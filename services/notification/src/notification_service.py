#!/usr/bin/env python3
"""
Notification service for bird and human monitoring system.
Consumes detections from Redis queue and sends Slack notifications.
"""
import os
import sys
import time
import json
import signal
import redis
import requests
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, config):
        self.config = config
        self.redis_client = None
        self.running = False
        self.last_notification_time = None
        self.cooldown_seconds = config.get('notification_cooldown', 300)  # 5 minutes default
    
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
    
    def check_cooldown(self):
        """Check if cooldown period has expired."""
        if self.last_notification_time is None:
            return True
        
        elapsed = (datetime.now() - self.last_notification_time).total_seconds()
        return elapsed >= self.cooldown_seconds
    
    def get_cooldown_key(self):
        """Get Redis key for cooldown tracking."""
        return "notification:cooldown"
    
    def check_redis_cooldown(self):
        """Check cooldown using Redis (for distributed systems)."""
        try:
            cooldown_key = self.get_cooldown_key()
            last_time_str = self.redis_client.get(cooldown_key)
            
            if last_time_str is None:
                return True
            
            last_time = datetime.fromisoformat(last_time_str)
            elapsed = (datetime.now() - last_time).total_seconds()
            return elapsed >= self.cooldown_seconds
        except Exception as e:
            logger.warning(f"Error checking Redis cooldown: {e}, using local cooldown")
            return self.check_cooldown()
    
    def update_cooldown(self):
        """Update cooldown timestamp."""
        self.last_notification_time = datetime.now()
        try:
            cooldown_key = self.get_cooldown_key()
            self.redis_client.set(cooldown_key, self.last_notification_time.isoformat())
        except Exception as e:
            logger.warning(f"Error updating Redis cooldown: {e}")
    
    def format_slack_message(self, detection_data):
        """Format detection data into Slack message."""
        is_bird = detection_data.get('is_bird', False)
        is_human = detection_data.get('is_human', False)
        category = detection_data.get('category', 'none')
        confidence = detection_data.get('confidence', 0.0)
        image_path = detection_data.get('image_path', '')
        timestamp = detection_data.get('timestamp', '')
        num_detections = detection_data.get('num_detections', 0)
        num_birds = detection_data.get('num_birds', 0)
        num_humans = detection_data.get('num_humans', 0)
        
        # Parse timestamp
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            time_str = timestamp
        
        # Determine emoji and title based on category
        if category == 'both':
            emoji = "🐦👤"
            title = "Bird and Human Detected!"
            color = "good"  # Green
        elif category == 'bird':
            emoji = "🐦"
            title = "Bird Detected!"
            color = "good"  # Green
        elif category == 'human':
            emoji = "👤"
            title = "Human Detected!"
            color = "warning"  # Yellow (different from bird to distinguish)
        else:
            emoji = "👁️"
            title = "Motion Detected"
            color = "warning"  # Yellow
        
        # Build message
        message = {
            "text": f"{emoji} {title}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {title}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Confidence:*\n{confidence:.1%}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Detections:*\n{num_detections}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Birds:*\n{num_birds}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Humans:*\n{num_humans}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Time:*\n{time_str}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Image:*\n`{image_path}`"
                        }
                    ]
                }
            ]
        }
        
        # Add image if available (requires image URL or file upload)
        # For now, just include the path - can be enhanced with image serving URL
        if image_path:
            message["blocks"].append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Image path: `{image_path}`"
                    }
                ]
            })
        
        return message
    
    def send_slack_notification(self, detection_data):
        """Send notification to Slack webhook."""
        webhook_url = self.config.get('slack_webhook_url')
        if not webhook_url:
            logger.warning("No Slack webhook URL configured, skipping notification")
            return False
        
        # Check cooldown
        if not self.check_redis_cooldown():
            elapsed = (datetime.now() - self.last_notification_time).total_seconds() if self.last_notification_time else 0
            remaining = self.cooldown_seconds - elapsed
            logger.info(f"Cooldown active, skipping notification ({remaining:.0f}s remaining)")
            return False
        
        # Format message
        message = self.format_slack_message(detection_data)
        
        # Send to Slack
        try:
            response = requests.post(
                webhook_url,
                json=message,
                timeout=10
            )
            response.raise_for_status()
            
            logger.info(f"✓ Sent Slack notification for: {detection_data.get('image_path')}")
            self.update_cooldown()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False
    
    def process_detection(self, detection_data):
        """Process a single detection."""
        # Process if bird or human detected
        is_bird = detection_data.get('is_bird', False)
        is_human = detection_data.get('is_human', False)
        category = detection_data.get('category', 'none')
        
        if not (is_bird or is_human) or category == 'none':
            logger.debug("No bird or human detected, skipping notification")
            return
        
        # Check confidence threshold
        confidence = detection_data.get('confidence', 0.0)
        min_confidence = self.config.get('min_confidence', 0.7)
        if confidence < min_confidence:
            logger.debug(f"Confidence {confidence:.2f} below threshold {min_confidence}, skipping")
            return
        
        # Send notification
        self.send_slack_notification(detection_data)
    
    def run(self):
        """Main service loop."""
        # Check if service is enabled
        if not self.config.get('slack_webhook_url'):
            logger.warning("Slack webhook URL not configured. Service will start but won't send notifications.")
            logger.warning("Set SLACK_WEBHOOK_URL environment variable to enable notifications.")
        
        if not self.connect_redis():
            logger.error("Failed to connect to Redis, exiting")
            return False
        
        self.running = True
        detections_queue = self.config.get('detections_queue', 'detections')
        timeout = 5  # seconds
        
        logger.info(f"\nStarting notification service...")
        logger.info(f"Consuming from queue: {detections_queue}")
        logger.info(f"Cooldown: {self.cooldown_seconds} seconds")
        logger.info(f"Min confidence: {self.config.get('min_confidence', 0.7)}")
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
                    self.process_detection(detection_data)
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
            logger.info("\nStopping notification service...")
        finally:
            self.running = False
            logger.info(f"Notification service stopped. Processed {processed_count} detections.")

def load_config():
    """Load configuration from environment variables."""
    config = {
        'redis_host': os.getenv('REDIS_HOST', 'redis'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'detections_queue': os.getenv('REDIS_DETECTIONS_QUEUE', 'detections'),
        'slack_webhook_url': os.getenv('SLACK_WEBHOOK_URL', ''),
        'notification_cooldown': int(os.getenv('NOTIFICATION_COOLDOWN', '300')),  # 5 minutes
        'min_confidence': float(os.getenv('MIN_CONFIDENCE', '0.7')),
    }
    return config

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("\nReceived shutdown signal")
    sys.exit(0)

if __name__ == "__main__":
    logger.info("Starting notification service...")
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    config = load_config()
    logger.info("Configuration loaded:")
    for key, value in config.items():
        if 'webhook' in key.lower() or 'password' in key.lower():
            logger.info(f"  {key}: {'***' if value else '(not set)'}")
        else:
            logger.info(f"  {key}: {value}")
    
    service = NotificationService(config)
    service.run()

