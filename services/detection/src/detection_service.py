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
from datetime import datetime, timezone
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
        # Class IDs - can be set via config or auto-detected from model
        # Defaults to COCO dataset IDs if not specified
        bird_class_id = self.config.get('bird_class_id')
        human_class_id = self.config.get('human_class_id')
        self.bird_class_id = int(bird_class_id) if bird_class_id is not None else 14  # COCO: 14, custom: 1
        self.human_class_id = int(human_class_id) if human_class_id is not None else 0  # COCO: 0, custom: 0
        # Optional class ID for squirrel (not in COCO by default). Set via env/config.
        # Use -1 to disable if not provided.
        self.squirrel_class_id = int(self.config.get('squirrel_class_id', -1))
        # Per-class confidence thresholds
        default_threshold = self.config.get('confidence_threshold', 0.5)
        self.human_threshold = self.config.get('human_confidence_threshold', default_threshold)
        self.bird_threshold = self.config.get('bird_confidence_threshold', default_threshold)
        self.squirrel_threshold = self.config.get('squirrel_confidence_threshold', default_threshold)
        # Debugging
        self.debug = bool(self.config.get('debug', False))
        self.debug_save = bool(self.config.get('debug_save', False))
        self.debug_dir = Path(self.config.get('debug_dir', 'debug'))
        
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
        """Load YOLOv8 model and auto-detect class IDs if not explicitly set."""
        model_path = self.config.get('model_path', 'yolov8n.pt')
        print(f"Loading YOLOv8 model: {model_path}", flush=True)
        try:
            # If model_path is a file path, use it; otherwise download pre-trained
            if os.path.exists(model_path):
                self.model = YOLO(model_path)
            else:
                # Download pre-trained model (yolov8n.pt, yolov8s.pt, etc.)
                self.model = YOLO(model_path)
            
            # Auto-detect class IDs from model names if not explicitly configured
            # This allows the model to work with both COCO and custom trained models
            if hasattr(self.model, 'names') and self.model.names:
                model_names = self.model.names
                print(f"Model classes: {model_names}", flush=True)
                
                # Try to find class IDs by name (case-insensitive)
                for class_id, class_name in model_names.items():
                    class_name_lower = class_name.lower()
                    # Only auto-detect if class IDs weren't explicitly set via config
                    if self.config.get('bird_class_id') is None and 'bird' in class_name_lower:
                        self.bird_class_id = int(class_id)
                        print(f"Auto-detected bird class ID: {self.bird_class_id} (from '{class_name}')", flush=True)
                    if self.config.get('human_class_id') is None and class_name_lower in ['person', 'human']:
                        self.human_class_id = int(class_id)
                        print(f"Auto-detected human class ID: {self.human_class_id} (from '{class_name}')", flush=True)
                    if self.squirrel_class_id < 0 and 'squirrel' in class_name_lower:
                        self.squirrel_class_id = int(class_id)
                        print(f"Auto-detected squirrel class ID: {self.squirrel_class_id} (from '{class_name}')", flush=True)
            
            print(f"✓ Model loaded successfully", flush=True)
            print(f"Using class IDs - Bird: {self.bird_class_id}, Human: {self.human_class_id}, Squirrel: {self.squirrel_class_id}", flush=True)
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
            is_squirrel = False
            max_confidence = 0.0
            bounding_boxes = []
            bird_boxes = []
            human_boxes = []
            squirrel_boxes = []
            all_preds = []
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    cls = int(box.cls[0])
                    conf = float(box.conf[0])
                    all_preds.append({'cls': cls, 'conf': conf})
                    
                    # Determine the appropriate threshold based on class
                    threshold = None
                    if cls == self.bird_class_id:
                        threshold = self.bird_threshold
                    elif cls == self.human_class_id:
                        threshold = self.human_threshold
                    elif self.squirrel_class_id >= 0 and cls == self.squirrel_class_id:
                        threshold = self.squirrel_threshold
                    else:
                        # For other classes, skip (or use default threshold if needed)
                        continue
                    
                    # Check if confidence meets the class-specific threshold
                    if conf >= threshold:
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        box_data = {
                            'x1': x1,
                            'y1': y1,
                            'x2': x2,
                            'y2': y2,
                            'confidence': conf,
                            'class': (
                                'bird' if cls == self.bird_class_id else
                                'human' if cls == self.human_class_id else
                                'squirrel' if (self.squirrel_class_id >= 0 and cls == self.squirrel_class_id) else
                                'other'
                            )
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
                        elif self.squirrel_class_id >= 0 and cls == self.squirrel_class_id:
                            is_squirrel = True
                            max_confidence = max(max_confidence, conf)
                            squirrel_boxes.append(box_data)
                            bounding_boxes.append(box_data)
            
            # Determine category
            present = [is_bird, is_human, is_squirrel]
            if present.count(True) == 0:
                category = 'none'
            elif present.count(True) == 1:
                category = 'bird' if is_bird else ('human' if is_human else 'squirrel')
            else:
                # Multiple classes detected
                category = 'both'

            # Debug logging
            if self.debug:
                try:
                    # Log image size and top predictions (by confidence)
                    img = cv2.imread(str(full_path))
                    h, w = (img.shape[0], img.shape[1]) if img is not None else (-1, -1)
                    names = getattr(self.model, 'names', {})
                    top_preds = sorted(all_preds, key=lambda p: p['conf'], reverse=True)[:10]
                    pretty = [f"{names.get(p['cls'], p['cls'])}:{p['conf']:.2f}" for p in top_preds]
                    print(f"Debug: {image_path} size={w}x{h}, top={pretty}", flush=True)
                except Exception:
                    pass

            # Optional: save debug image with boxes
            if self.debug_save and (is_bird or is_human or is_squirrel):
                try:
                    img = cv2.imread(str(full_path))
                    if img is not None:
                        for b in bounding_boxes:
                            color = (0,255,0) if b['class']=='human' else (255,0,0) if b['class']=='bird' else (0,255,255)
                            p1 = (int(b['x1']), int(b['y1']))
                            p2 = (int(b['x2']), int(b['y2']))
                            cv2.rectangle(img, p1, p2, color, 2)
                            cv2.putText(img, f"{b['class']} {b['confidence']:.2f}", (p1[0], max(0,p1[1]-6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
                        debug_base = Path(self.config['images_path']) / self.debug_dir
                        out_path = debug_base / image_path
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(str(out_path), img)
                        print(f"Debug: saved {out_path}", flush=True)
                except Exception as e:
                    print(f"Debug save failed: {e}", flush=True)
            
            return {
                'is_bird': is_bird,
                'is_human': is_human,
                'is_squirrel': is_squirrel,
                'category': category,
                'confidence': max_confidence if (is_bird or is_human or is_squirrel) else 0.0,
                'bounding_boxes': bounding_boxes,
                'num_detections': len(bounding_boxes),
                'num_birds': len(bird_boxes),
                'num_humans': len(human_boxes),
                'num_squirrels': len(squirrel_boxes)
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
            'is_squirrel': detection_result.get('is_squirrel', False),
            'category': detection_result['category'],
            'confidence': detection_result['confidence'],
            'bounding_boxes': detection_result['bounding_boxes'],
            'num_detections': detection_result['num_detections'],
            'num_birds': detection_result.get('num_birds', 0),
            'num_humans': detection_result.get('num_humans', 0),
            'num_squirrels': detection_result.get('num_squirrels', 0),
            'motion_score': image_data.get('motion_score', 0),
            'source': image_data.get('source', 'unknown'),
            'detected_at': datetime.now(timezone.utc).isoformat()
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
            if detection_result.get('is_squirrel'):
                status_parts.append(f"Squirrel({detection_result.get('num_squirrels', 0)})")
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
        print(f"Class IDs - Human: {self.human_class_id}, Bird: {self.bird_class_id}, Squirrel: {self.squirrel_class_id}", flush=True)
        print(f"Confidence thresholds - Human: {self.human_threshold}, Bird: {self.bird_threshold}, Squirrel: {self.squirrel_threshold}", flush=True)
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
    # Default threshold (used as fallback if per-class thresholds not set)
    default_threshold = float(os.getenv('CONFIDENCE_THRESHOLD', '0.5'))
    
    # Class IDs - None means auto-detect from model, otherwise use specified value
    bird_class_id = os.getenv('BIRD_CLASS_ID')
    human_class_id = os.getenv('HUMAN_CLASS_ID')
    squirrel_class_id = os.getenv('SQUIRREL_CLASS_ID', '-1')
    
    config = {
        'redis_host': os.getenv('REDIS_HOST', 'redis'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'images_queue': os.getenv('REDIS_IMAGES_QUEUE', 'images'),
        'detections_queue': os.getenv('REDIS_DETECTIONS_QUEUE', 'detections'),
        'images_path': os.getenv('IMAGES_PATH', 'data/images'),
        'model_path': os.getenv('MODEL_PATH', 'yolov8n.pt'),
        'confidence_threshold': default_threshold,
        # Per-class confidence thresholds (fallback to default_threshold if not set)
        'human_confidence_threshold': float(os.getenv('HUMAN_CONFIDENCE_THRESHOLD', str(default_threshold))),
        'bird_confidence_threshold': float(os.getenv('BIRD_CONFIDENCE_THRESHOLD', str(default_threshold))),
        'squirrel_confidence_threshold': float(os.getenv('SQUIRREL_CONFIDENCE_THRESHOLD', str(default_threshold))),
        # Class IDs - None means auto-detect, otherwise use specified value
        'bird_class_id': int(bird_class_id) if bird_class_id is not None else None,
        'human_class_id': int(human_class_id) if human_class_id is not None else None,
        # Optional: class ID for squirrel in the active model; -1 disables detection
        'squirrel_class_id': int(squirrel_class_id),
        # Debugging controls
        'debug': os.getenv('DETECTION_DEBUG', 'false').lower() == 'true',
        'debug_save': os.getenv('DETECTION_DEBUG_SAVE', 'false').lower() == 'true',
        'debug_dir': os.getenv('DETECTION_DEBUG_DIR', 'debug'),
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

