"""
NSFW detector service for detecting NSFW content in images.

This service communicates with an external NSFW detection HTTP service.
"""

import os
from typing import Optional, List, Dict
from loguru import logger
import httpx


class NsfwDetectorService:
    """
    Service for detecting NSFW content in images via HTTP API.

    Uses external NSFW detection service to classify images into:
    - porn: 色情内容
    - hentai: 色情动漫
    - sexy: 性感内容
    - neutral: 正常内容
    - drawings: 绘画内容
    """

    _instance: Optional['NsfwDetectorService'] = None
    _service_url = "http://127.0.0.1:3000/api/nsfw-detect"
    _api_key: str = "your-secret-key"
    _available = True  # Assume service is available

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize NSFW detector service."""
        if not hasattr(self, '_initialized'):
            self._api_key = os.environ.get('API_KEY', 'your-secret-key')
            self._initialized = True
            logger.info("NSFW detector service initialized")

    def is_available(self) -> bool:
        """Check if the detector service is available."""
        return self._available

    async def detect_from_bytes(self, image_bytes: bytes) -> Optional[Dict]:
        """
        Detect NSFW content in an image from bytes.

        Args:
            image_bytes: Image data in bytes

        Returns:
            Detection result with format:
            {
                'filename': str,
                'nsfw_result': {
                    'drawings': float,
                    'hentai': float,
                    'neutral': float,
                    'porn': float,
                    'sexy': float
                },
                'dominantClass': str,  # 'porn', 'hentai', 'sexy', 'neutral', 'drawings'
                'dominantScore': float,
                'isNSFW': bool
            }
        """
        if not self.is_available():
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Prepare multipart form data
                files = {'images': ('image.jpg', image_bytes, 'image/jpeg')}
                headers = {'Authorization': f'Bearer {self._api_key}'}

                # Call API
                response = await client.post(
                    self._service_url,
                    files=files,
                    headers=headers
                )

                if response.status_code != 200:
                    logger.error(f"NSFW detection API error: {response.status_code} {response.text}")
                    return None

                # Parse response
                data = response.json()
                results = data.get('results', [])

                if not results:
                    return None

                # Return first result
                return results[0]

        except Exception as e:
            logger.error(f"Error calling NSFW detection API: {e}")
            return None

    def get_nsfw_type(self, result: Optional[Dict], threshold: float = 0.8) -> Optional[str]:
        """
        Get NSFW type from detection result based on threshold.

        Args:
            result: Detection result from detect_from_bytes()
            threshold: Minimum score threshold (default: 0.8)

        Returns:
            NSFW type: 'porn', 'hentai', 'sexy', or None if below threshold or neutral
        """
        if not result:
            return None

        dominant_class = result.get('dominantClass', '')
        dominant_score = result.get('dominantScore', 0.0)

        # Check if score meets threshold and is NSFW
        if dominant_score >= threshold and dominant_class in ['porn', 'hentai', 'sexy']:
            return dominant_class

        return None

    def get_reaction_emoji(self, nsfw_type: Optional[str]) -> Optional[str]:
        """
        Get reaction emoji for NSFW type.

        Args:
            nsfw_type: 'porn', 'hentai', 'sexy', or None

        Returns:
            Emoji string or None
        """
        emoji_map = {
            'porn': '🍌',      # 色情用香蕉回应
            'hentai': '❤️‍🔥',  # 色情动漫用火热的心回应
            'sexy': '💋'       # 性感用亲吻回应
        }
        return emoji_map.get(nsfw_type)


# Global singleton instance
nsfw_detector = NsfwDetectorService()
