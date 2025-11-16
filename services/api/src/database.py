"""
Database operations for API service.
"""
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone

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
                
                # Get paginated results with annotation info
                offset = (page - 1) * page_size
                query = f"""
                    SELECT d.*, 
                           a.id as annotation_id,
                           a.is_correct as annotation_is_correct,
                           a.correct_class as annotation_correct_class,
                           a.incorrect_class as annotation_incorrect_class,
                           a.notes as annotation_notes,
                           a.created_at as annotation_created_at,
                           a.updated_at as annotation_updated_at
                    FROM detections d
                    LEFT JOIN detection_annotations a ON d.id = a.detection_id
                    WHERE {where_clause}
                    ORDER BY d.timestamp DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([page_size, offset])
                cur.execute(query, params)
                
                rows = cur.fetchall()
                detections = []
                for row in rows:
                    detection = dict(row)
                    # Add UTC timezone info to naive timestamps (stored as UTC in TIMESTAMP column)
                    if detection.get('timestamp') and detection['timestamp'].tzinfo is None:
                        detection['timestamp'] = detection['timestamp'].replace(tzinfo=timezone.utc)
                    if detection.get('detected_at') and detection['detected_at'] and detection['detected_at'].tzinfo is None:
                        detection['detected_at'] = detection['detected_at'].replace(tzinfo=timezone.utc)
                    if detection.get('created_at') and detection['created_at'].tzinfo is None:
                        detection['created_at'] = detection['created_at'].replace(tzinfo=timezone.utc)
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
                    # Build annotation object if present
                    if detection.get('annotation_id'):
                        detection['annotation'] = {
                            'id': detection['annotation_id'],
                            'detection_id': detection['id'],
                            'is_correct': detection['annotation_is_correct'],
                            'correct_class': detection['annotation_correct_class'],
                            'incorrect_class': detection['annotation_incorrect_class'],
                            'notes': detection['annotation_notes'],
                            'created_at': detection['annotation_created_at'],
                            'updated_at': detection['annotation_updated_at']
                        }
                        # Add timezone info to annotation timestamps
                        if detection['annotation']['created_at'] and detection['annotation']['created_at'].tzinfo is None:
                            detection['annotation']['created_at'] = detection['annotation']['created_at'].replace(tzinfo=timezone.utc)
                        if detection['annotation']['updated_at'] and detection['annotation']['updated_at'].tzinfo is None:
                            detection['annotation']['updated_at'] = detection['annotation']['updated_at'].replace(tzinfo=timezone.utc)
                    # Remove individual annotation fields
                    for key in ['annotation_id', 'annotation_is_correct', 'annotation_correct_class', 
                               'annotation_incorrect_class', 'annotation_notes', 'annotation_created_at', 'annotation_updated_at']:
                        detection.pop(key, None)
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
                cur.execute("""
                    SELECT d.*, 
                           a.id as annotation_id,
                           a.is_correct as annotation_is_correct,
                           a.correct_class as annotation_correct_class,
                           a.incorrect_class as annotation_incorrect_class,
                           a.notes as annotation_notes,
                           a.created_at as annotation_created_at,
                           a.updated_at as annotation_updated_at
                    FROM detections d
                    LEFT JOIN detection_annotations a ON d.id = a.detection_id
                    WHERE d.id = %s
                """, (detection_id,))
                row = cur.fetchone()
                if row:
                    detection = dict(row)
                    # Add UTC timezone info to naive timestamps (stored as UTC in TIMESTAMP column)
                    if detection.get('timestamp') and detection['timestamp'].tzinfo is None:
                        detection['timestamp'] = detection['timestamp'].replace(tzinfo=timezone.utc)
                    if detection.get('detected_at') and detection['detected_at'] and detection['detected_at'].tzinfo is None:
                        detection['detected_at'] = detection['detected_at'].replace(tzinfo=timezone.utc)
                    if detection.get('created_at') and detection['created_at'].tzinfo is None:
                        detection['created_at'] = detection['created_at'].replace(tzinfo=timezone.utc)
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
                    # Build annotation object if present
                    if detection.get('annotation_id'):
                        detection['annotation'] = {
                            'id': detection['annotation_id'],
                            'detection_id': detection['id'],
                            'is_correct': detection['annotation_is_correct'],
                            'correct_class': detection['annotation_correct_class'],
                            'incorrect_class': detection['annotation_incorrect_class'],
                            'notes': detection['annotation_notes'],
                            'created_at': detection['annotation_created_at'],
                            'updated_at': detection['annotation_updated_at']
                        }
                        # Add timezone info to annotation timestamps
                        if detection['annotation']['created_at'] and detection['annotation']['created_at'].tzinfo is None:
                            detection['annotation']['created_at'] = detection['annotation']['created_at'].replace(tzinfo=timezone.utc)
                        if detection['annotation']['updated_at'] and detection['annotation']['updated_at'].tzinfo is None:
                            detection['annotation']['updated_at'] = detection['annotation']['updated_at'].replace(tzinfo=timezone.utc)
                    # Remove individual annotation fields
                    for key in ['annotation_id', 'annotation_is_correct', 'annotation_correct_class', 
                               'annotation_incorrect_class', 'annotation_notes', 'annotation_created_at', 'annotation_updated_at']:
                        detection.pop(key, None)
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
                    # Add UTC timezone info to naive timestamps (stored as UTC in TIMESTAMP column)
                    if detection.get('timestamp') and detection['timestamp'].tzinfo is None:
                        detection['timestamp'] = detection['timestamp'].replace(tzinfo=timezone.utc)
                    if detection.get('detected_at') and detection['detected_at'] and detection['detected_at'].tzinfo is None:
                        detection['detected_at'] = detection['detected_at'].replace(tzinfo=timezone.utc)
                    if detection.get('created_at') and detection['created_at'].tzinfo is None:
                        detection['created_at'] = detection['created_at'].replace(tzinfo=timezone.utc)
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
                
                # Squirrels detected
                cur.execute("SELECT COUNT(*) as squirrels FROM detections WHERE is_squirrel = true")
                squirrels = cur.fetchone()['squirrels']
                
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
                    WHERE (is_bird = true OR is_human = true OR is_squirrel = true) AND confidence IS NOT NULL
                """)
                avg_conf_row = cur.fetchone()
                avg_conf = float(avg_conf_row['avg_conf']) if avg_conf_row['avg_conf'] else None
                
                return {
                    'total_detections': total,
                    'birds_detected': birds,
                    'humans_detected': humans,
                    'squirrels_detected': squirrels,
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
    
    def delete_detections_bulk(self, detection_ids: List[int]) -> int:
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
    
    def get_detection_image_paths(self, detection_ids: List[int]) -> List[str]:
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
        category: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        is_bird: Optional[bool] = None,
        is_human: Optional[bool] = None
    ) -> Tuple[int, List[str]]:
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
    
    def create_or_update_annotation(
        self,
        detection_id: int,
        is_correct: bool,
        correct_class: Optional[str] = None,
        incorrect_class: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Optional[int]:
        """Create or update an annotation for a detection. Returns annotation ID."""
        conn = self.get_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor() as cur:
                # Check if annotation exists
                cur.execute("SELECT id FROM detection_annotations WHERE detection_id = %s", (detection_id,))
                existing = cur.fetchone()
                
                if existing:
                    # Update existing annotation
                    cur.execute("""
                        UPDATE detection_annotations
                        SET is_correct = %s,
                            correct_class = %s,
                            incorrect_class = %s,
                            notes = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE detection_id = %s
                        RETURNING id
                    """, (is_correct, correct_class, incorrect_class, notes, detection_id))
                    annotation_id = cur.fetchone()[0]
                else:
                    # Create new annotation
                    cur.execute("""
                        INSERT INTO detection_annotations (
                            detection_id, is_correct, correct_class, incorrect_class, notes
                        ) VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    """, (detection_id, is_correct, correct_class, incorrect_class, notes))
                    annotation_id = cur.fetchone()[0]
                
                conn.commit()
                logger.info(f"Created/updated annotation {annotation_id} for detection {detection_id}")
                return annotation_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating/updating annotation: {e}")
            return None
        finally:
            self.return_connection(conn)
    
    def get_annotation_by_detection_id(self, detection_id: int) -> Optional[Dict[str, Any]]:
        """Get annotation for a detection by detection ID."""
        conn = self.get_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM detection_annotations
                    WHERE detection_id = %s
                """, (detection_id,))
                row = cur.fetchone()
                if row:
                    annotation = dict(row)
                    # Add UTC timezone info to naive timestamps
                    if annotation.get('created_at') and annotation['created_at'].tzinfo is None:
                        annotation['created_at'] = annotation['created_at'].replace(tzinfo=timezone.utc)
                    if annotation.get('updated_at') and annotation['updated_at'].tzinfo is None:
                        annotation['updated_at'] = annotation['updated_at'].replace(tzinfo=timezone.utc)
                    return annotation
                return None
        except Exception as e:
            logger.error(f"Error getting annotation: {e}")
            return None
        finally:
            self.return_connection(conn)
    
    def get_annotations(
        self,
        page: int = 1,
        page_size: int = 20,
        is_correct: Optional[bool] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get annotations with pagination and filters. Returns (annotations, total)."""
        conn = self.get_connection()
        if not conn:
            return [], 0
        
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Build WHERE clause
                conditions = []
                params = []
                
                if is_correct is not None:
                    conditions.append("is_correct = %s")
                    params.append(is_correct)
                
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                
                # Get total count
                count_query = f"SELECT COUNT(*) FROM detection_annotations WHERE {where_clause}"
                cur.execute(count_query, params)
                total = cur.fetchone()['count']
                
                # Get paginated results
                offset = (page - 1) * page_size
                query = f"""
                    SELECT * FROM detection_annotations
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([page_size, offset])
                cur.execute(query, params)
                
                rows = cur.fetchall()
                annotations = []
                for row in rows:
                    annotation = dict(row)
                    # Add UTC timezone info to naive timestamps
                    if annotation.get('created_at') and annotation['created_at'].tzinfo is None:
                        annotation['created_at'] = annotation['created_at'].replace(tzinfo=timezone.utc)
                    if annotation.get('updated_at') and annotation['updated_at'].tzinfo is None:
                        annotation['updated_at'] = annotation['updated_at'].replace(tzinfo=timezone.utc)
                    annotations.append(annotation)
                
                return annotations, total
        except Exception as e:
            logger.error(f"Error getting annotations: {e}")
            return [], 0
        finally:
            self.return_connection(conn)
    
    def delete_annotation(self, detection_id: int) -> bool:
        """Delete an annotation by detection ID."""
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM detection_annotations WHERE detection_id = %s", (detection_id,))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info(f"Deleted annotation for detection {detection_id}")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting annotation: {e}")
            conn.rollback()
            return False
        finally:
            self.return_connection(conn)
    
    def close(self):
        """Close all connections in the pool."""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Database connection pool closed")

