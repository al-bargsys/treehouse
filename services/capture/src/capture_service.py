#!/usr/bin/env python3
"""
Capture service for bird monitoring system.
Captures frames from webcam (via RTSP stream or direct device) and publishes to Redis.
"""
import cv2
import os
import sys
import time
import json
import redis
import warnings
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, Response
# Suppress OpenCV/h264 decoder warnings
# These are common with RTSP streams and usually don't affect functionality
# FFmpeg handles these errors gracefully and continues decoding
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
os.environ['AV_LOG_LEVEL'] = 'error'  # FFmpeg/libav log level
os.environ['GST_DEBUG'] = '0'  # GStreamer debug level (if using GStreamer backend)
os.environ['GST_DEBUG_NO_COLOR'] = '1'
warnings.filterwarnings('ignore', category=UserWarning)

# Create a custom stderr filter to suppress h264 decoder warnings
# These warnings (co located POCs, mmco failures, etc.) are non-fatal
# FFmpeg writes directly to the file descriptor, so we need to intercept at a lower level
class FFmpegErrorFilter:
    """Filter out non-critical FFmpeg/h264 decoder warnings."""
    IGNORE_PATTERNS = [
        'co located POCs unavailable',
        'mmco: unref short failure',
        'error while decoding MB',
        'bytestream',
        'reference picture missing',
        'Missing reference picture',
        'illegal short term buffer state',
        'Invalid level prefix',
        'corrupted macroblock',
        '[h264 @',  # All h264 decoder messages
    ]
    
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
        self.buffer = ''
    
    def write(self, message):
        if not message:
            return
        
        # Buffer partial lines
        self.buffer += message
        lines = self.buffer.split('\n')
        self.buffer = lines[-1]  # Keep incomplete line in buffer
        
        # Process complete lines
        for line in lines[:-1]:
            if line.strip():
                # Check if line contains any ignore patterns
                line_lower = line.lower()
                should_filter = any(pattern.lower() in line_lower for pattern in self.IGNORE_PATTERNS)
                
                if not should_filter:
                    self.original_stderr.write(line + '\n')
    
    def flush(self):
        # Flush any remaining buffer
        if self.buffer.strip():
            line_lower = self.buffer.lower()
            should_filter = any(pattern.lower() in line_lower for pattern in self.IGNORE_PATTERNS)
            if not should_filter:
                self.original_stderr.write(self.buffer)
            self.buffer = ''
        self.original_stderr.flush()

# Redirect stderr to filter
# Note: FFmpeg/OpenCV may write directly to file descriptor 2, bypassing Python's stderr
# This filter catches Python-level writes. Some FFmpeg messages may still appear but are harmless.
if not sys.stderr.isatty():
    sys.stderr = FFmpegErrorFilter(sys.stderr)

# Force unbuffered output for Docker logs
# Use line buffering instead of unbuffered (0) which can cause issues
if sys.stdout.isatty():
    # Terminal mode - use line buffering
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', 1)
else:
    # Non-terminal (Docker) - Python's default buffering should work with flush=True
    pass

