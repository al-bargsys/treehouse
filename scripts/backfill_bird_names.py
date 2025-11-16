#!/usr/bin/env python3
"""
Backfill script to generate OpenAI names and backstories for existing bird detections.

This script will:
1. Find all bird detections without names/backstories
2. Generate names and backstories via OpenAI API
3. Update the database records

Usage:
    # Run locally (requires psycopg2-binary and openai packages)
    python scripts/backfill_bird_names.py
    
    # Run with dry-run to see what would be processed
    python scripts/backfill_bird_names.py --dry-run
    
    # Limit to first 10 detections (useful for testing)
    python scripts/backfill_bird_names.py --limit 10
    
    # Run inside Docker container
    docker exec -it bird-monitor-storage python /app/scripts/backfill_bird_names.py

Environment variables:
    OPENAI_API_KEY - OpenAI API key (required)
    POSTGRES_HOST - PostgreSQL host (default: localhost, use 'postgres' in Docker)
    POSTGRES_PORT - PostgreSQL port (default: 5432)
    POSTGRES_DB - Database name (default: birdmonitor)
    POSTGRES_USER - Database user (default: birdmonitor)
    POSTGRES_PASSWORD - Database password (required)
"""
import os
import sys
import time
import logging
from pathlib import Path

# Add parent directory to path to import shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils.openai_client import OpenAIBirdNamer
import psycopg2
import psycopg2.extras

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BirdBackfill:
    def __init__(self):
        self.db_conn = None
        self.openai_namer = None
        
    def connect_database(self):
        """Connect to PostgreSQL database."""
        # Auto-detect if running in Docker (check for /.dockerenv or container hostname)
        default_host = 'postgres' if os.path.exists('/.dockerenv') else 'localhost'
        
        config = {
            'host': os.getenv('POSTGRES_HOST', default_host),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'database': os.getenv('POSTGRES_DB', 'birdmonitor'),
            'user': os.getenv('POSTGRES_USER', 'birdmonitor'),
            'password': os.getenv('POSTGRES_PASSWORD')
        }
        
        if not config['password']:
            logger.error("POSTGRES_PASSWORD environment variable is required")
            logger.error("If running locally, you may need to expose the database port or run the script in Docker")
            return False
        
        try:
            logger.info(f"Connecting to database at {config['host']}:{config['port']}...")
            self.db_conn = psycopg2.connect(**config)
            logger.info("✓ Connected to database")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            if config['host'] == 'localhost':
                logger.error("\nTip: If the database is in Docker, try one of these:")
                logger.error("  1. Run the script inside Docker: docker exec bird-monitor-storage python /app/backfill_bird_names.py")
                logger.error("  2. Expose postgres port in docker-compose.yml and use POSTGRES_HOST=localhost")
                logger.error("  3. Set POSTGRES_HOST=postgres if running from another container")
            return False
    
    def init_openai(self):
        """Initialize OpenAI client."""
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.error("OPENAI_API_KEY environment variable is required")
            return False
        
        self.openai_namer = OpenAIBirdNamer(api_key=api_key)
        if not self.openai_namer.enabled:
            logger.error("Failed to initialize OpenAI client")
            return False
        
        logger.info("✓ OpenAI client initialized")
        return True
    
    def get_birds_needing_backfill(self):
        """Get all bird detections that need names/backstories."""
        with self.db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, image_path, timestamp, is_bird, bird_name, bird_backstory
                FROM detections
                WHERE is_bird = true
                  AND (bird_name IS NULL OR bird_backstory IS NULL)
                ORDER BY timestamp DESC
            """)
            return cur.fetchall()
    
    def update_detection(self, detection_id, bird_name, bird_backstory):
        """Update a detection with bird name and backstory."""
        with self.db_conn.cursor() as cur:
            cur.execute("""
                UPDATE detections
                SET bird_name = %s, bird_backstory = %s
                WHERE id = %s
            """, (bird_name, bird_backstory, detection_id))
            self.db_conn.commit()
    
    def backfill(self, dry_run=False, limit=None):
        """Backfill bird names and backstories."""
        logger.info("Fetching bird detections needing backfill...")
        birds = self.get_birds_needing_backfill()
        
        total = len(birds)
        if limit:
            birds = birds[:limit]
            logger.info(f"Limited to {len(birds)} detections (out of {total} total)")
        else:
            logger.info(f"Found {total} bird detections needing backfill")
        
        if not birds:
            logger.info("No birds need backfilling!")
            return
        
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made")
            for bird in birds:
                logger.info(f"  Would process: ID {bird['id']}, {bird['image_path']}, {bird['timestamp']}")
            return
        
        logger.info(f"Starting backfill for {len(birds)} detections...")
        logger.info("Press Ctrl+C to stop at any time\n")
        
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        for i, bird in enumerate(birds, 1):
            detection_id = bird['id']
            image_path = bird['image_path']
            timestamp = bird['timestamp']
            
            # Skip if already has both name and backstory
            if bird['bird_name'] and bird['bird_backstory']:
                logger.info(f"[{i}/{len(birds)}] Skipping ID {detection_id} - already has name and backstory")
                skipped_count += 1
                continue
            
            logger.info(f"[{i}/{len(birds)}] Processing ID {detection_id}: {image_path} ({timestamp})")
            
            try:
                # Check what we already have
                existing_name = bird['bird_name']
                existing_backstory = bird['bird_backstory']
                
                bird_name = existing_name
                bird_backstory = existing_backstory
                
                # Generate missing pieces
                if not bird_name:
                    logger.info(f"  Generating name...")
                    bird_name = self.openai_namer.generate_bird_name()
                    if not bird_name:
                        logger.warning(f"  Failed to generate name for ID {detection_id}")
                        error_count += 1
                        continue
                    logger.info(f"  Generated name: {bird_name}")
                
                if not bird_backstory:
                    logger.info(f"  Generating backstory for {bird_name}...")
                    bird_backstory = self.openai_namer.generate_bird_backstory(bird_name)
                    if not bird_backstory:
                        logger.warning(f"  Failed to generate backstory for ID {detection_id}")
                        # Still update with just the name if we generated it
                        if not existing_name:
                            self.update_detection(detection_id, bird_name, None)
                            success_count += 1
                            logger.info(f"  ✓ Updated with name: {bird_name}")
                        else:
                            error_count += 1
                        continue
                    logger.info(f"  Generated backstory")
                
                # Update database
                self.update_detection(detection_id, bird_name, bird_backstory)
                success_count += 1
                if existing_name:
                    logger.info(f"  ✓ Updated backstory for {bird_name}")
                else:
                    logger.info(f"  ✓ Updated: {bird_name}")
                logger.debug(f"     Backstory: {bird_backstory[:100]}...")
                
                # Rate limiting - be nice to OpenAI API
                if i < len(birds):
                    time.sleep(1)  # 1 second delay between requests
                    
            except KeyboardInterrupt:
                logger.info("\n\nInterrupted by user")
                break
            except Exception as e:
                logger.error(f"  ✗ Error processing ID {detection_id}: {e}")
                error_count += 1
                continue
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Backfill complete!")
        logger.info(f"  Success: {success_count}")
        logger.info(f"  Errors: {error_count}")
        logger.info(f"  Skipped: {skipped_count}")
        logger.info(f"  Total processed: {success_count + error_count + skipped_count}")
        logger.info(f"{'='*60}")
    
    def close(self):
        """Close database connection."""
        if self.db_conn:
            self.db_conn.close()
            logger.info("Database connection closed")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Backfill OpenAI-generated names and backstories for bird detections'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without making changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit the number of detections to process (useful for testing)'
    )
    args = parser.parse_args()
    
    backfill = BirdBackfill()
    
    try:
        # Initialize connections
        if not backfill.connect_database():
            sys.exit(1)
        
        if not backfill.init_openai():
            sys.exit(1)
        
        # Run backfill
        backfill.backfill(dry_run=args.dry_run, limit=args.limit)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        backfill.close()


if __name__ == "__main__":
    main()

