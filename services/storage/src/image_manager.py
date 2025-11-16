"""
Image management utilities for cleanup, compression, and thumbnail generation.
"""
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image, ImageDraw, ImageFont
import shutil

logger = logging.getLogger(__name__)


class ImageManager:
    """Manages image lifecycle: cleanup, compression, and thumbnail generation."""
    
    def __init__(self, config):
        self.config = config
        self.images_path = Path(config.get('images_path', 'data/images'))
        self.db = None  # Will be set by storage service
        
    def set_database(self, db):
        """Set database connection for checking image references."""
        self.db = db
    
    def get_image_path(self, image_path: str) -> Path:
        """Get full path to an image file."""
        return self.images_path / image_path
    
    def get_thumbnail_path(self, image_path: str) -> Path:
        """Get full path to a thumbnail file."""
        image_file = Path(image_path)
        # Insert 'thumbnails' directory before filename
        thumbnail_path = image_file.parent / 'thumbnails' / image_file.name
        return self.images_path / thumbnail_path
    
    def is_image_referenced(self, image_path: str) -> bool:
        """Check if an image is referenced in the database."""
        if not self.db:
            return False
        
        try:
            conn = self.db.get_connection()
            if not conn:
                return False
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM detections WHERE image_path = %s", (image_path,))
                count = cur.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.error(f"Error checking image reference: {e}")
            return True  # Assume referenced if error (safer)
        finally:
            if conn:
                self.db.return_connection(conn)
    
    def cleanup_old_images(
        self,
        retention_days: int = 90,
        keep_detected: bool = True,
        detected_retention_days: int = 365
    ) -> Tuple[int, int]:
        """
        Clean up old images based on retention policy.
        
        Returns:
            Tuple of (deleted_count, orphaned_deleted_count)
        """
        deleted_count = 0
        orphaned_deleted_count = 0
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        detected_cutoff_date = datetime.now() - timedelta(days=detected_retention_days) if keep_detected else cutoff_date
        
        logger.info(f"Starting image cleanup: retention={retention_days} days, detected_retention={detected_retention_days} days")
        
        # Walk through all image directories
        for year_month_dir in self.images_path.iterdir():
            if not year_month_dir.is_dir():
                continue
            
            for day_dir in year_month_dir.iterdir():
                if not day_dir.is_dir():
                    continue
                
                # Process images in this day directory
                for image_file in day_dir.glob('*.jpg'):
                    if image_file.name == 'thumbnails' or image_file.is_dir():
                        continue
                    
                    try:
                        # Get file modification time
                        file_mtime = datetime.fromtimestamp(image_file.stat().st_mtime)
                        
                        # Get relative path for database check
                        relative_path = image_file.relative_to(self.images_path)
                        image_path_str = str(relative_path).replace('\\', '/')
                        
                        # Check if image is referenced in database
                        is_referenced = self.is_image_referenced(image_path_str)
                        
                        # Determine cutoff date based on whether image is referenced
                        if is_referenced and keep_detected:
                            cutoff = detected_cutoff_date
                        else:
                            cutoff = cutoff_date
                        
                        # Delete if older than cutoff
                        if file_mtime < cutoff:
                            # Delete thumbnail if it exists
                            thumbnail_path = self.get_thumbnail_path(image_path_str)
                            if thumbnail_path.exists():
                                thumbnail_path.unlink()
                                logger.debug(f"Deleted thumbnail: {thumbnail_path}")
                            
                            # Delete bbox image if it exists
                            bbox_path = self.get_bbox_image_path(image_path_str)
                            if bbox_path.exists():
                                bbox_path.unlink()
                                logger.debug(f"Deleted bbox image: {bbox_path}")
                            
                            # Delete image
                            image_file.unlink()
                            deleted_count += 1
                            logger.info(f"Deleted old image: {image_path_str} (age: {(datetime.now() - file_mtime).days} days, referenced: {is_referenced})")
                        
                        # Also check for orphaned images (not referenced and older than 7 days)
                        elif not is_referenced:
                            orphan_cutoff = datetime.now() - timedelta(days=7)
                            if file_mtime < orphan_cutoff:
                                thumbnail_path = self.get_thumbnail_path(image_path_str)
                                if thumbnail_path.exists():
                                    thumbnail_path.unlink()
                                
                                # Delete bbox image if it exists
                                bbox_path = self.get_bbox_image_path(image_path_str)
                                if bbox_path.exists():
                                    bbox_path.unlink()
                                
                                image_file.unlink()
                                orphaned_deleted_count += 1
                                logger.info(f"Deleted orphaned image: {image_path_str}")
                    
                    except Exception as e:
                        logger.error(f"Error processing image {image_file}: {e}")
                
                # Clean up empty thumbnail directories
                thumbnail_dir = day_dir / 'thumbnails'
                if thumbnail_dir.exists() and thumbnail_dir.is_dir():
                    try:
                        if not any(thumbnail_dir.iterdir()):
                            thumbnail_dir.rmdir()
                            logger.debug(f"Removed empty thumbnail directory: {thumbnail_dir}")
                    except Exception as e:
                        logger.debug(f"Could not remove thumbnail directory {thumbnail_dir}: {e}")
                
                # Clean up empty bbox directories
                bbox_dir = day_dir / 'bbox'
                if bbox_dir.exists() and bbox_dir.is_dir():
                    try:
                        if not any(bbox_dir.iterdir()):
                            bbox_dir.rmdir()
                            logger.debug(f"Removed empty bbox directory: {bbox_dir}")
                    except Exception as e:
                        logger.debug(f"Could not remove bbox directory {bbox_dir}: {e}")
                
                # Clean up empty day directories
                try:
                    if not any(day_dir.iterdir()):
                        day_dir.rmdir()
                        logger.debug(f"Removed empty day directory: {day_dir}")
                except Exception as e:
                    logger.debug(f"Could not remove day directory {day_dir}: {e}")
        
        logger.info(f"Cleanup complete: deleted {deleted_count} old images, {orphaned_deleted_count} orphaned images")
        return deleted_count, orphaned_deleted_count
    
    def compress_image(
        self,
        image_path: str,
        quality: int = 85,
        preserve_original: bool = False,
        optimize: bool = True
    ) -> Optional[str]:
        """
        Compress an image file.
        
        Args:
            image_path: Relative path to image (e.g., "2025-11/12/image.jpg")
            quality: JPEG quality (1-100)
            preserve_original: If True, keep original and create .compressed.jpg
            optimize: Use Pillow optimize flag
        
        Returns:
            Path to compressed image, or None if failed
        """
        full_path = self.get_image_path(image_path)
        
        if not full_path.exists():
            logger.warning(f"Image not found for compression: {image_path}")
            return None
        
        try:
            # Open and compress image
            with Image.open(full_path) as img:
                # Convert to RGB if necessary (for JPEG)
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Determine output path
                if preserve_original:
                    output_path = full_path.parent / f"{full_path.stem}.compressed{full_path.suffix}"
                else:
                    output_path = full_path
                
                # Save compressed image
                save_kwargs = {'quality': quality, 'optimize': optimize}
                img.save(output_path, 'JPEG', **save_kwargs)
                
                # Get file sizes
                original_size = full_path.stat().st_size if preserve_original else output_path.stat().st_size
                compressed_size = output_path.stat().st_size
                
                # Replace original if not preserving
                if not preserve_original:
                    # Already saved to same path
                    pass
                
                reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
                logger.info(f"Compressed {image_path}: {original_size} -> {compressed_size} bytes ({reduction:.1f}% reduction)")
                
                return str(output_path.relative_to(self.images_path))
        
        except Exception as e:
            logger.error(f"Error compressing image {image_path}: {e}")
            return None
    
    def generate_thumbnail(
        self,
        image_path: str,
        width: int = 300,
        height: int = 300,
        quality: int = 85
    ) -> Optional[str]:
        """
        Generate a thumbnail for an image.
        
        Args:
            image_path: Relative path to image
            width: Thumbnail width in pixels
            height: Thumbnail height in pixels
            quality: JPEG quality for thumbnail
        
        Returns:
            Path to thumbnail, or None if failed
        """
        full_path = self.get_image_path(image_path)
        thumbnail_path = self.get_thumbnail_path(image_path)
        
        if not full_path.exists():
            logger.warning(f"Image not found for thumbnail generation: {image_path}")
            return None
        
        try:
            # Create thumbnail directory if it doesn't exist
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open and create thumbnail
            with Image.open(full_path) as img:
                # Create thumbnail maintaining aspect ratio
                img.thumbnail((width, height), Image.Resampling.LANCZOS)
                
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Save thumbnail
                img.save(thumbnail_path, 'JPEG', quality=quality, optimize=True)
                
                logger.debug(f"Generated thumbnail: {thumbnail_path}")
                return str(thumbnail_path.relative_to(self.images_path))
        
        except Exception as e:
            logger.error(f"Error generating thumbnail for {image_path}: {e}")
            return None
    
    def delete_orphaned_images(self) -> int:
        """
        Delete images that are not referenced in the database.
        
        Returns:
            Number of orphaned images deleted
        """
        deleted_count = 0
        
        logger.info("Starting orphaned image cleanup")
        
        # Walk through all image directories
        for year_month_dir in self.images_path.iterdir():
            if not year_month_dir.is_dir():
                continue
            
            for day_dir in year_month_dir.iterdir():
                if not day_dir.is_dir():
                    continue
                
                # Process images in this day directory
                for image_file in day_dir.glob('*.jpg'):
                    if image_file.name == 'thumbnails' or image_file.is_dir():
                        continue
                    
                    try:
                        # Get relative path for database check
                        relative_path = image_file.relative_to(self.images_path)
                        image_path_str = str(relative_path).replace('\\', '/')
                        
                        # Check if image is referenced
                        if not self.is_image_referenced(image_path_str):
                            # Delete thumbnail if it exists
                            thumbnail_path = self.get_thumbnail_path(image_path_str)
                            if thumbnail_path.exists():
                                thumbnail_path.unlink()
                            
                            # Delete bbox image if it exists
                            bbox_path = self.get_bbox_image_path(image_path_str)
                            if bbox_path.exists():
                                bbox_path.unlink()
                            
                            # Delete image
                            image_file.unlink()
                            deleted_count += 1
                            logger.info(f"Deleted orphaned image: {image_path_str}")
                    
                    except Exception as e:
                        logger.error(f"Error processing image {image_file}: {e}")
        
        logger.info(f"Orphaned image cleanup complete: deleted {deleted_count} images")
        return deleted_count
    
    def delete_image_files(self, image_paths: List[str]) -> int:
        """
        Delete image files and their thumbnails.
        
        Args:
            image_paths: List of relative image paths
        
        Returns:
            Number of images successfully deleted
        """
        deleted_count = 0
        
        for image_path in image_paths:
            try:
                full_path = self.get_image_path(image_path)
                thumbnail_path = self.get_thumbnail_path(image_path)
                bbox_path = self.get_bbox_image_path(image_path)
                
                # Delete thumbnail if exists
                if thumbnail_path.exists():
                    thumbnail_path.unlink()
                
                # Delete bbox image if exists
                if bbox_path.exists():
                    bbox_path.unlink()
                    logger.debug(f"Deleted bbox image: {bbox_path}")
                
                # Delete image if exists
                if full_path.exists():
                    full_path.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted image file: {image_path}")
                else:
                    logger.warning(f"Image file not found: {image_path}")
            
            except Exception as e:
                logger.error(f"Error deleting image {image_path}: {e}")
        
        return deleted_count
    
    def batch_generate_thumbnails(
        self,
        width: int = 300,
        height: int = 300,
        quality: int = 85
    ) -> int:
        """
        Generate thumbnails for all images that don't have them.
        
        Returns:
            Number of thumbnails generated
        """
        generated_count = 0
        
        logger.info("Starting batch thumbnail generation")
        
        # Walk through all image directories
        for year_month_dir in self.images_path.iterdir():
            if not year_month_dir.is_dir():
                continue
            
            for day_dir in year_month_dir.iterdir():
                if not day_dir.is_dir():
                    continue
                
                # Process images in this day directory
                for image_file in day_dir.glob('*.jpg'):
                    if image_file.name == 'thumbnails' or image_file.is_dir():
                        continue
                    
                    try:
                        # Get relative path
                        relative_path = image_file.relative_to(self.images_path)
                        image_path_str = str(relative_path).replace('\\', '/')
                        
                        # Check if thumbnail already exists
                        thumbnail_path = self.get_thumbnail_path(image_path_str)
                        if not thumbnail_path.exists():
                            # Generate thumbnail
                            result = self.generate_thumbnail(image_path_str, width, height, quality)
                            if result:
                                generated_count += 1
                    
                    except Exception as e:
                        logger.error(f"Error processing image {image_file}: {e}")
        
        logger.info(f"Batch thumbnail generation complete: generated {generated_count} thumbnails")
        return generated_count
    
    def get_bbox_image_path(self, image_path: str) -> Path:
        """Get full path to a bbox version of an image file."""
        image_file = Path(image_path)
        # Insert 'bbox' directory before filename
        bbox_path = image_file.parent / 'bbox' / image_file.name
        return self.images_path / bbox_path
    
    def draw_bounding_boxes(
        self,
        image_path: str,
        bounding_boxes: List[Dict[str, Any]],
        line_width: int = 3
    ) -> Optional[str]:
        """
        Draw bounding boxes on an image and save a bbox version.
        
        Args:
            image_path: Relative path to image (e.g., "2025-11/12/image.jpg")
            bounding_boxes: List of bounding box dicts with keys: x1, y1, x2, y2, confidence, class
            line_width: Width of bounding box lines in pixels
        
        Returns:
            Path to bbox image, or None if failed
        """
        full_path = self.get_image_path(image_path)
        bbox_path = self.get_bbox_image_path(image_path)
        
        if not full_path.exists():
            logger.warning(f"Image not found for bbox drawing: {image_path}")
            return None
        
        if not bounding_boxes:
            logger.debug(f"No bounding boxes to draw for {image_path}")
            return None
        
        try:
            # Create bbox directory if it doesn't exist
            bbox_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open image
            with Image.open(full_path) as img:
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Create a copy for drawing
                draw_img = img.copy()
                draw = ImageDraw.Draw(draw_img)
                
                # Color mapping for different classes
                color_map = {
                    'bird': (0, 255, 0),      # Green
                    'human': (255, 0, 0),     # Red
                    'squirrel': (0, 0, 255),  # Blue
                    'other': (255, 255, 0)    # Yellow
                }
                
                # Draw each bounding box
                for box in bounding_boxes:
                    x1 = float(box.get('x1', 0))
                    y1 = float(box.get('y1', 0))
                    x2 = float(box.get('x2', 0))
                    y2 = float(box.get('y2', 0))
                    confidence = box.get('confidence', 0.0)
                    class_name = box.get('class', 'other')
                    
                    # Get color for this class
                    color = color_map.get(class_name, color_map['other'])
                    
                    # Draw rectangle
                    draw.rectangle(
                        [(x1, y1), (x2, y2)],
                        outline=color,
                        width=line_width
                    )
                    
                    # Draw label with confidence
                    label = f"{class_name} {confidence:.2f}"
                    # Try to use a default font, fallback to basic if not available
                    font = None
                    font_size = max(12, int(img.width / 50))
                    
                    # Try common font paths
                    font_paths = [
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                        "/System/Library/Fonts/Helvetica.ttc",  # macOS
                        "/Windows/Fonts/arial.ttf",  # Windows
                    ]
                    
                    for font_path in font_paths:
                        try:
                            if os.path.exists(font_path):
                                font = ImageFont.truetype(font_path, font_size)
                                break
                        except:
                            continue
                    
                    # Fallback to default font
                    if font is None:
                        try:
                            font = ImageFont.load_default()
                        except:
                            font = None
                    
                    # Calculate text position (above the box, or inside if too close to top)
                    text_y = max(0, y1 - 20) if y1 > 20 else y1 + 5
                    
                    # Draw text background for better visibility
                    if font:
                        bbox = draw.textbbox((x1, text_y), label, font=font)
                        text_bg = [(bbox[0] - 2, bbox[1] - 2), (bbox[2] + 2, bbox[3] + 2)]
                        draw.rectangle(text_bg, fill=(0, 0, 0))
                        draw.text((x1, text_y), label, fill=color, font=font)
                    else:
                        # Fallback: just draw text without font
                        draw.text((x1, text_y), label, fill=color)
                
                # Save bbox image
                draw_img.save(bbox_path, 'JPEG', quality=95, optimize=True)
                
                logger.debug(f"Generated bbox image: {bbox_path}")
                return str(bbox_path.relative_to(self.images_path))
        
        except Exception as e:
            logger.error(f"Error drawing bounding boxes for {image_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

