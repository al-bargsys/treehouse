"""
Unit tests for ImageManager class.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from image_manager import ImageManager


class TestImageManager(unittest.TestCase):
    """Test cases for ImageManager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config = {
            'images_path': self.temp_dir
        }
        self.image_manager = ImageManager(self.config)
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_get_image_path(self):
        """Test getting full image path."""
        image_path = "2025-11/12/image.jpg"
        full_path = self.image_manager.get_image_path(image_path)
        expected = Path(self.temp_dir) / image_path
        self.assertEqual(full_path, expected)
    
    def test_get_thumbnail_path(self):
        """Test getting thumbnail path."""
        image_path = "2025-11/12/image.jpg"
        thumbnail_path = self.image_manager.get_thumbnail_path(image_path)
        expected = Path(self.temp_dir) / "2025-11/12/thumbnails/image.jpg"
        self.assertEqual(thumbnail_path, expected)
    
    def test_delete_image_files(self):
        """Test deleting image files."""
        # Create test directory structure
        test_dir = Path(self.temp_dir) / "2025-11" / "12"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        # Create test image
        image_file = test_dir / "test.jpg"
        image_file.write_bytes(b"fake image data")
        
        # Create thumbnail
        thumbnail_dir = test_dir / "thumbnails"
        thumbnail_dir.mkdir(exist_ok=True)
        thumbnail_file = thumbnail_dir / "test.jpg"
        thumbnail_file.write_bytes(b"fake thumbnail data")
        
        # Delete image
        image_path = "2025-11/12/test.jpg"
        deleted_count = self.image_manager.delete_image_files([image_path])
        
        self.assertEqual(deleted_count, 1)
        self.assertFalse(image_file.exists())
        self.assertFalse(thumbnail_file.exists())


if __name__ == '__main__':
    unittest.main()

