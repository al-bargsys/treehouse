"""
Database operations for API service.
"""
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

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
    
    def check_health(self):
        """Check database health."""
        conn = self.get_connection()
        if not conn:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
        except:
            return False
        finally:
            self.return_connection(conn)
    
    def get_detections(
        self,
        page: int = 1,
        page_size: int = 20,
        is_bird: Optional[bool] = None,
        is_human: Optional[bool] = None,
        category: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get detections with pagination and filters."""
        conn = self.get_connection()
        if not conn:
            return [], 0
        
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Build WHERE clause
                conditions = []
                params = []
                
                if is_bird is not None:
                    conditions.append("is_bird = %s")
                    params.append(is_bird)
                
                if is_human is not None:
                    conditions.append("is_human = %s")
                    params.append(is_human)
                
                if category:
                    conditions.append("category = %s")
                    params.append(category)
                
                if start_date:
                    conditions.append("timestamp >= %s")
                    params.append(start_date)
                
                if end_date:
                    conditions.append("timestamp <= %s")
                    params.append(end_date)
                
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                
                # Get total count
                count_query = f"SELECT COUNT(*) FROM detections WHERE {where_clause}"
                cur.execute(count_query, params)
                total = cur.fetchone()['count']
                
                # Get paginated results
                offset = (page - 1) * page_size
                query = f"""
                    SELECT * FROM detections
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([page_size, offset])
                cur.execute(query, params)
                
                rows = cur.fetchall()
                detections = []
                for row in rows:
                    detection = dict(row)
                    # Parse JSONB fields
                    import json
                    if detection.get('bounding_boxes'):
                        if isinstance(detection['bounding_boxes'], str):
                            detection['bounding_boxes'] = json.loads(detection['bounding_boxes'])
                    if detection.get('metadata'):
                        if isinstance(detection['metadata'], str):
                            detection['metadata'] = json.loads(detection['metadata'])
                    if detection.get('weather'):
                        if isinstance(detection['weather'], str):
                            detection['weather'] = json.loads(detection['weather'])
                    detections.append(detection)
                
                return detections, total
        except Exception as e:
            logger.error(f"Error getting detections: {e}")
            return [], 0
        finally:
            self.return_connection(conn)
    
    def get_detection_by_id(self, detection_id: int) -> Optional[Dict[str, Any]]:
        """Get a single detection by ID."""
        conn = self.get_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM detections WHERE id = %s", (detection_id,))
                row = cur.fetchone()
                if row:
                    detection = dict(row)
                    # Parse JSONB fields
                    import json
                    if detection.get('bounding_boxes'):
                        if isinstance(detection['bounding_boxes'], str):
                            detection['bounding_boxes'] = json.loads(detection['bounding_boxes'])
                    if detection.get('metadata'):
                        if isinstance(detection['metadata'], str):
                            detection['metadata'] = json.loads(detection['metadata'])
                    if detection.get('weather'):
                        if isinstance(detection['weather'], str):
                            detection['weather'] = json.loads(detection['weather'])
                    return detection
                return None
        except Exception as e:
            logger.error(f"Error getting detection: {e}")
            return None
        finally:
            self.return_connection(conn)
    
    def get_latest_detection(self) -> Optional[Dict[str, Any]]:
        """Get the most recent detection."""
        conn = self.get_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM detections
                    ORDER BY timestamp DESC
                    LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    detection = dict(row)
                    # Parse JSONB fields
                    import json
                    if detection.get('bounding_boxes'):
                        if isinstance(detection['bounding_boxes'], str):
                            detection['bounding_boxes'] = json.loads(detection['bounding_boxes'])
                    if detection.get('metadata'):
                        if isinstance(detection['metadata'], str):
                            detection['metadata'] = json.loads(detection['metadata'])
                    if detection.get('weather'):
                        if isinstance(detection['weather'], str):
                            detection['weather'] = json.loads(detection['weather'])
                    return detection
                return None
        except Exception as e:
            logger.error(f"Error getting latest detection: {e}")
            return None
        finally:
            self.return_connection(conn)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about detections."""
        conn = self.get_connection()
        if not conn:
            return {}
        
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Total detections
                cur.execute("SELECT COUNT(*) as total FROM detections")
                total = cur.fetchone()['total']
                
                # Birds detected
                cur.execute("SELECT COUNT(*) as birds FROM detections WHERE is_bird = true")
                birds = cur.fetchone()['birds']
                
                # Humans detected
                cur.execute("SELECT COUNT(*) as humans FROM detections WHERE is_human = true")
                humans = cur.fetchone()['humans']
                
                # Recent activity (24h)
                yesterday = datetime.now() - timedelta(days=1)
                cur.execute("SELECT COUNT(*) as recent_24h FROM detections WHERE created_at >= %s", (yesterday,))
                recent_24h = cur.fetchone()['recent_24h']
                
                # Recent activity (7d)
                week_ago = datetime.now() - timedelta(days=7)
                cur.execute("SELECT COUNT(*) as recent_7d FROM detections WHERE created_at >= %s", (week_ago,))
                recent_7d = cur.fetchone()['recent_7d']
                
                # Average confidence for birds and humans
                cur.execute("""
                    SELECT AVG(confidence) as avg_conf
                    FROM detections
                    WHERE (is_bird = true OR is_human = true) AND confidence IS NOT NULL
                """)
                avg_conf_row = cur.fetchone()
                avg_conf = float(avg_conf_row['avg_conf']) if avg_conf_row['avg_conf'] else None
                
                return {
                    'total_detections': total,
                    'birds_detected': birds,
                    'humans_detected': humans,
                    'recent_activity_24h': recent_24h,
                    'recent_activity_7d': recent_7d,
                    'average_confidence': avg_conf
                }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
        finally:
            self.return_connection(conn)
    
    def delete_detection(self, detection_id: int) -> bool:
        """Delete a detection by ID."""
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM detections WHERE id = %s", (detection_id,))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info(f"Deleted detection {detection_id}")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting detection {detection_id}: {e}")
            conn.rollback()
            return False
        finally:
            self.return_connection(conn)
    
    def close(self):
        """Close all connections in the pool."""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Database connection pool closed")