class CaptureService:
    def __init__(self, config):
        self.config = config
        self.redis_client = None
        self.cap = None
        self.background_accumulator = None  # For gradual background updates
        self.running = False
        # Error tracking metrics
        self.frame_errors = 0
        self.corrupted_frames = 0
        self.total_frames = 0
        # Use MOG2 background subtractor - handles lighting changes and camera auto-adjustments
        # Lower varThreshold = more sensitive to motion
        mog2_var_threshold = self.config.get('motion_mog2_var_threshold', 25)
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500,  # Number of frames to use for background model
            varThreshold=mog2_var_threshold,  # Threshold on the squared Mahalanobis distance (lower = more sensitive)
            detectShadows=True  # Detect and mark shadows
        )
        
    def connect_redis(self):
        """Connect to Redis server."""
        print("Attempting to connect to Redis...", flush=True)
        try:
            redis_host = self.config.get('redis_host', 'redis')
            redis_port = self.config.get('redis_port', 6379)
            print(f"Connecting to Redis at {redis_host}:{redis_port}...", flush=True)
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=0,
                decode_responses=False,  # We'll send binary data
                socket_connect_timeout=5,
                socket_timeout=5
            )
            print("Sending ping to Redis...", flush=True)
            self.redis_client.ping()
            print(f"✓ Connected to Redis at {redis_host}:{redis_port}", flush=True)
            return True
        except Exception as e:
            print(f"✗ Failed to connect to Redis: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return False
    
    def open_camera(self):
        """Open camera stream (RTSP or direct device)."""
        camera_source = self.config.get('camera_url') or self.config.get('camera_device', 0)
        
        print(f"Opening camera source: {camera_source}", flush=True)
        
        # Check if it's an RTSP URL
        if isinstance(camera_source, str) and camera_source.startswith(('rtsp://', 'http://', 'https://')):
            print("Detected RTSP/HTTP stream", flush=True)
            print("Creating VideoCapture object...", flush=True)
            self.cap = cv2.VideoCapture(camera_source, cv2.CAP_FFMPEG)
            print("VideoCapture object created, checking if opened...", flush=True)
            
            # Set RTSP-specific options for better error handling
            # Use TCP transport for more reliable streaming (less packet loss)
            # Note: These options may not all be available depending on OpenCV build
            try:
                # Buffer size: Increased for stability (latency not critical)
                # Larger buffer helps prevent decoder errors from frame drops
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 10)  # Larger buffer for stability
            except:
                pass  # Some backends don't support this property
        else:
            # Direct device access
            print(f"Using direct device access: {camera_source}", flush=True)
            self.cap = cv2.VideoCapture(int(camera_source))
        
        # Give it a moment to connect
        import time
        time.sleep(1)
        
        if not self.cap.isOpened():
            print(f"ERROR: Could not open camera source: {camera_source}", flush=True)
            return False
        print("Camera opened successfully, getting properties...", flush=True)
        
        # Set camera properties if specified
        if 'resolution' in self.config:
            width, height = self.config['resolution']
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        
        if 'fps' in self.config:
            self.cap.set(cv2.CAP_PROP_FPS, self.config['fps'])
        
        # Get actual properties
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        print(f"✓ Camera opened: {width}x{height} @ {fps} FPS", flush=True)
        return True
    
    def is_valid_frame(self, frame):
        """Validate that a frame is usable (not None, has expected dimensions)."""
        if frame is None:
            return False
        
        # Check if frame has valid dimensions
        if len(frame.shape) < 2:
            return False
        
        height, width = frame.shape[:2]
        if width < 10 or height < 10:  # Minimum reasonable dimensions
            return False
        
        # Check if frame is not completely black or white (basic corruption check)
        # This is a simple heuristic - a completely uniform frame might indicate corruption
        if len(frame.shape) == 3:
            # Color frame
            std_dev = frame.std()
            if std_dev < 1.0:  # Very low variation might indicate corruption
                return False
        else:
            # Grayscale frame
            std_dev = frame.std()
            if std_dev < 1.0:
                return False
        
        return True
    
    def detect_motion(self, frame, background):
        """Motion detection using MOG2 background subtractor (handles lighting changes)."""
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(frame, (21, 21), 0)
        
        # Apply background subtractor (MOG2 handles auto-exposure/white-balance changes)
        fg_mask = self.bg_subtractor.apply(blurred)
        
        # Remove shadows (shadows are marked as 127, we want only foreground as 255)
        # Lower threshold = more sensitive (picks up more motion)
        binary_threshold = self.config.get('motion_binary_threshold', 150)
        _, fg_mask = cv2.threshold(fg_mask, binary_threshold, 255, cv2.THRESH_BINARY)
        
        # Apply morphological operations to remove noise and fill gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        
        # Calculate motion area
        motion_area = cv2.countNonZero(fg_mask)
        min_area = self.config.get('motion_min_area', 10000)
        
        motion_detected = motion_area > min_area
        
        # Debug output - only log occasionally to avoid spam
        # Motion detection logging is handled at capture time, not here
        
        return motion_detected, frame
    
    def save_image(self, frame, timestamp):
        """Save image to disk with high quality JPEG encoding."""
        images_path = Path(self.config.get('images_path', 'data/images'))
        date_path = images_path / timestamp.strftime('%Y-%m') / timestamp.strftime('%d')
        date_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"{timestamp.strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
        filepath = date_path / filename
        
        # Use high quality JPEG (95/100) for still images - quality over file size
        jpeg_quality = self.config.get('jpeg_quality', 95)
        cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        return str(filepath.relative_to(images_path))
    
    def measure_sharpness(self, frame):
        """Measure frame sharpness using Laplacian variance (higher = sharper)."""
        if frame is None:
            return 0.0
        
        # Convert to grayscale if needed
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        
        # Apply Laplacian filter and compute variance
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = laplacian.var()
        return sharpness
    
    def capture_frame(self):
        """Capture a single frame from the camera."""
        if not self.cap or not self.cap.isOpened():
            return None
        
        # Read a few frames to get a fresh one (skip buffered frames)
        for _ in range(3):
            ret, frame = self.cap.read()
            if not ret or frame is None:
                return None
        
        # Validate frame
        if not self.is_valid_frame(frame):
            return None
        
        return frame
    
    def capture_best_frame(self, num_samples=5, sample_interval=0.1):
        """
        Capture multiple frames and return the sharpest one.
        This helps avoid motion blur by selecting the frame with least blur.
        
        Args:
            num_samples: Number of frames to sample
            sample_interval: Time in seconds between samples
        
        Returns:
            Best (sharpest) frame, or None if capture fails
        """
        if not self.cap or not self.cap.isOpened():
            return None
        
        best_frame = None
        best_sharpness = 0.0
        
        # Sample multiple frames and pick the sharpest
        for i in range(num_samples):
            ret, frame = self.cap.read()
            if ret and frame is not None and self.is_valid_frame(frame):
                sharpness = self.measure_sharpness(frame)
                if sharpness > best_sharpness:
                    best_sharpness = sharpness
                    best_frame = frame.copy()
            
            # Wait between samples (except on last iteration)
            if i < num_samples - 1:
                time.sleep(sample_interval)
        
        return best_frame
    
    def publish_to_redis(self, image_path, metadata):
        """Publish image info to Redis queue."""
        # Metadata should already have timestamp as string, but handle both cases
        message = {
            'image_path': image_path,
            'timestamp': metadata.get('timestamp', datetime.now().isoformat()),
            'motion_score': metadata.get('motion_score', 0),
            'source': metadata.get('source', 'unknown')
        }
        
        queue_name = self.config.get('redis_queue', 'images')
        try:
            self.redis_client.lpush(queue_name, json.dumps(message))
            print(f"Published to Redis queue '{queue_name}': {image_path}", flush=True)
        except Exception as e:
            print(f"Error publishing to Redis: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    def start_http_server(self):
        """Start HTTP server for live frame capture."""
        app = Flask(__name__)
        
        @app.route('/capture/live', methods=['GET'])
        def get_live_frame():
            """Capture and return a live frame as JPEG."""
            frame = self.capture_frame()
            if frame is None:
                return Response(
                    "Failed to capture frame",
                    status=503,
                    mimetype='text/plain'
                )
            
            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                return Response(
                    "Failed to encode frame",
                    status=500,
                    mimetype='text/plain'
                )
            
            return Response(
                buffer.tobytes(),
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            )
        
        @app.route('/capture/health', methods=['GET'])
        def health():
            """Health check endpoint."""
            if self.cap and self.cap.isOpened():
                return {'status': 'healthy', 'camera': 'connected'}, 200
            else:
                return {'status': 'unhealthy', 'camera': 'disconnected'}, 503
        
        # Get port from config or use default
        port = self.config.get('http_port', 8080)
        host = self.config.get('http_host', '0.0.0.0')
        
        print(f"Starting HTTP server on {host}:{port} for live capture", flush=True)
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    
    def run(self):
        """Main capture loop."""
        if not self.connect_redis():
            print("Failed to connect to Redis, exiting", flush=True)
            return False
        
        if not self.open_camera():
            print("Failed to open camera, exiting", flush=True)
            return False
        
        # Start HTTP server in a separate thread
        http_thread = threading.Thread(target=self.start_http_server, daemon=True)
        http_thread.start()
        print("HTTP server thread started", flush=True)
        
        self.running = True
        background = None
        last_capture_time = time.time()  # Initialize to current time, not 0
        last_status_time = time.time()
        cooldown = self.config.get('motion_cooldown', 10.0)  # seconds
        motion_delay = self.config.get('motion_delay', 1.5)  # seconds to wait after motion detected before capturing (increased for sharper images)
        capture_samples = self.config.get('capture_samples', 5)  # number of frames to sample when capturing
        capture_sample_interval = self.config.get('capture_sample_interval', 0.1)  # seconds between samples
        frame_count = 0
        motion_detections = 0
        # Calculate warmup frames based on FPS (5 seconds worth)
        fps = self.config.get('fps', 15)
        warmup_frames = int(fps * 5)  # Let MOG2 learn background for ~5 seconds
        sleep_time = 1.0 / fps  # Sleep for one frame duration to match FPS
        motion_detected_time = None  # Track when motion was first detected
        
        print("\nStarting capture loop...", flush=True)
        print(f"MOG2 background model warming up ({warmup_frames} frames)...", flush=True)
        print(f"Target FPS: {fps} (sleep: {sleep_time:.3f}s per frame)", flush=True)
        print("Press Ctrl+C to stop\n", flush=True)
        
        try:
            while self.running:
                ret, frame = self.cap.read()
                frame_count += 1
                self.total_frames += 1
                
                if not ret or frame is None:
                    self.frame_errors += 1
                    # Only log occasionally to avoid spam
                    if self.frame_errors % 100 == 0:
                        print(f"Warning: Failed to read frame (total errors: {self.frame_errors})", flush=True)
                    time.sleep(0.1)
                    continue
                
                # Validate frame quality
                if not self.is_valid_frame(frame):
                    self.corrupted_frames += 1
                    # Only log occasionally
                    if self.corrupted_frames % 100 == 0:
                        print(f"Warning: Skipped corrupted frame (total corrupted: {self.corrupted_frames})", flush=True)
                    continue
                
                # Print status every 10 seconds
                current_time = time.time()
                if current_time - last_status_time >= 10:
                    time_since_capture = int(current_time - last_capture_time) if last_capture_time > 0 else 0
                    error_rate = (self.frame_errors + self.corrupted_frames) / max(self.total_frames, 1) * 100
                    print(f"Status: Processing frames... ({frame_count} frames, {motion_detections} motion events, {time_since_capture}s since last capture, {error_rate:.1f}% error rate)", flush=True)
                    last_status_time = current_time
                
                # Initialize background tracking (MOG2 handles this internally, but we track for status)
                if background is None:
                    background = frame.copy()  # Keep for reference, but MOG2 does the real work
                
                # During warmup, let MOG2 learn the background without detecting motion
                if frame_count < warmup_frames:
                    # Apply frames to MOG2 but don't detect motion yet
                    blurred = cv2.GaussianBlur(frame, (21, 21), 0)
                    self.bg_subtractor.apply(blurred)  # Feed to MOG2 for learning
                    if frame_count == warmup_frames - 1:
                        print(f"✓ Background model warmed up after {warmup_frames} frames", flush=True)
                    motion_detected = False
                else:
                    # MOG2 background subtractor automatically adapts to lighting changes
                    # No need to manually update background - it learns continuously
                    
                    # Detect motion (MOG2 handles background adaptation automatically)
                    motion_detected, _ = self.detect_motion(frame, background)
                
                # Track when motion is first detected
                if motion_detected:
                    if motion_detected_time is None:
                        motion_detected_time = current_time
                else:
                    motion_detected_time = None  # Reset if motion stops
                
                # If motion detected, cooldown expired, and delay has passed, capture and publish
                should_capture = (
                    motion_detected and 
                    (current_time - last_capture_time) >= cooldown and
                    motion_detected_time is not None and
                    (current_time - motion_detected_time) >= motion_delay
                )
                
                if should_capture:
                    motion_detections += 1
                    time_since_last = current_time - last_capture_time
                    print(f"✓ Motion detected, waiting for motion to settle... (event #{motion_detections}, {time_since_last:.1f}s since last capture, {current_time - motion_detected_time:.1f}s after motion start)", flush=True)
                    
                    # Wait a bit more for motion to settle, then capture the sharpest frame
                    time.sleep(0.3)  # Additional brief wait for motion to settle
                    
                    # Capture multiple frames and pick the sharpest one
                    best_frame = self.capture_best_frame(
                        num_samples=capture_samples,
                        sample_interval=capture_sample_interval
                    )
                    
                    if best_frame is None:
                        print(f"Warning: Failed to capture best frame, using current frame", flush=True)
                        best_frame = frame
                    
                    timestamp = datetime.now()
                    image_path = self.save_image(best_frame, timestamp)
                    
                    metadata = {
                        'timestamp': timestamp.isoformat(),  # Convert to string for JSON serialization
                        'motion_score': 1.0,  # Simplified for now
                        'source': self.config.get('camera_url') or f"device_{self.config.get('camera_device', 0)}"
                    }
                    
                    self.publish_to_redis(image_path, metadata)
                    last_capture_time = current_time
                    motion_detected_time = None  # Reset motion tracking after capture
                    
                    # Don't update background immediately after capture - wait for scene to stabilize
                
                # Small delay to prevent CPU spinning - matches configured FPS
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("\nStopping capture service...", flush=True)
        except Exception as e:
            print(f"\nError in capture loop: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            if self.cap:
                self.cap.release()
            print("Capture service stopped", flush=True)

def load_config():
    """Load configuration from environment variables."""
    config = {
        'redis_host': os.getenv('REDIS_HOST', 'redis'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'redis_queue': os.getenv('REDIS_QUEUE', 'images'),
        'camera_url': os.getenv('CAMERA_URL'),  # RTSP URL
        'camera_device': int(os.getenv('CAMERA_DEVICE_ID', 0)),  # Direct device
        'images_path': os.getenv('IMAGES_PATH', 'data/images'),
        'resolution': [int(x) for x in os.getenv('CAMERA_RESOLUTION', '1920,1080').split(',')],
        'fps': float(os.getenv('CAMERA_FPS', 15)),
        'motion_threshold': int(os.getenv('MOTION_THRESHOLD', 50)),
        'motion_min_area': int(os.getenv('MOTION_MIN_AREA', 3000)),  # Lower = more sensitive (default: 3000 for moderate sensitivity)
        'motion_cooldown': float(os.getenv('MOTION_COOLDOWN', 5.0)),  # Lower = more frequent captures (default: 5.0s)
        'motion_delay': float(os.getenv('MOTION_DELAY', 1.5)),  # Delay after motion detected before capturing (default: 1.5s for sharper images)
        'capture_samples': int(os.getenv('CAPTURE_SAMPLES', 5)),  # Number of frames to sample when capturing (default: 5)
        'capture_sample_interval': float(os.getenv('CAPTURE_SAMPLE_INTERVAL', 0.1)),  # Seconds between samples (default: 0.1s)
        'jpeg_quality': int(os.getenv('JPEG_QUALITY', 95)),  # JPEG quality for saved images (1-100, default: 95 for high quality)
        'motion_mog2_var_threshold': float(os.getenv('MOTION_MOG2_VAR_THRESHOLD', 35)),  # MOG2 sensitivity (lower = more sensitive, default: 35)
        'motion_binary_threshold': int(os.getenv('MOTION_BINARY_THRESHOLD', 175)),  # Binary threshold (lower = more sensitive, default: 175)
        'http_port': int(os.getenv('CAPTURE_HTTP_PORT', 8080)),  # HTTP server port for live capture
        'http_host': os.getenv('CAPTURE_HTTP_HOST', '0.0.0.0'),  # HTTP server host
    }
    return config

if __name__ == "__main__":
    print("Starting capture service...", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    
    config = load_config()
    print(f"Configuration loaded:", flush=True)
    print(f"  Redis: {config.get('redis_host')}:{config.get('redis_port')}", flush=True)
    print(f"  Camera URL: {config.get('camera_url')}", flush=True)
    print(f"  Images path: {config.get('images_path')}", flush=True)
    
    try:
        service = CaptureService(config)
        service.run()
    except Exception as e:
        print(f"Fatal error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

