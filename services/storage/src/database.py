"""
Database operations for storage service.
"""
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, config):
        self.config = config
        self.connection_pool = None
    
    def connect(self):
        """Create connection pool to PostgreSQL."""
        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                1,  # min connections
                10,  # max connections
                host=self.config['postgres_host'],
                database=self.config['postgres_db'],
                user=self.config['postgres_user'],
                password=self.config['postgres_password'],
                port=self.config.get('postgres_port', 5432)
            )
            if self.connection_pool:
                logger.info("✓ Database connection pool created")
                return True
            else:
                logger.error("Failed to create database connection pool")
                return False
        except Exception as e:
            logger.error(f"Error creating connection pool: {e}")
            return False
    
    def get_connection(self):
        """Get a connection from the pool."""
        if self.connection_pool:
            return self.connection_pool.getconn()
        return None
    
    def return_connection(self, conn):
        """Return a connection to the pool."""
        if self.connection_pool:
            self.connection_pool.putconn(conn)
    
    def init_schema(self):
        """Initialize database schema if it doesn't exist."""
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cur:
                # Create detections table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS detections (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP NOT NULL,
                        image_path TEXT NOT NULL,
                        is_bird BOOLEAN NOT NULL,
                        is_human BOOLEAN NOT NULL DEFAULT FALSE,
                        is_squirrel BOOLEAN NOT NULL DEFAULT FALSE,
                        category TEXT,
                        confidence REAL,
                        species TEXT,
                        bounding_boxes JSONB,
                        motion_score REAL,
                        metadata JSONB,
                        detected_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Add new columns if they don't exist (for migration)
                cur.execute("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='is_human') THEN
                            ALTER TABLE detections ADD COLUMN is_human BOOLEAN NOT NULL DEFAULT FALSE;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='is_squirrel') THEN
                            ALTER TABLE detections ADD COLUMN is_squirrel BOOLEAN NOT NULL DEFAULT FALSE;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='category') THEN
                            ALTER TABLE detections ADD COLUMN category TEXT;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='weather') THEN
                            ALTER TABLE detections ADD COLUMN weather JSONB;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='bird_name') THEN
                            ALTER TABLE detections ADD COLUMN bird_name TEXT;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='bird_backstory') THEN
                            ALTER TABLE detections ADD COLUMN bird_backstory TEXT;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='bbox_image_path') THEN
                            ALTER TABLE detections ADD COLUMN bbox_image_path TEXT;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='detections' AND column_name='video_path') THEN
                            ALTER TABLE detections ADD COLUMN video_path TEXT;
                        END IF;
                    END $$;
                """)
                
                # Create indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detections_timestamp 
                    ON detections(timestamp);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detections_is_bird 
                    ON detections(is_bird);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detections_is_human 
                    ON detections(is_human);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detections_is_squirrel 
                    ON detections(is_squirrel);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detections_category 
                    ON detections(category);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detections_created_at 
                    ON detections(created_at);
                """)
                
                # Create detection_annotations table for human feedback
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS detection_annotations (
                        id SERIAL PRIMARY KEY,
                        detection_id INTEGER NOT NULL REFERENCES detections(id) ON DELETE CASCADE,
                        is_correct BOOLEAN NOT NULL,
                        correct_class TEXT,
                        incorrect_class TEXT,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(detection_id)
                    );
                """)
                
                # Create indexes for annotations
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_annotations_detection_id 
                    ON detection_annotations(detection_id);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_annotations_is_correct 
                    ON detection_annotations(is_correct);
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_annotations_created_at 
                    ON detection_annotations(created_at);
                """)
                
                conn.commit()
                logger.info("✓ Database schema initialized")
                return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Error initializing schema: {e}")
            return False
        finally:
            self.return_connection(conn)
    
    def insert_detection(self, detection_data):
        """Insert a detection record into the database."""
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cur:
                import json
                cur.execute("""
                    INSERT INTO detections (
                        timestamp, image_path, is_bird, is_human, is_squirrel, category, confidence, species,
                        bounding_boxes, motion_score, metadata, detected_at, weather,
                        bird_name, bird_backstory, bbox_image_path, video_path
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s::jsonb,
                        %s, %s, %s, %s
                    )
                    RETURNING id;
                """, (
                    detection_data['timestamp'],
                    detection_data['image_path'],
                    detection_data.get('is_bird', False),
                    detection_data.get('is_human', False),
                    detection_data.get('is_squirrel', False),
                    detection_data.get('category'),
                    detection_data.get('confidence'),
                    detection_data.get('species'),
                    json.dumps(detection_data.get('bounding_boxes', [])),
                    detection_data.get('motion_score'),
                    json.dumps(detection_data.get('metadata', {})),
                    detection_data.get('detected_at'),
                    json.dumps(detection_data.get('weather')) if detection_data.get('weather') else None,
                    detection_data.get('bird_name'),
                    detection_data.get('bird_backstory'),
                    detection_data.get('bbox_image_path'),
                    detection_data.get('video_path')
                ))
                
                detection_id = cur.fetchone()[0]
                conn.commit()
                logger.debug(f"Inserted detection with id: {detection_id}")
                return detection_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Error inserting detection: {e}")
            return None
        finally:
            self.return_connection(conn)
    
    def delete_detections_bulk(self, detection_ids: list) -> int:
        """Delete multiple detections by IDs. Returns number of deleted rows."""
        if not detection_ids:
            return 0
        
        conn = self.get_connection()
        if not conn:
            return 0
        
        try:
            with conn.cursor() as cur:
                # Use parameterized query with tuple for IN clause
                placeholders = ','.join(['%s'] * len(detection_ids))
                cur.execute(
                    f"DELETE FROM detections WHERE id IN ({placeholders})",
                    tuple(detection_ids)
                )
                deleted_count = cur.rowcount
                conn.commit()
                logger.info(f"Bulk deleted {deleted_count} detections")
                return deleted_count
        except Exception as e:
            conn.rollback()
            logger.error(f"Error bulk deleting detections: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    def get_detection_image_paths(self, detection_ids: list) -> list:
        """Get image paths for given detection IDs."""
        if not detection_ids:
            return []
        
        conn = self.get_connection()
        if not conn:
            return []
        
        try:
            with conn.cursor() as cur:
                placeholders = ','.join(['%s'] * len(detection_ids))
                cur.execute(
                    f"SELECT image_path FROM detections WHERE id IN ({placeholders})",
                    tuple(detection_ids)
                )
                rows = cur.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error getting image paths: {e}")
            return []
        finally:
            self.return_connection(conn)
    
    def delete_detections_by_filter(
        self,
        category: str = None,
        start_date = None,
        end_date = None,
        is_bird: bool = None,
        is_human: bool = None
    ) -> tuple[int, list]:
        """
        Delete detections by filter criteria.
        Returns tuple of (deleted_count, image_paths)
        """
        conn = self.get_connection()
        if not conn:
            return 0, []
        
        try:
            with conn.cursor() as cur:
                # Build WHERE clause
                conditions = []
                params = []
                
                if category:
                    conditions.append("category = %s")
                    params.append(category)
                
                if start_date:
                    conditions.append("timestamp >= %s")
                    params.append(start_date)
                
                if end_date:
                    conditions.append("timestamp <= %s")
                    params.append(end_date)
                
                if is_bird is not None:
                    conditions.append("is_bird = %s")
                    params.append(is_bird)
                
                if is_human is not None:
                    conditions.append("is_human = %s")
                    params.append(is_human)
                
                if not conditions:
                    # Don't delete all if no conditions
                    logger.warning("No filter conditions provided for bulk delete")
                    return 0, []
                
                where_clause = " AND ".join(conditions)
                
                # Get image paths first
                cur.execute(
                    f"SELECT image_path FROM detections WHERE {where_clause}",
                    params
                )
                image_paths = [row[0] for row in cur.fetchall()]
                
                # Delete detections
                cur.execute(
                    f"DELETE FROM detections WHERE {where_clause}",
                    params
                )
                deleted_count = cur.rowcount
                conn.commit()
                logger.info(f"Bulk deleted {deleted_count} detections by filter")
                return deleted_count, image_paths
        except Exception as e:
            conn.rollback()
            logger.error(f"Error bulk deleting by filter: {e}")
            return 0, []
        finally:
            self.return_connection(conn)
    
    def close(self):
        """Close all connections in the pool."""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Database connection pool closed")

