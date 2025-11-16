#!/usr/bin/env python3
"""
Unified capture service for bird monitoring system.
Runs on host (not in Docker) to directly access USB webcam.
Captures frames, detects motion, saves high-res images, and publishes to Redis.
Also serves HTTP endpoints for live view.
"""
import cv2
import numpy as np
import os
import sys
import time
import json
import redis
import warnings
import threading
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, Response
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Suppress OpenCV warnings
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
warnings.filterwarnings('ignore', category=UserWarning)

# Force unbuffered output
if sys.stdout.isatty():
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', 1)

class HostCaptureService:
    def __init__(self, config):
        self.config = config
        self.redis_client = None
        self.cap = None
        self.running = False
        self.cap_lock = threading.Lock()
        self.last_good_frame = None
        self.last_frame_lock = threading.Lock()
        self.current_brightness = 0.0
        self.is_low_light = False
        self.brightness_lock = threading.Lock()
        self.last_motion_area = 0
        self.last_motion_min_area = 10000
        self.frame_errors = 0
        self.corrupted_frames = 0
        self.total_frames = 0
        self.consecutive_errors = 0
        self.max_consecutive_errors = 50
        self.reconnect_delay = 5.0
        
        # MOG2 background subtractor for motion detection
        mog2_var_threshold = self.config.get('motion_mog2_var_threshold', 25)
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500,
            varThreshold=mog2_var_threshold,
            detectShadows=True
        )
        
        # Video clip capture: frame buffer for storing recent frames
        self.video_clip_enabled = self.config.get('video_clip_enabled', True)
        self.video_clip_duration = self.config.get('video_clip_duration', 3.0)  # seconds
        self.video_clip_fps = self.config.get('video_clip_fps', 15.0)
        self.frame_buffer = []  # List of (timestamp, frame) tuples
        self.frame_buffer_lock = threading.Lock()
        self.max_buffer_frames = int(self.video_clip_duration * self.video_clip_fps) + 10  # Extra buffer
        
    def connect_redis(self):
        """Connect to Redis server (running in Docker)."""
        print("Attempting to connect to Redis...", flush=True)
        try:
            redis_host = self.config.get('redis_host', 'localhost')
            redis_port = self.config.get('redis_port', 6379)
            print(f"Connecting to Redis at {redis_host}:{redis_port}...", flush=True)
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=0,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            self.redis_client.ping()
            print(f"✓ Connected to Redis at {redis_host}:{redis_port}", flush=True)
            return True
        except Exception as e:
            print(f"✗ Failed to connect to Redis: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return False
    
    def close_camera(self):
        """Safely close the camera connection."""
        with self.cap_lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception as e:
                    print(f"Error closing camera: {e}", flush=True)
                finally:
                    self.cap = None
                    time.sleep(0.5)
    
    def open_camera(self):
        """Open USB webcam directly."""
        self.close_camera()
        
        camera_device = self.config.get('camera_device', 0)
        print(f"Opening USB camera device: {camera_device}", flush=True)
        
        with self.cap_lock:
            self.cap = cv2.VideoCapture(int(camera_device))
            
            # Set camera properties
            if 'resolution' in self.config:
                width, height = self.config['resolution']
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            
            if 'fps' in self.config:
                self.cap.set(cv2.CAP_PROP_FPS, self.config['fps'])
            
            # Set buffer size to minimize latency
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except:
                pass
        
        time.sleep(1)
        
        with self.cap_lock:
            if not self.cap or not self.cap.isOpened():
                print(f"ERROR: Could not open camera device: {camera_device}", flush=True)
                return False
            
            try:
                width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = self.cap.get(cv2.CAP_PROP_FPS)
                print(f"✓ Camera opened: {width}x{height} @ {fps} FPS", flush=True)
            except Exception as e:
                print(f"Warning: Could not get camera properties: {e}", flush=True)
                print("✓ Camera opened (properties unavailable)", flush=True)
        
        self.consecutive_errors = 0
        return True
    
    def is_valid_frame(self, frame):
        """Validate that a frame is usable."""
        if frame is None:
            return False
        
        if len(frame.shape) < 2:
            return False
        
        height, width = frame.shape[:2]
        if width < 10 or height < 10:
            return False
        
        # Check if frame is completely uniform
        if len(frame.shape) == 3:
            std_dev = frame.std()
            if std_dev < 0.001:
                return False
        else:
            std_dev = frame.std()
            if std_dev < 0.001:
                return False
        
        return True
    
    def detect_motion(self, frame, background):
        """Motion detection using MOG2 background subtractor."""
        blurred = cv2.GaussianBlur(frame, (21, 21), 0)
        fg_mask = self.bg_subtractor.apply(blurred)
        
        binary_threshold = self.config.get('motion_binary_threshold', 150)
        _, fg_mask = cv2.threshold(fg_mask, binary_threshold, 255, cv2.THRESH_BINARY)
        
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        
        motion_area = cv2.countNonZero(fg_mask)
        min_area = self.config.get('motion_min_area', 10000)
        
        motion_detected = motion_area > min_area
        
        self.last_motion_area = motion_area
        self.last_motion_min_area = min_area
        
        return motion_detected, frame
    
    def generate_thumbnail(self, image_path, frame):
        """Generate a thumbnail for an image."""
        if not PIL_AVAILABLE:
            return None
        
        if not self.config.get('thumbnail_enabled', True):
            return None
        
        if not self.config.get('thumbnail_generate_on_capture', True):
            return None
        
        try:
            images_path = Path(self.config.get('images_path', 'data/images'))
            full_path = images_path / image_path
            
            width = self.config.get('thumbnail_width', 300)
            height = self.config.get('thumbnail_height', 300)
            quality = self.config.get('thumbnail_quality', 85)
            
            thumbnail_dir = full_path.parent / 'thumbnails'
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail_path = thumbnail_dir / full_path.name
            
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            pil_image.thumbnail((width, height), Image.Resampling.LANCZOS)
            pil_image.save(thumbnail_path, 'JPEG', quality=quality, optimize=True)
            return str(thumbnail_path.relative_to(images_path))
        except Exception as e:
            print(f"Error generating thumbnail: {e}", flush=True)
            return None
    
    def save_image(self, frame, timestamp):
        """Save image to disk with high quality JPEG encoding."""
        images_path = Path(self.config.get('images_path', 'data/images'))
        date_path = images_path / timestamp.strftime('%Y-%m') / timestamp.strftime('%d')
        date_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"{timestamp.strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
        filepath = date_path / filename
        
        jpeg_quality = self.config.get('jpeg_quality', 95)
        cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        
        image_path = str(filepath.relative_to(images_path))
        self.generate_thumbnail(image_path, frame)
        
        return image_path
    
    def save_video_clip(self, timestamp):
        """Save a video clip from the frame buffer. Returns video_path or None."""
        if not self.video_clip_enabled:
            return None
        
        images_path = Path(self.config.get('images_path', 'data/images'))
        date_path = images_path / timestamp.strftime('%Y-%m') / timestamp.strftime('%d')
        date_path.mkdir(parents=True, exist_ok=True)
        
        filename_base = timestamp.strftime('%Y%m%d_%H%M%S_%f')[:-3]
        video_filename = f"{filename_base}.mp4"
        video_filepath = date_path / video_filename
        
        # Get frames from buffer
        with self.frame_buffer_lock:
            if not self.frame_buffer:
                print("Warning: Frame buffer is empty, cannot save video clip", flush=True)
                return None
            
            # Get frames from the last video_clip_duration seconds
            current_time = time.time()
            cutoff_time = current_time - self.video_clip_duration
            
            # Filter frames within the time window
            frames_to_save = [(t, f) for t, f in self.frame_buffer if t >= cutoff_time]
            
            if not frames_to_save:
                print("Warning: No frames in buffer within clip duration, using all available frames", flush=True)
                frames_to_save = self.frame_buffer[-int(self.video_clip_fps * self.video_clip_duration):]
            
            if not frames_to_save:
                print("Warning: No frames available for video clip", flush=True)
                return None
        
        try:
            # Get frame dimensions from first frame
            first_frame = frames_to_save[0][1]
            height, width = first_frame.shape[:2]
            
            # Use H.264 codec (MP4V is more compatible but H.264 is better)
            # Try H.264 first, fallback to MP4V
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(
                str(video_filepath),
                fourcc,
                self.video_clip_fps,
                (width, height)
            )
            
            if not video_writer.isOpened():
                print(f"Warning: Could not open video writer for {video_filepath}, trying H.264...", flush=True)
                # Try H.264 codec (may require additional codec support)
                fourcc = cv2.VideoWriter_fourcc(*'avc1')
                video_writer = cv2.VideoWriter(
                    str(video_filepath),
                    fourcc,
                    self.video_clip_fps,
                    (width, height)
                )
                if not video_writer.isOpened():
                    print(f"Error: Could not open video writer with any codec", flush=True)
                    return None
            
            # Write frames to video
            for _, frame in frames_to_save:
                video_writer.write(frame)
            
            video_writer.release()
            
            video_path = str(video_filepath.relative_to(images_path))
            print(f"Saved video clip: {video_path} ({len(frames_to_save)} frames)", flush=True)
            return video_path
            
        except Exception as e:
            print(f"Error saving video clip: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None
    
    def measure_sharpness(self, frame):
        """Measure frame sharpness using Laplacian variance."""
        if frame is None:
            return 0.0
        
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = laplacian.var()
        return sharpness
    
    def measure_brightness(self, frame):
        """Measure average brightness of frame."""
        if frame is None:
            return 0.0
        
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        
        brightness = gray.mean() / 255.0
        return brightness
    
    def capture_best_frame(self, num_samples=5, sample_interval=0.1):
        """Capture multiple frames and return the sharpest one."""
        with self.cap_lock:
            if not self.cap or not self.cap.isOpened():
                return None
            
            best_frame = None
            best_sharpness = 0.0
            
            try:
                # Flush buffer to get fresh frames
                buffer_flush_count = self.config.get('capture_buffer_flush', 10)
                for _ in range(buffer_flush_count):
                    self.cap.read()
                
                for i in range(num_samples):
                    ret, frame = self.cap.read()
                    if ret and frame is not None and self.is_valid_frame(frame):
                        sharpness = self.measure_sharpness(frame)
                        if sharpness > best_sharpness:
                            best_sharpness = sharpness
                            best_frame = frame.copy()
                    
                    if i < num_samples - 1:
                        time.sleep(sample_interval)
            except Exception as e:
                print(f"Error in capture_best_frame: {e}", flush=True)
                return None
        
        return best_frame
    
    def publish_to_redis(self, image_path, metadata):
        """Publish image info to Redis queue."""
        message = {
            'image_path': image_path,
            'timestamp': metadata.get('timestamp', datetime.now(timezone.utc).isoformat()),
            'motion_score': metadata.get('motion_score', 0),
            'source': metadata.get('source', 'usb_webcam')
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
            try:
                frame = None
                try:
                    with self.last_frame_lock:
                        if self.last_good_frame is not None:
                            frame = self.last_good_frame.copy()
                except Exception as e:
                    print(f"Error accessing last_good_frame: {e}", flush=True)
                    frame = None
                
                if frame is None:
                    return Response(
                        "No frame available - camera not connected or no frames captured yet",
                        status=503,
                        mimetype='text/plain'
                    )
                
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
            except Exception as e:
                return Response(
                    f"Error encoding frame: {str(e)}",
                    status=500,
                    mimetype='text/plain'
                )
        
        @app.route('/capture/health', methods=['GET'])
        def health():
            """Health check endpoint."""
            with self.cap_lock:
                if self.cap and self.cap.isOpened():
                    with self.brightness_lock:
                        return Response(
                            json.dumps({
                                'status': 'healthy',
                                'camera': 'connected',
                                'low_light': bool(self.is_low_light),
                                'brightness': round(self.current_brightness, 3)
                            }),
                            mimetype='application/json',
                            status=200
                        )
                else:
                    return Response(
                        json.dumps({'status': 'unhealthy', 'camera': 'disconnected'}),
                        mimetype='application/json',
                        status=503
                    )
        
        @app.route('/capture/status', methods=['GET'])
        def status():
            """Get capture service status."""
            with self.brightness_lock:
                with self.cap_lock:
                    camera_connected = self.cap is not None and self.cap.isOpened()
                
                return {
                    'camera_connected': bool(camera_connected),
                    'low_light': bool(self.is_low_light),
                    'brightness': round(self.current_brightness, 3),
                    'frame_errors': int(self.frame_errors),
                    'corrupted_frames': int(self.corrupted_frames),
                    'total_frames': int(self.total_frames),
                    'motion_area': int(self.last_motion_area),
                    'motion_min_area': int(self.last_motion_min_area),
                    'motion_detected': bool(self.last_motion_area > self.last_motion_min_area)
                }, 200
        
        port = self.config.get('http_port', 8080)
        host = self.config.get('http_host', '0.0.0.0')
        
        print(f"Starting HTTP server on {host}:{port} for live capture", flush=True)
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True, processes=1)
    
    def run(self):
        """Main capture loop."""
        if not self.connect_redis():
            print("Failed to connect to Redis, exiting", flush=True)
            return False
        
        # Start HTTP server in a separate thread
        http_thread = threading.Thread(target=self.start_http_server, daemon=True)
        http_thread.start()
        print("HTTP server thread started", flush=True)
        
        time.sleep(2)
        
        camera_opened = self.open_camera()
        if not camera_opened:
            print("Warning: Failed to open camera initially, but continuing (will retry in background)", flush=True)
        
        self.running = True
        background = None
        last_capture_time = time.time()
        last_status_time = time.time()
        cooldown = self.config.get('motion_cooldown', 10.0)
        motion_delay = self.config.get('motion_delay', 1.5)
        capture_samples = self.config.get('capture_samples', 5)
        capture_sample_interval = self.config.get('capture_sample_interval', 0.1)
        frame_count = 0
        motion_detections = 0
        fps = self.config.get('fps', 15)
        warmup_frames = int(fps * 5)
        sleep_time = 1.0 / fps
        motion_detected_time = None
        
        print("\nStarting capture loop...", flush=True)
        print(f"MOG2 background model warming up ({warmup_frames} frames)...", flush=True)
        print(f"Target FPS: {fps} (sleep: {sleep_time:.3f}s per frame)", flush=True)
        print("Press Ctrl+C to stop\n", flush=True)
        
        try:
            while self.running:
                try:
                    with self.cap_lock:
                        if not self.cap or not self.cap.isOpened():
                            print("Camera not opened, attempting to reconnect...", flush=True)
                            if not self.open_camera():
                                print(f"Failed to reconnect, waiting {self.reconnect_delay}s...", flush=True)
                                time.sleep(self.reconnect_delay)
                                continue
                        
                        ret, frame = self.cap.read()
                except Exception as e:
                    print(f"Exception reading frame: {e}", flush=True)
                    self.frame_errors += 1
                    self.consecutive_errors += 1
                    ret = False
                    frame = None
                
                frame_count += 1
                self.total_frames += 1
                
                if not ret or frame is None:
                    self.frame_errors += 1
                    self.consecutive_errors += 1
                    
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        print(f"Too many consecutive errors ({self.consecutive_errors}), reconnecting camera...", flush=True)
                        self.close_camera()
                        time.sleep(self.reconnect_delay)
                        if not self.open_camera():
                            print(f"Reconnection failed, waiting {self.reconnect_delay}s before retry...", flush=True)
                            time.sleep(self.reconnect_delay)
                        continue
                    
                    if self.frame_errors % 100 == 0:
                        print(f"Warning: Failed to read frame (total errors: {self.frame_errors}, consecutive: {self.consecutive_errors})", flush=True)
                    time.sleep(0.1)
                    continue
                
                if not self.is_valid_frame(frame):
                    self.corrupted_frames += 1
                    self.consecutive_errors += 1
                    
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        print(f"Too many consecutive corrupted frames ({self.consecutive_errors}), reconnecting camera...", flush=True)
                        self.close_camera()
                        time.sleep(self.reconnect_delay)
                        if not self.open_camera():
                            print(f"Reconnection failed, waiting {self.reconnect_delay}s before retry...", flush=True)
                            time.sleep(self.reconnect_delay)
                        continue
                    
                    if self.corrupted_frames % 100 == 0:
                        print(f"Warning: Skipped corrupted frame (total corrupted: {self.corrupted_frames}, consecutive: {self.consecutive_errors})", flush=True)
                    continue
                
                self.consecutive_errors = 0
                
                brightness = self.measure_brightness(frame)
                with self.brightness_lock:
                    self.current_brightness = brightness
                    self.is_low_light = brightness < 0.2
                
                with self.last_frame_lock:
                    self.last_good_frame = frame.copy()
                
                # Add frame to buffer for video clips
                if self.video_clip_enabled:
                    with self.frame_buffer_lock:
                        self.frame_buffer.append((time.time(), frame.copy()))
                        # Keep only recent frames (max_buffer_frames)
                        if len(self.frame_buffer) > self.max_buffer_frames:
                            self.frame_buffer.pop(0)
                
                current_time = time.time()
                if current_time - last_status_time >= 10:
                    time_since_capture = int(current_time - last_capture_time) if last_capture_time > 0 else 0
                    error_rate = (self.frame_errors + self.corrupted_frames) / max(self.total_frames, 1) * 100
                    warmup_status = f" (warmup: {warmup_frames - frame_count} frames left)" if frame_count < warmup_frames else ""
                    print(f"Status: Processing frames... ({frame_count} frames, {motion_detections} motion events, {time_since_capture}s since last capture, {error_rate:.1f}% error rate){warmup_status}", flush=True)
                    if frame_count >= warmup_frames:
                        is_detected = self.last_motion_area > self.last_motion_min_area
                        print(f"  Motion detection: area={self.last_motion_area}, threshold={self.last_motion_min_area}, detected={is_detected}", flush=True)
                    last_status_time = current_time
                
                if background is None:
                    background = frame.copy()
                
                if frame_count < warmup_frames:
                    blurred = cv2.GaussianBlur(frame, (21, 21), 0)
                    self.bg_subtractor.apply(blurred)
                    if frame_count == 0:
                        with self.last_frame_lock:
                            self.last_good_frame = frame.copy()
                    if frame_count == warmup_frames - 1:
                        print(f"✓ Background model warmed up after {warmup_frames} frames", flush=True)
                    motion_detected = False
                else:
                    motion_detected, _ = self.detect_motion(frame, background)
                    
                    if self.config.get('motion_debug', False) and frame_count % 30 == 0:
                        print(f"Motion debug: area={self.last_motion_area}, min_area={self.last_motion_min_area}, detected={motion_detected}", flush=True)
                
                if motion_detected:
                    if motion_detected_time is None:
                        motion_detected_time = current_time
                else:
                    motion_detected_time = None
                
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
                    
                    time.sleep(0.3)
                    
                    timestamp = datetime.now(timezone.utc)
                    best_frame = self.capture_best_frame(
                        num_samples=capture_samples,
                        sample_interval=capture_sample_interval
                    )
                    if best_frame is None:
                        print(f"Warning: Failed to capture best frame, using current frame", flush=True)
                        best_frame = frame
                    
                    image_path = self.save_image(best_frame, timestamp)
                    
                    # Save video clip if enabled
                    video_path = None
                    if self.video_clip_enabled:
                        video_path = self.save_video_clip(timestamp)
                    
                    metadata = {
                        'timestamp': timestamp.isoformat(),
                        'motion_score': 1.0,
                        'source': f"usb_device_{self.config.get('camera_device', 0)}"
                    }
                    
                    # Include video_path in metadata for Redis message
                    if video_path:
                        metadata['video_path'] = video_path
                    
                    self.publish_to_redis(image_path, metadata)
                    last_capture_time = current_time
                    motion_detected_time = None
                
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("\nStopping capture service...", flush=True)
        except Exception as e:
            print(f"\nError in capture loop: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            self.close_camera()
            print("Capture service stopped", flush=True)

def load_config():
    """Load configuration from environment variables."""
    config = {
        'redis_host': os.getenv('REDIS_HOST', 'localhost'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'redis_queue': os.getenv('REDIS_QUEUE', 'images'),
        'camera_device': int(os.getenv('CAMERA_DEVICE_ID', 0)),
        'images_path': os.getenv('IMAGES_PATH', 'data/images'),
        'resolution': [int(x) for x in os.getenv('CAMERA_RESOLUTION', '1920,1080').split(',')],
        'fps': float(os.getenv('CAMERA_FPS', 15)),
        'motion_threshold': int(os.getenv('MOTION_THRESHOLD', 50)),
        'motion_min_area': int(os.getenv('MOTION_MIN_AREA', 3000)),
        'motion_cooldown': float(os.getenv('MOTION_COOLDOWN', 5.0)),
        'motion_delay': float(os.getenv('MOTION_DELAY', 1.5)),
        'capture_samples': int(os.getenv('CAPTURE_SAMPLES', 5)),
        'capture_sample_interval': float(os.getenv('CAPTURE_SAMPLE_INTERVAL', 0.1)),
        'capture_buffer_flush': int(os.getenv('CAPTURE_BUFFER_FLUSH', 10)),
        'jpeg_quality': int(os.getenv('JPEG_QUALITY', 95)),
        'motion_mog2_var_threshold': float(os.getenv('MOTION_MOG2_VAR_THRESHOLD', 35)),
        'motion_binary_threshold': int(os.getenv('MOTION_BINARY_THRESHOLD', 175)),
        'motion_debug': os.getenv('MOTION_DEBUG', 'false').lower() == 'true',
        'http_port': int(os.getenv('CAPTURE_HTTP_PORT', 8080)),
        'http_host': os.getenv('CAPTURE_HTTP_HOST', '0.0.0.0'),
        'thumbnail_enabled': os.getenv('THUMBNAIL_ENABLED', 'true').lower() == 'true',
        'thumbnail_width': int(os.getenv('THUMBNAIL_WIDTH', '300')),
        'thumbnail_height': int(os.getenv('THUMBNAIL_HEIGHT', '300')),
        'thumbnail_quality': int(os.getenv('THUMBNAIL_QUALITY', '85')),
        'thumbnail_generate_on_capture': os.getenv('THUMBNAIL_GENERATE_ON_CAPTURE', 'true').lower() == 'true',
        'video_clip_enabled': os.getenv('VIDEO_CLIP_ENABLED', 'true').lower() == 'true',
        'video_clip_duration': float(os.getenv('VIDEO_CLIP_DURATION', '3.0')),
        'video_clip_fps': float(os.getenv('VIDEO_CLIP_FPS', '15.0')),
    }
    return config

if __name__ == "__main__":
    print("Starting host capture service...", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    
    config = load_config()
    print(f"Configuration loaded:", flush=True)
    print(f"  Redis: {config.get('redis_host')}:{config.get('redis_port')}", flush=True)
    print(f"  Camera device: {config.get('camera_device')}", flush=True)
    print(f"  Images path: {config.get('images_path')}", flush=True)
    
    try:
        service = HostCaptureService(config)
        service.run()
    except Exception as e:
        print(f"Fatal error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

