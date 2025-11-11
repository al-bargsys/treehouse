#!/usr/bin/env python3
"""
Detection service for bird and human monitoring system.
Consumes images from Redis queue, runs YOLOv8 inference, and publishes detections.
"""
import os
import sys
import time
import json
import signal
import redis
import warnings
from pathlib import Path
from datetime import datetime
from ultralytics import YOLO
import cv2

# Suppress warnings
warnings.filterwarnings('ignore', category=UserWarning)
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'

# Force unbuffered output for Docker logs
if sys.stdout.isatty():
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', 1)

class DetectionService:
    def __init__(self, config):
        self.config = config
        self.redis_client = None
        self.model = None
        self.running = False
        self.bird_class_id = 14  # COCO dataset class ID for bird
        self.human_class_id = 0  # COCO dataset class ID for person
        
    def connect_redis(self):
        """Connect to Redis server."""
        print("Attempting to connect to Redis...", flush=True)
        try:
            self.redis_client = redis.Redis(
                host=self.config['redis_host'],
                port=self.config['redis_port'],
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            print(f"✓ Connected to Redis at {self.config['redis_host']}:{self.config['redis_port']}", flush=True)
            return True
        except Exception as e:
            print(f"Failed to connect to Redis: {e}", flush=True)
            return False
    
    def load_model(self):
        """Load YOLOv8 model."""
        model_path = self.config.get('model_path', 'yolov8n.pt')
        print(f"Loading YOLOv8 model: {model_path}", flush=True)
        try:
            # If model_path is a file path, use it; otherwise download pre-trained
            if os.path.exists(model_path):
                self.model = YOLO(model_path)
            else:
                # Download pre-trained model (yolov8n.pt, yolov8s.pt, etc.)
                self.model = YOLO(model_path)
            print(f"✓ Model loaded successfully", flush=True)
            return True
        except Exception as e:
            print(f"Failed to load model: {e}", flush=True)
            return False
    
    def detect_objects(self, image_path):
        """Run inference on image and detect birds and humans."""
        # image_path is relative (e.g., "2025-11/11/image.jpg")
        # images_path is the base directory (e.g., "/app/data/images")
        full_path = Path(self.config['images_path']) / image_path
        
        if not full_path.exists():
            print(f"Warning: Image not found: {full_path} (looking for: {image_path})", flush=True)
            return None
        
        try:
            # Run inference
            results = self.model(str(full_path), verbose=False)
            
            # Process results
            is_bird = False
            is_human = False
            max_confidence = 0.0
            bounding_boxes = []
            bird_boxes = []
            human_boxes = []
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    cls = int(box.cls[0])
                    conf = float(box.conf[0])
                    
                    # Check if this is a bird (class 14 in COCO) or human (class 0 in COCO)
                    if conf >= self.config['confidence_threshold']:
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        box_data = {
                            'x1': x1,
                            'y1': y1,
                            'x2': x2,
                            'y2': y2,
                            'confidence': conf,
                            'class': 'bird' if cls == self.bird_class_id else 'human' if cls == self.human_class_id else 'other'
                        }
                        
                        if cls == self.bird_class_id:
                            is_bird = True
                            max_confidence = max(max_confidence, conf)
                            bird_boxes.append(box_data)
                            bounding_boxes.append(box_data)
                        elif cls == self.human_class_id:
                            is_human = True
                            max_confidence = max(max_confidence, conf)
                            human_boxes.append(box_data)
                            bounding_boxes.append(box_data)
            
            # Determine category
            if is_bird and is_human:
                category = 'both'
            elif is_bird:
                category = 'bird'
            elif is_human:
                category = 'human'
            else:
                category = 'none'
            
            return {
                'is_bird': is_bird,
                'is_human': is_human,
                'category': category,
                'confidence': max_confidence if (is_bird or is_human) else 0.0,
                'bounding_boxes': bounding_boxes,
                'num_detections': len(bounding_boxes),
                'num_birds': len(bird_boxes),
                'num_humans': len(human_boxes)
            }
        except Exception as e:
            print(f"Error during inference: {e}", flush=True)
            return None
    
    def publish_detection(self, image_data, detection_result):
        """Publish detection result to Redis queue."""
        if detection_result is None:
            return
        
        message = {
            'image_path': image_data['image_path'],
            'timestamp': image_data['timestamp'],
            'is_bird': detection_result['is_bird'],
            'is_human': detection_result['is_human'],
            'category': detection_result['category'],
            'confidence': detection_result['confidence'],
            'bounding_boxes': detection_result['bounding_boxes'],
            'num_detections': detection_result['num_detections'],
            'num_birds': detection_result.get('num_birds', 0),
            'num_humans': detection_result.get('num_humans', 0),
            'motion_score': image_data.get('motion_score', 0),
            'source': image_data.get('source', 'unknown'),
            'detected_at': datetime.now().isoformat()
        }
        
        queue_name = self.config.get('detections_queue', 'detections')
        try:
            self.redis_client.lpush(queue_name, json.dumps(message))
            # Build status message
            status_parts = []
            if detection_result['is_bird']:
                status_parts.append(f"Bird({detection_result['num_birds']})")
            if detection_result['is_human']:
                status_parts.append(f"Human({detection_result['num_humans']})")
            status = "✓ " + ", ".join(status_parts) if status_parts else "No detection"
            print(f"{status}: {image_data['image_path']} (confidence: {detection_result['confidence']:.2f})", flush=True)
        except Exception as e:
            print(f"Error publishing to Redis: {e}", flush=True)
    
    def delete_image(self, image_path):
        """Delete image file from disk if no bird/human detected."""
        full_path = Path(self.config['images_path']) / image_path
        try:
            if full_path.exists():
                full_path.unlink()
                print(f"✗ Deleted image (no detection): {image_path}", flush=True)
                return True
            else:
                print(f"Warning: Image not found for deletion: {image_path}", flush=True)
                return False
        except Exception as e:
            print(f"Error deleting image {image_path}: {e}", flush=True)
            return False
    
    def process_image(self, image_data):
        """Process a single image."""
        image_path = image_data.get('image_path')
        if not image_path:
            print("Warning: Missing image_path in message", flush=True)
            return
        
        # Run detection
        detection_result = self.detect_objects(image_path)
        
        if detection_result:
            # Publish result (only if something was detected)
            if detection_result['category'] != 'none':
                self.publish_detection(image_data, detection_result)
            else:
                # No bird or human detected - delete the image
                self.delete_image(image_path)
    
    def run(self):
        """Main service loop."""
        if not self.connect_redis():
            print("Failed to connect to Redis, exiting", flush=True)
            return False
        
        if not self.load_model():
            print("Failed to load model, exiting", flush=True)
            return False
        
        self.running = True
        images_queue = self.config.get('images_queue', 'images')
        timeout = 5  # seconds
        
        print(f"\nStarting detection service...", flush=True)
        print(f"Consuming from queue: {images_queue}", flush=True)
        print(f"Publishing to queue: {self.config.get('detections_queue', 'detections')}", flush=True)
        print(f"Confidence threshold: {self.config['confidence_threshold']}", flush=True)
        print("Press Ctrl+C to stop\n", flush=True)
        
        processed_count = 0
        
        try:
            while self.running:
                try:
                    # Blocking pop from Redis queue with timeout
                    result = self.redis_client.brpop(images_queue, timeout=timeout)
                    
                    if result is None:
                        # Timeout - continue loop to check if still running
                        continue
                    
                    _, message_json = result
                    image_data = json.loads(message_json)
                    
                    # Process image
                    self.process_image(image_data)
                    processed_count += 1
                    
                except redis.exceptions.ConnectionError as e:
                    print(f"Redis connection error: {e}, retrying...", flush=True)
                    time.sleep(5)
                    # Try to reconnect
                    if not self.connect_redis():
                        print("Failed to reconnect to Redis", flush=True)
                        break
                except redis.exceptions.TimeoutError:
                    # Timeout is expected when queue is empty, just continue
                    continue
                except json.JSONDecodeError as e:
                    print(f"Error decoding message: {e}", flush=True)
                except Exception as e:
                    print(f"Error processing message: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
        
        except KeyboardInterrupt:
            print("\nStopping detection service...", flush=True)
        finally:
            self.running = False
            print(f"Detection service stopped. Processed {processed_count} images.", flush=True)

def load_config():
    """Load configuration from environment variables."""
    config = {
        'redis_host': os.getenv('REDIS_HOST', 'redis'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'images_queue': os.getenv('REDIS_IMAGES_QUEUE', 'images'),
        'detections_queue': os.getenv('REDIS_DETECTIONS_QUEUE', 'detections'),
        'images_path': os.getenv('IMAGES_PATH', 'data/images'),
        'model_path': os.getenv('MODEL_PATH', 'yolov8n.pt'),
        'confidence_threshold': float(os.getenv('CONFIDENCE_THRESHOLD', '0.5')),
    }
    return config

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print("\nReceived shutdown signal", flush=True)
    sys.exit(0)

if __name__ == "__main__":
    print("Starting detection service...", flush=True)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    config = load_config()
    print("Configuration loaded:", flush=True)
    for key, value in config.items():
        print(f"  {key}: {value}", flush=True)
    
    service = DetectionService(config)
    service.run()

