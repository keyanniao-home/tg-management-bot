"""
Image detection queue system.

Handles image detection tasks asynchronously with hash-based deduplication.
"""

import asyncio
import io
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes
from sqlmodel import Session
from sqlalchemy.orm.attributes import flag_modified
from PIL import Image
import imagehash

from app.models import Message
from app.database.connection import engine


class SimilarityLRUCache:
    """LRU Cache with similarity-based matching using Hamming distance and NSFW detection results."""

    def __init__(self, capacity: int = 1000, hamming_threshold: int = 12):
        """
        Initialize similarity cache.

        Args:
            capacity: Maximum cache size
            hamming_threshold: Max Hamming distance to consider as duplicate (0-64 for hash_size=8)
                              - 0: exact match only
                              - 5-10: very similar images
                              - 10-15: similar images (recommended for compression)
                              - >20: loosely similar
                              Note: for hash_size=16, the range is 0-256
        """
        # Store both hash and NSFW result: {hash_str: (ImageHash, nsfw_type_or_None)}
        self.cache: OrderedDict[str, Tuple[imagehash.ImageHash, Optional[str]]] = OrderedDict()
        self.capacity = capacity
        self.hamming_threshold = hamming_threshold

    def get(self, phash: imagehash.ImageHash) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if a similar hash exists in cache.

        Args:
            phash: ImageHash object to check

        Returns:
            Tuple of (is_duplicate, matched_hash_str or None, nsfw_type or None)
        """
        for key_str, (stored_hash, nsfw_type) in self.cache.items():
            distance = phash - stored_hash  # Hamming distance
            if distance <= self.hamming_threshold:
                # Move to end (most recently used)
                self.cache.move_to_end(key_str)
                return True, key_str, nsfw_type
        return False, None, None

    def put(self, phash: imagehash.ImageHash, nsfw_type: Optional[str] = None) -> str:
        """
        Add hash to cache with NSFW detection result.

        Args:
            phash: ImageHash object to store
            nsfw_type: NSFW type ('porn', 'hentai', 'sexy') or None if not NSFW

        Returns:
            String representation of the hash
        """
        key_str = str(phash)
        if key_str in self.cache:
            # Update NSFW result if provided
            old_hash, old_nsfw = self.cache[key_str]
            self.cache[key_str] = (old_hash, nsfw_type if nsfw_type else old_nsfw)
            self.cache.move_to_end(key_str)
        else:
            self.cache[key_str] = (phash, nsfw_type)
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
        return key_str

    def update_nsfw(self, hash_str: str, nsfw_type: Optional[str]):
        """
        Update NSFW result for an existing hash.

        Args:
            hash_str: Hash string to update
            nsfw_type: NSFW type or None
        """
        if hash_str in self.cache:
            phash, _ = self.cache[hash_str]
            self.cache[hash_str] = (phash, nsfw_type)
            self.cache.move_to_end(hash_str)

    def __len__(self) -> int:
        return len(self.cache)


@dataclass
class ImageDetectionTask:
    """Task for image detection."""
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    message: Message
    image_bytes: bytes
    image_hash: str


class ImageDetectionQueue:
    """
    Async queue for image detection tasks.

    Features:
    - Processes one task at a time
    - Perceptual hash-based deduplication with Hamming distance tolerance
    - Non-blocking async execution
    - Rate limiting: auto-blacklist users sending >5 images in 1 minute
    """

    # Rate limit configuration
    RATE_LIMIT_WINDOW = 60  # 1 minute window
    RATE_LIMIT_MAX = 5  # max 5 images per window
    BLACKLIST_DURATION = 300  # 5 minutes blacklist

    # Hash configuration
    HASH_SIZE = 16  # Larger hash size for better precision (default is 8)
    HAMMING_THRESHOLD = 20  # For hash_size=16, range is 0-256, 20 is reasonable for compressed images

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.hash_cache = SimilarityLRUCache(
            capacity=1000,
            hamming_threshold=self.HAMMING_THRESHOLD
        )
        self.worker_task: Optional[asyncio.Task] = None
        self._running = False

        # Rate limiting: {user_id: [timestamp1, timestamp2, ...]}
        self.user_image_history: Dict[int, List[float]] = defaultdict(list)

        # Blacklist: {user_id: blacklist_until_timestamp}
        self.image_blacklist: Dict[int, float] = {}

    def start(self):
        """Start the background worker."""
        if not self._running:
            self._running = True
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("Image detection queue worker started")

    async def stop(self):
        """Stop the background worker."""
        self._running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Image detection queue worker stopped")

    def compute_hash(self, image_bytes: bytes) -> Optional[imagehash.ImageHash]:
        """
        Compute Perceptual Hash (pHash) of image bytes.

        pHash is a perceptual hashing algorithm that generates similar hashes
        for visually similar images, enabling detection of near-duplicate images
        even after compression or resizing.

        Args:
            image_bytes: Raw image data in bytes

        Returns:
            ImageHash object for distance comparison, or None on error
        """
        try:
            # Open image from bytes
            image = Image.open(io.BytesIO(image_bytes))

            # Convert to RGB if necessary (handles RGBA, P mode, etc.)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')

            # Compute perceptual hash with larger hash_size for better precision
            phash = imagehash.phash(image, hash_size=self.HASH_SIZE)

            return phash
        except Exception as e:
            logger.error(f"Error computing perceptual hash: {e}")
            return None

    def _check_and_update_rate_limit(self, user_id: int) -> bool:
        """
        Check if user exceeds rate limit and update blacklist if needed.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user is allowed (not rate limited), False if blacklisted
        """
        current_time = time.time()

        # Check if user is currently blacklisted
        if user_id in self.image_blacklist:
            blacklist_until = self.image_blacklist[user_id]
            if current_time < blacklist_until:
                remaining = int(blacklist_until - current_time)
                logger.debug(f"User {user_id} is blacklisted for {remaining}s more")
                return False
            else:
                # Blacklist expired, remove from blacklist
                del self.image_blacklist[user_id]
                logger.info(f"User {user_id} removed from image blacklist (expired)")

        # Clean old timestamps (outside rate limit window)
        cutoff_time = current_time - self.RATE_LIMIT_WINDOW
        self.user_image_history[user_id] = [
            ts for ts in self.user_image_history[user_id]
            if ts > cutoff_time
        ]

        # Add current timestamp
        self.user_image_history[user_id].append(current_time)

        # Check if exceeded rate limit
        image_count = len(self.user_image_history[user_id])
        if image_count > self.RATE_LIMIT_MAX:
            # Add to blacklist
            blacklist_until = current_time + self.BLACKLIST_DURATION
            self.image_blacklist[user_id] = blacklist_until
            logger.warning(
                f"⚠️ User {user_id} exceeded rate limit "
                f"({image_count} images in {self.RATE_LIMIT_WINDOW}s), "
                f"blacklisted for {self.BLACKLIST_DURATION}s"
            )
            return False

        return True

    async def enqueue(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                      message: Message, image_bytes: bytes) -> bool:
        """
        Add image detection task to queue.

        Args:
            update: Telegram update
            context: Bot context
            message: Database message object
            image_bytes: Image data

        Returns:
            True if task was enqueued, False if skipped (duplicate/blacklisted/error)
        """
        from app.models import GroupConfig
        from sqlmodel import select

        # Get user ID
        user_id = message.user_id if message.user_id else message.sender_chat_id
        if user_id is None:
            logger.warning(f"Cannot determine user_id for message {message.message_id}")
            return False

        # Check rate limit and blacklist
        if not self._check_and_update_rate_limit(user_id):
            logger.debug(f"Skipping image from blacklisted user {user_id} (message {message.message_id})")
            return False

        # Compute image hash
        image_hash = self.compute_hash(image_bytes)
        if image_hash is None:
            logger.warning(f"Failed to compute hash for message {message.message_id}")
            return False

        # Check if similar hash exists in cache
        is_duplicate, matched_hash, cached_nsfw_type = self.hash_cache.get(image_hash)
        if is_duplicate:
            logger.debug(
                f"Similar image found in message {message.message_id} "
                f"(matched with existing hash {matched_hash[:16]}...)"
            )

            # If this is a duplicate NSFW image and auto-delete is enabled, delete it
            if cached_nsfw_type:
                # Get group config to check if auto-delete is enabled
                with Session(engine) as session:
                    group_statement = select(GroupConfig).where(GroupConfig.id == message.group_id)
                    group_config = session.exec(group_statement).first()

                    if group_config:
                        nsfw_auto_delete = group_config.config.get('leaderboards', {}).get('nsfw', {}).get('auto_delete', False)

                        if nsfw_auto_delete:
                            try:
                                await context.bot.delete_message(
                                    chat_id=update.effective_chat.id,
                                    message_id=update.message.message_id
                                )
                                logger.info(
                                    f"🗑️ Auto-deleted duplicate NSFW image in message {message.message_id} "
                                    f"(type: {cached_nsfw_type}, not counted in leaderboard)"
                                )

                                # Mark as deleted in database
                                db_statement = select(Message).where(Message.id == message.id)
                                db_message = session.exec(db_statement).first()
                                if db_message:
                                    db_message.is_deleted = True
                                    session.add(db_message)
                                    session.commit()
                            except Exception as e:
                                logger.error(f"Failed to auto-delete duplicate NSFW message {message.message_id}: {e}")

            # Don't enqueue duplicate images (whether NSFW or not)
            return False

        # Add to cache immediately to prevent duplicates in queue (without NSFW result yet)
        hash_str = self.hash_cache.put(image_hash)

        # Create task and enqueue
        task = ImageDetectionTask(
            update=update,
            context=context,
            message=message,
            image_bytes=image_bytes,
            image_hash=hash_str
        )

        await self.queue.put(task)
        logger.debug(
            f"Enqueued image detection task for message {message.message_id} "
            f"(hash: {hash_str[:16]}..., queue size: {self.queue.qsize()})"
        )
        return True

    async def _worker(self):
        """Background worker that processes tasks one at a time."""
        logger.info("Image detection worker started")

        while self._running:
            try:
                # Wait for next task (with timeout to allow checking _running flag)
                try:
                    task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Process task
                await self._process_task(task)

                # Mark task as done
                self.queue.task_done()

            except asyncio.CancelledError:
                logger.info("Worker received cancellation")
                break
            except Exception as e:
                logger.error(f"Error in worker: {e}")
                await asyncio.sleep(1)  # Brief pause on error

        logger.info("Image detection worker stopped")

    async def _process_task(self, task: ImageDetectionTask):
        """
        Process a single image detection task.

        Args:
            task: Image detection task
        """
        from app.services.image_detector import image_detector
        from app.services.nsfw_detector import nsfw_detector
        from app.models import GroupConfig

        try:
            message_id = task.message.message_id
            logger.debug(f"Processing image detection for message {message_id}...")

            # Get group config for confidence threshold
            with Session(engine) as session:
                # Re-fetch message to avoid detached instance issues
                from sqlmodel import select
                statement = select(Message).where(Message.id == task.message.id)
                db_message = session.exec(statement).first()

                if not db_message:
                    logger.warning(f"Message {message_id} not found in database")
                    return

                # Get group config
                group_statement = select(GroupConfig).where(GroupConfig.id == db_message.group_id)
                group_config = session.exec(group_statement).first()

                # Get minimum confidence threshold from config (default: 0.1)
                min_confidence = 0.1
                if group_config:
                    min_confidence = group_config.config.get('image_detection', {}).get('min_confidence', 0.1)

                # Check if NSFW leaderboard is enabled
                nsfw_enabled = False
                nsfw_threshold = 0.8
                nsfw_auto_delete = False
                if group_config:
                    nsfw_enabled = group_config.config.get('leaderboards', {}).get('nsfw', {}).get('enabled', False)
                    nsfw_threshold = group_config.config.get('leaderboards', {}).get('nsfw', {}).get('threshold', 0.8)
                    nsfw_auto_delete = group_config.config.get('leaderboards', {}).get('nsfw', {}).get('auto_delete', False)

                # Run DONE detection
                results = await image_detector.detect_from_bytes(task.image_bytes)

                # Filter results by confidence threshold
                filtered_results = image_detector.filter_by_confidence(results, min_confidence)

                # Initialize extra_data if needed
                if db_message.extra_data is None:
                    db_message.extra_data = {}

                # Process DONE detection results
                if image_detector.has_detections(filtered_results):
                    logger.info(
                        f"✅ Detected {len(results)} objects in message {message_id}, "
                        f"{len(filtered_results)} passed confidence threshold {min_confidence}"
                    )

                    db_message.extra_data['is_done_image'] = True
                    db_message.extra_data['detection_count'] = len(filtered_results)
                    db_message.extra_data['detection_results'] = [
                        {
                            'confidence': r['confidence'],
                            'class': r['class']
                        }
                        for r in filtered_results
                    ]

                    # Add 💯 reaction
                    try:
                        await task.context.bot.set_message_reaction(
                            chat_id=task.update.effective_chat.id,
                            message_id=task.update.message.message_id,
                            reaction="💯"
                        )
                        logger.debug(f"Added 💯 reaction to message {message_id}")
                    except Exception as e:
                        logger.error(f"Failed to add reaction to message {message_id}: {e}")
                else:
                    if results:
                        logger.debug(
                            f"No objects passed confidence threshold {min_confidence} "
                            f"in message {message_id} ({len(results)} total detections)"
                        )
                    else:
                        logger.debug(f"No objects detected in message {message_id}")

                # Run NSFW detection if enabled
                nsfw_type_for_cache = None  # Track NSFW type to update cache
                if nsfw_enabled:
                    logger.debug(f"Running NSFW detection for message {message_id}...")
                    nsfw_result = await nsfw_detector.detect_from_bytes(task.image_bytes)

                    if nsfw_result:
                        # Get NSFW type based on threshold
                        nsfw_type = nsfw_detector.get_nsfw_type(nsfw_result, nsfw_threshold)

                        # Store NSFW result in extra_data
                        db_message.extra_data['nsfw_result'] = nsfw_result.get('nsfw_result', {})
                        db_message.extra_data['nsfw_dominant_class'] = nsfw_result.get('dominantClass', 'neutral')
                        db_message.extra_data['nsfw_dominant_score'] = nsfw_result.get('dominantScore', 0.0)
                        db_message.extra_data['is_nsfw'] = nsfw_result.get('isNSFW', False)

                        # Store the detected type if meets threshold
                        if nsfw_type:
                            db_message.extra_data['nsfw_type'] = nsfw_type
                            nsfw_type_for_cache = nsfw_type  # Save for cache update
                            logger.info(
                                f"🔞 NSFW detected in message {message_id}: {nsfw_type} "
                                f"(score: {nsfw_result.get('dominantScore', 0.0):.2f})"
                            )

                            # Auto delete if enabled
                            if nsfw_auto_delete:
                                try:
                                    await task.context.bot.delete_message(
                                        chat_id=task.update.effective_chat.id,
                                        message_id=task.update.message.message_id
                                    )
                                    logger.info(f"🗑️ Auto-deleted NSFW message {message_id} ({nsfw_type})")

                                    # Mark as deleted in database
                                    db_message.is_deleted = True
                                except Exception as e:
                                    logger.error(f"Failed to auto-delete NSFW message {message_id}: {e}")
                            else:
                                # Add reaction emoji only if not auto-deleting
                                reaction_emoji = nsfw_detector.get_reaction_emoji(nsfw_type)
                                if reaction_emoji:
                                    try:
                                        await task.context.bot.set_message_reaction(
                                            chat_id=task.update.effective_chat.id,
                                            message_id=task.update.message.message_id,
                                            reaction=reaction_emoji
                                        )
                                        logger.debug(f"Added {reaction_emoji} reaction to message {message_id}")
                                    except Exception as e:
                                        logger.error(f"Failed to add NSFW reaction to message {message_id}: {e}")
                        else:
                            logger.debug(
                                f"NSFW score below threshold {nsfw_threshold} in message {message_id} "
                                f"({nsfw_result.get('dominantClass', 'neutral')}: "
                                f"{nsfw_result.get('dominantScore', 0.0):.2f})"
                            )
                    else:
                        logger.debug(f"NSFW detection returned no result for message {message_id}")

                # Update cache with NSFW result (if any)
                if task.image_hash:
                    self.hash_cache.update_nsfw(task.image_hash, nsfw_type_for_cache)
                    if nsfw_type_for_cache:
                        logger.debug(f"Updated cache with NSFW type {nsfw_type_for_cache} for hash {task.image_hash[:16]}...")

                # Mark field as modified and commit
                flag_modified(db_message, "extra_data")
                session.add(db_message)
                session.commit()
                logger.debug(f"Updated database for message {message_id}")

        except Exception as e:
            logger.error(f"Error processing detection task for message {task.message.message_id}: {e}")


# Global queue instance
image_queue = ImageDetectionQueue()
