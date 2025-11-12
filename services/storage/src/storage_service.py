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
from pathlib import Path
from datetime import datetime
from database import Database
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
        
        # Verify image exists
        if not self.verify_image_exists(image_path):
            logger.warning(f"Image not found: {image_path}, skipping storage")
            return False
        
        # Prepare data for database
        detected_at = None
        if detection_data.get('detected_at'):
            try:
                detected_at = datetime.fromisoformat(detection_data['detected_at'].replace('Z', '+00:00'))
            except:
                detected_at = datetime.now()
        
        timestamp = datetime.fromisoformat(detection_data['timestamp'].replace('Z', '+00:00'))
        
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
        is_bird = detection_data.get('is_bird', False)
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
        
        db_record = {
            'timestamp': timestamp,
            'image_path': image_path,
            'is_bird': is_bird,
            'is_human': detection_data.get('is_human', False),
            'category': detection_data.get('category'),
            'confidence': detection_data.get('confidence'),
            'species': detection_data.get('species'),
            'bounding_boxes': detection_data.get('bounding_boxes', []),  # Will be converted to JSON in database.py
            'motion_score': detection_data.get('motion_score'),
            'metadata': {
                'source': detection_data.get('source', 'unknown'),
                'num_detections': detection_data.get('num_detections', 0),
                'num_birds': detection_data.get('num_birds', 0),
                'num_humans': detection_data.get('num_humans', 0)
            },
            'detected_at': detected_at,
            'weather': weather_data,
            'bird_name': bird_name,
            'bird_backstory': bird_backstory
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

