#!/usr/bin/env python3
"""
Storage service for bird and human monitoring system.
Consumes detections from Redis queue and stores them in PostgreSQL.
"""
import os
import sys
import time
import json
import signal
import redis
import logging
import threading
import schedule
from pathlib import Path
from datetime import datetime, timezone
from database import Database
from image_manager import ImageManager
from shared.utils.weather import get_weather_for_zip
from shared.utils.openai_client import OpenAIBirdNamer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self, config):
        self.config = config
        self.redis_client = None
        self.db = None
        self.running = False
        # Initialize OpenAI client (optional - will be None if no API key)
        self.openai_namer = OpenAIBirdNamer()
        # Initialize ImageManager
        self.image_manager = ImageManager(config)
    
    def connect_redis(self):
        """Connect to Redis server."""
        logger.info("Attempting to connect to Redis...")
        try:
            self.redis_client = redis.Redis(
                host=self.config['redis_host'],
                port=self.config['redis_port'],
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            self.redis_client.ping()
            logger.info(f"✓ Connected to Redis at {self.config['redis_host']}:{self.config['redis_port']}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False
    
    def connect_database(self):
        """Connect to PostgreSQL database."""
        logger.info("Attempting to connect to PostgreSQL...")
        self.db = Database(self.config)
        if self.db.connect():
            # Initialize schema
            if self.db.init_schema():
                # Set database reference in ImageManager
                self.image_manager.set_database(self.db)
                return True
        return False
    
    def verify_image_exists(self, image_path):
        """Verify that the image file exists on the shared volume."""
        full_path = Path(self.config['images_path']) / image_path
        return full_path.exists()
    
    def process_detection(self, detection_data):
        """Process a single detection record."""
        image_path = detection_data.get('image_path')
        if not image_path:
            logger.warning("Missing image_path in detection data")
            return False
        
        # Skip if no actual detections (only motion, no classification)
        category = detection_data.get('category')
        is_bird = detection_data.get('is_bird', False)
        is_human = detection_data.get('is_human', False)
        is_squirrel = detection_data.get('is_squirrel', False)
        num_detections = detection_data.get('num_detections', 0)
        
        # Don't save if category is 'none' or if no actual detections
        if category == 'none' or (not is_bird and not is_human and not is_squirrel) or num_detections == 0:
            logger.debug(f"Skipping storage for {image_path}: no detections (category: {category}, num_detections: {num_detections})")
            # Delete the image file since we're not storing it
            try:
                full_path = Path(self.config['images_path']) / image_path
                if full_path.exists():
                    full_path.unlink()
                    logger.debug(f"Deleted image file: {image_path}")
            except Exception as e:
                logger.warning(f"Could not delete image file {image_path}: {e}")
            return False
        
        # Verify image exists
        if not self.verify_image_exists(image_path):
            logger.warning(f"Image not found: {image_path}, skipping storage")
            return False
        
        # Prepare data for database
        detected_at = None
        if detection_data.get('detected_at'):
            try:
                # Handle both 'Z' suffix and '+00:00' timezone formats
                detected_at_str = detection_data['detected_at']
                if detected_at_str.endswith('Z'):
                    detected_at_str = detected_at_str.replace('Z', '+00:00')
                detected_at = datetime.fromisoformat(detected_at_str)
                # Convert to naive UTC datetime for storage
                if detected_at.tzinfo is not None:
                    detected_at = detected_at.astimezone(timezone.utc).replace(tzinfo=None)
            except:
                detected_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Parse timestamp, handling both 'Z' suffix and '+00:00' timezone formats
        timestamp_str = detection_data['timestamp']
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str.replace('Z', '+00:00')
        timestamp = datetime.fromisoformat(timestamp_str)
        # Convert to naive UTC datetime for storage (TIMESTAMP column doesn't store timezone)
        # If timezone-aware, convert to UTC and make naive
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        
        # Fetch weather data for the detection timestamp
        weather_data = None
        zip_code = self.config.get('zip_code', '34232')
        try:
            weather_data = get_weather_for_zip(zip_code, timestamp)
            if weather_data:
                logger.debug(f"Fetched weather for detection: {weather_data}")
            else:
                logger.warning(f"Could not fetch weather for zip {zip_code} at {timestamp}")
        except Exception as e:
            logger.warning(f"Error fetching weather data: {e}")
        
        # Generate bird name and backstory if a bird is detected and OpenAI is enabled
        bird_name = None
        bird_backstory = None
        if is_bird and self.openai_namer.enabled:
            try:
                logger.info("Bird detected - generating name and backstory via OpenAI...")
                bird_name, bird_backstory = self.openai_namer.generate_name_and_backstory()
                if bird_name:
                    logger.info(f"Generated bird name: {bird_name}")
                if bird_backstory:
                    logger.info(f"Generated backstory for {bird_name}")
            except Exception as e:
                logger.warning(f"Error generating bird name/backstory: {e}")
                # Continue without name/backstory if generation fails
        
        # Generate bbox image if bounding boxes are present
        bbox_image_path = None
        bounding_boxes = detection_data.get('bounding_boxes', [])
        if bounding_boxes:
            try:
                bbox_image_path = self.image_manager.draw_bounding_boxes(
                    image_path,
                    bounding_boxes
                )
                if bbox_image_path:
                    logger.debug(f"Generated bbox image: {bbox_image_path}")
            except Exception as e:
                logger.warning(f"Failed to generate bbox image for {image_path}: {e}")
        
        db_record = {
            'timestamp': timestamp,
            'image_path': image_path,
            'is_bird': is_bird,
            'is_human': is_human,
            'is_squirrel': is_squirrel,
            'category': category,
            'confidence': detection_data.get('confidence'),
            'species': detection_data.get('species'),
            'bounding_boxes': bounding_boxes,  # Will be converted to JSON in database.py
            'motion_score': detection_data.get('motion_score'),
            'metadata': {
                'source': detection_data.get('source', 'unknown'),
                'num_detections': detection_data.get('num_detections', 0),
                'num_birds': detection_data.get('num_birds', 0),
                'num_humans': detection_data.get('num_humans', 0),
                'num_squirrels': detection_data.get('num_squirrels', 0)
            },
            'detected_at': detected_at,
            'weather': weather_data,
            'bird_name': bird_name,
            'bird_backstory': bird_backstory,
            'bbox_image_path': bbox_image_path,
            'video_path': detection_data.get('video_path')
        }
        
        # Insert into database
        detection_id = self.db.insert_detection(db_record)
        if detection_id:
            category_str = db_record.get('category', 'none')
            logger.info(f"✓ Stored detection {detection_id}: {image_path} (category: {category_str})")
            return True
        else:
            logger.error(f"Failed to store detection: {image_path}")
            return False
    
    def run_cleanup_task(self):
        """Run scheduled cleanup task."""
        if not self.config.get('image_cleanup_enabled', False):
            return
        
        try:
            retention_days = self.config.get('image_retention_days', 90)
            keep_detected = self.config.get('image_cleanup_keep_detected', True)
            detected_retention_days = self.config.get('image_cleanup_detected_retention_days', 365)
            
            logger.info("Running scheduled image cleanup...")
            deleted, orphaned = self.image_manager.cleanup_old_images(
                retention_days=retention_days,
                keep_detected=keep_detected,
                detected_retention_days=detected_retention_days
            )
            logger.info(f"Cleanup complete: {deleted} old images, {orphaned} orphaned images deleted")
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
    
    def start_cleanup_scheduler(self):
        """Start the cleanup scheduler in a background thread."""
        if not self.config.get('image_cleanup_enabled', False):
            logger.info("Image cleanup is disabled")
            return
        
        cleanup_schedule = self.config.get('image_cleanup_schedule', '0 2 * * *')
        
        # Parse cron-like schedule (simple format: "hour minute * * *")
        # For now, support daily at specific time
        try:
            parts = cleanup_schedule.split()
            if len(parts) >= 2:
                hour = int(parts[0])
                minute = int(parts[1])
                schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(self.run_cleanup_task)
                logger.info(f"Scheduled image cleanup daily at {hour:02d}:{minute:02d}")
        except Exception as e:
            logger.warning(f"Could not parse cleanup schedule '{cleanup_schedule}', using default (2 AM): {e}")
            schedule.every().day.at("02:00").do(self.run_cleanup_task)
        
        def scheduler_loop():
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        scheduler_thread.start()
        logger.info("Cleanup scheduler thread started")
    
    def run(self):
        """Main service loop."""
        if not self.connect_redis():
            logger.error("Failed to connect to Redis, exiting")
            return False
        
        if not self.connect_database():
            logger.error("Failed to connect to database, exiting")
            return False
        
        self.running = True
        detections_queue = self.config.get('detections_queue', 'detections')
        timeout = 5  # seconds
        
        logger.info(f"\nStarting storage service...")
        logger.info(f"Consuming from queue: {detections_queue}")
        
        # Start cleanup scheduler
        self.start_cleanup_scheduler()
        
        logger.info("Press Ctrl+C to stop\n")
        
        processed_count = 0
        
        try:
            while self.running:
                try:
                    # Blocking pop from Redis queue with timeout
                    result = self.redis_client.brpop(detections_queue, timeout=timeout)
                    
                    if result is None:
                        # Timeout - continue loop to check if still running
                        continue
                    
                    _, message_json = result
                    detection_data = json.loads(message_json)
                    
                    # Process detection
                    if self.process_detection(detection_data):
                        processed_count += 1
                    
                except redis.exceptions.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}, retrying...")
                    time.sleep(5)
                    if not self.connect_redis():
                        logger.error("Failed to reconnect to Redis")
                        break
                except redis.exceptions.TimeoutError:
                    # Timeout is expected when queue is empty, just continue
                    continue
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding message: {e}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    import traceback
                    traceback.print_exc()
        
        except KeyboardInterrupt:
            logger.info("\nStopping storage service...")
        finally:
            self.running = False
            if self.db:
                self.db.close()
            logger.info(f"Storage service stopped. Processed {processed_count} detections.")

def load_config():
    """Load configuration from environment variables."""
    config = {
        'redis_host': os.getenv('REDIS_HOST', 'redis'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'detections_queue': os.getenv('REDIS_DETECTIONS_QUEUE', 'detections'),
        'images_path': os.getenv('IMAGES_PATH', 'data/images'),
        'postgres_host': os.getenv('POSTGRES_HOST', 'postgres'),
        'postgres_port': int(os.getenv('POSTGRES_PORT', 5432)),
        'postgres_db': os.getenv('POSTGRES_DB', 'birdmonitor'),
        'postgres_user': os.getenv('POSTGRES_USER', 'birdmonitor'),
        'postgres_password': os.getenv('POSTGRES_PASSWORD', 'changeme265'),
        'zip_code': os.getenv('ZIP_CODE', '34232'),
        # Image management settings
        'image_retention_days': int(os.getenv('IMAGE_RETENTION_DAYS', '90')),
        'image_cleanup_enabled': os.getenv('IMAGE_CLEANUP_ENABLED', 'false').lower() == 'true',
        'image_cleanup_schedule': os.getenv('IMAGE_CLEANUP_SCHEDULE', '0 2 * * *'),
        'image_cleanup_keep_detected': os.getenv('IMAGE_CLEANUP_KEEP_DETECTED', 'true').lower() == 'true',
        'image_cleanup_detected_retention_days': int(os.getenv('IMAGE_CLEANUP_DETECTED_RETENTION_DAYS', '365')),
        'image_compression_enabled': os.getenv('IMAGE_COMPRESSION_ENABLED', 'false').lower() == 'true',
        'image_compression_quality': int(os.getenv('IMAGE_COMPRESSION_QUALITY', '85')),
        'image_compression_preserve_original': os.getenv('IMAGE_COMPRESSION_PRESERVE_ORIGINAL', 'false').lower() == 'true',
        'thumbnail_enabled': os.getenv('THUMBNAIL_ENABLED', 'true').lower() == 'true',
        'thumbnail_width': int(os.getenv('THUMBNAIL_WIDTH', '300')),
        'thumbnail_height': int(os.getenv('THUMBNAIL_HEIGHT', '300')),
        'thumbnail_quality': int(os.getenv('THUMBNAIL_QUALITY', '85')),
    }
    return config

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("\nReceived shutdown signal")
    sys.exit(0)

if __name__ == "__main__":
    logger.info("Starting storage service...")
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    config = load_config()
    logger.info("Configuration loaded:")
    for key, value in config.items():
        if 'password' in key.lower():
            logger.info(f"  {key}: ***")
        else:
            logger.info(f"  {key}: {value}")
    
    service = StorageService(config)
    service.run()

