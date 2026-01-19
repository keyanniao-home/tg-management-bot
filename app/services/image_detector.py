"""
Image detector service for detecting objects in images.

This service communicates with an external detection HTTP service.
"""

import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, List, Dict
from loguru import logger
import httpx


class ImageDetectorService:
    """
    Service for detecting objects in images via HTTP API.

    Manages external detection service process and communicates via REST API.
    """

    _instance: Optional['ImageDetectorService'] = None
    _process: Optional[subprocess.Popen] = None
    _service_url = "http://localhost:3000/api/inference"
    _api_key: str = "your-secret-key"
    _available = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if self._process is None:
            self._api_key = os.environ.get('API_KEY', 'your-secret-key')
            self._start_detection_service()

    def _start_detection_service(self):
        """Start the external detection service in a daemon thread."""
        def start_service():
            try:
                # Determine system and architecture
                system = platform.system().lower()  # 'linux', 'windows', 'darwin'
                machine = platform.machine().lower()  # 'x86_64', 'amd64', 'arm64', etc.

                logger.info(f"Detected system: {system}, architecture: {machine}")

                # Map architecture to binary naming
                if machine in ['x86_64', 'amd64', 'x64']:
                    arch = 'amd64'
                elif machine in ['aarch64', 'arm64']:
                    arch = 'arm64'
                else:
                    logger.error(f"Unsupported architecture: {machine}")
                    return

                # Build executable path
                project_root = Path(__file__).parent.parent.parent
                service_dir = project_root / 'stripe_done_object_recognition'

                if system == 'windows':
                    executable = service_dir / f'windows_{arch}.exe'
                elif system == 'linux':
                    executable = service_dir / f'linux_{arch}'
                elif system == 'darwin':
                    executable = service_dir / f'darwin_{arch}'
                else:
                    logger.error(f"Unsupported system: {system}")
                    return

                if not executable.exists():
                    logger.error(f"Detection service executable not found: {executable}")
                    logger.error("Image detection will be disabled.")
                    return

                # Make executable (Unix-like systems)
                if system in ['linux', 'darwin']:
                    executable.chmod(0o755)

                # Set environment variables
                env = os.environ.copy()
                env['API_KEY'] = self._api_key

                # Linux needs ORT_DYLIB_PATH for onnxruntime
                if system == 'linux':
                    ort_lib = service_dir / 'libonnxruntime.so'
                    if ort_lib.exists():
                        env['ORT_DYLIB_PATH'] = str(ort_lib)
                        logger.info(f"Set ORT_DYLIB_PATH={ort_lib}")
                    else:
                        logger.warning(f"ONNX Runtime library not found: {ort_lib}")

                # Start process
                logger.info(f"Starting detection service: {executable}")
                self._process = subprocess.Popen(
                    [str(executable)],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(service_dir)
                )

                # Wait for service to be ready
                max_retries = 30
                for i in range(max_retries):
                    try:
                        response = httpx.get("http://localhost:3000", timeout=1.0)
                        if response.status_code == 200:
                            logger.success("Detection service started successfully!")
                            self._available = True
                            return
                    except Exception:
                        pass
                    time.sleep(1)
                    if i % 5 == 0:
                        logger.debug(f"Waiting for detection service... ({i+1}/{max_retries})")

                logger.error("Detection service failed to start within timeout")

            except Exception as e:
                logger.error(f"Failed to start detection service: {e}")
                logger.error("Image detection will be disabled.")

        # Start in daemon thread
        thread = threading.Thread(target=start_service, daemon=True, name="DetectionServiceStarter")
        thread.start()

    def is_available(self) -> bool:
        """Check if the detector service is available."""
        return self._available

    async def detect_from_bytes(self, image_bytes: bytes) -> List[Dict]:
        """
        Detect objects in an image from bytes.

        Args:
            image_bytes: Image data in bytes

        Returns:
            List of detection results with 'confidence' and 'class' keys
        """
        if not self.is_available():
            return []

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
                    logger.error(f"Detection API error: {response.status_code} {response.text}")
                    return []

                # Parse response
                data = response.json()
                results = data.get('results', [])

                if not results:
                    return []

                # Extract detections from first result
                detections = results[0].get('detections', [])

                # Convert to expected format
                formatted_results = []
                for det in detections:
                    formatted_results.append({
                        'confidence': det.get('confidence', 0.0),
                        'class': 'done',  # Fixed class name
                        'bbox': {
                            'x': det.get('x', 0),
                            'y': det.get('y', 0),
                            'width': det.get('width', 0),
                            'height': det.get('height', 0)
                        }
                    })

                return formatted_results

        except Exception as e:
            logger.error(f"Error calling detection API: {e}")
            return []

    def filter_by_confidence(self, results: list, min_confidence: float = 0.1) -> list:
        """
        Filter detection results by minimum confidence threshold.

        Args:
            results: Detection results from detect_from_bytes()
            min_confidence: Minimum confidence threshold (0.1 to 0.99)

        Returns:
            Filtered detection results
        """
        if not results:
            return []

        # Clamp min_confidence to valid range
        min_confidence = max(0.1, min(0.99, min_confidence))

        return [r for r in results if r.get('confidence', 0.0) >= min_confidence]

    def has_detections(self, results: list) -> bool:
        """
        Check if detection results contain any objects.

        Args:
            results: Detection results from detect_from_bytes()

        Returns:
            True if objects were detected
        """
        return len(results) > 0

    def shutdown(self):
        """Shutdown the detection service process."""
        if self._process:
            logger.info("Shutting down detection service...")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Detection service did not terminate, killing...")
                self._process.kill()
            logger.info("Detection service stopped")


# Global singleton instance
image_detector = ImageDetectorService()
