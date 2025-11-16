#!/usr/bin/env python3
"""
FastAPI application for bird monitoring system.
Provides REST API and serves frontend.
"""
import os
import sys
import logging
import requests
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, status, Body
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from database import Database
from models import (
    DetectionResponse, DetectionListResponse, StatsResponse, HealthResponse, WeatherResponse,
    BulkDeleteRequest, BulkDeleteByFilterRequest, BulkDeleteResponse,
    AnnotationRequest, AnnotationResponse, AnnotationListResponse
)
from shared.utils.weather import get_weather_for_zip
# Add parent directory to path to import ImageManager
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../storage/src'))
try:
    from image_manager import ImageManager
    IMAGE_MANAGER_AVAILABLE = True
except ImportError:
    IMAGE_MANAGER_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load configuration
def load_config():
    return {
        'postgres_host': os.getenv('POSTGRES_HOST', 'postgres'),
        'postgres_port': int(os.getenv('POSTGRES_PORT', 5432)),
        'postgres_db': os.getenv('POSTGRES_DB', 'birdmonitor'),
        'postgres_user': os.getenv('POSTGRES_USER', 'birdmonitor'),
        'postgres_password': os.getenv('POSTGRES_PASSWORD', 'changeme265'),
        'images_path': os.getenv('IMAGES_PATH', 'data/images'),
        'static_path': os.getenv('STATIC_PATH', 'static'),
        'capture_service_url': os.getenv('CAPTURE_SERVICE_URL', 'http://capture-service:8080'),
        'zip_code': os.getenv('ZIP_CODE', '34232'),
    }

config = load_config()
db = Database(config)
# Initialize ImageManager if available
image_manager = None
if IMAGE_MANAGER_AVAILABLE:
    try:
        image_manager = ImageManager(config)
        image_manager.set_database(db)
    except Exception as e:
        logger.warning(f"Could not initialize ImageManager: {e}")
        image_manager = None

# Initialize FastAPI app
app = FastAPI(
    title="Bird and Human Monitor API",
    description="REST API for bird and human monitoring system",
    version="1.0.0"
)

# Mount static files
static_path = Path(config['static_path'])
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Initialize database connection
@app.on_event("startup")
async def startup_event():
    logger.info("Starting API service...")
    if not db.connect():
        logger.error("Failed to connect to database")
    else:
        logger.info("✓ API service started")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down API service...")
    db.close()

# Health check endpoint
@app.get("/api/capture-status")
async def get_capture_status():
    """Get capture service status including low light detection."""
    capture_url = config['capture_service_url']
    
    try:
        response = requests.get(
            f"{capture_url}/capture/status",
            timeout=3
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error requesting capture status: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to get capture status: {str(e)}")

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    db_healthy = db.check_health()
    return HealthResponse(
        status="healthy" if db_healthy else "unhealthy",
        database="connected" if db_healthy else "disconnected",
        timestamp=datetime.now()
    )

# Get detections with pagination and filters
@app.get("/api/detections", response_model=DetectionListResponse)
async def get_detections(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    is_bird: Optional[bool] = Query(None, description="Filter by bird detection"),
    is_human: Optional[bool] = Query(None, description="Filter by human detection"),
    category: Optional[str] = Query(None, description="Filter by category (bird, human, both)"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter")
):
    """Get list of detections with pagination and filters."""
    detections, total = db.get_detections(
        page=page,
        page_size=page_size,
        is_bird=is_bird,
        is_human=is_human,
        category=category,
        start_date=start_date,
        end_date=end_date
    )
    
    total_pages = (total + page_size - 1) // page_size
    
    return DetectionListResponse(
        detections=[DetectionResponse(**d) for d in detections],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )

# Get single detection by ID
@app.get("/api/detections/{detection_id}", response_model=DetectionResponse)
async def get_detection(detection_id: int):
    """Get a single detection by ID."""
    detection = db.get_detection_by_id(detection_id)
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    return DetectionResponse(**detection)

# Delete detection by ID
@app.delete("/api/detections/{detection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection(detection_id: int):
    """Delete a detection by ID."""
    # First check if detection exists
    detection = db.get_detection_by_id(detection_id)
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    
    # Get image path before deletion
    image_path = detection.get('image_path')
    
    # Delete the detection
    success = db.delete_detection(detection_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete detection")
    
    # Delete image file if ImageManager is available
    if image_manager and image_path:
        try:
            image_manager.delete_image_files([image_path])
        except Exception as e:
            logger.warning(f"Could not delete image file {image_path}: {e}")
    
    return None

# Bulk delete detections by IDs
@app.delete("/api/detections/bulk", response_model=BulkDeleteResponse)
async def bulk_delete_detections(request: BulkDeleteRequest = Body(...)):
    """Delete multiple detections by their IDs."""
    if not request.detection_ids:
        raise HTTPException(status_code=400, detail="No detection IDs provided")
    
    # Get image paths before deletion
    image_paths = db.get_detection_image_paths(request.detection_ids)
    
    # Delete detections
    deleted_count = db.delete_detections_bulk(request.detection_ids)
    
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="No detections found to delete")
    
    # Delete image files if ImageManager is available
    if image_manager and image_paths:
        try:
            image_manager.delete_image_files(image_paths)
        except Exception as e:
            logger.warning(f"Could not delete some image files: {e}")
    
    return BulkDeleteResponse(
        deleted_count=deleted_count,
        message=f"Successfully deleted {deleted_count} detection(s)"
    )

# Bulk delete detections by filter
@app.delete("/api/detections/bulk-by-filter", response_model=BulkDeleteResponse)
async def bulk_delete_detections_by_filter(request: BulkDeleteByFilterRequest = Body(...)):
    """Delete detections matching filter criteria."""
    # Delete detections and get image paths
    deleted_count, image_paths = db.delete_detections_by_filter(
        category=request.category,
        start_date=request.start_date,
        end_date=request.end_date,
        is_bird=request.is_bird,
        is_human=request.is_human
    )
    
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="No detections found matching criteria")
    
    # Delete image files if ImageManager is available
    if image_manager and image_paths:
        try:
            image_manager.delete_image_files(image_paths)
        except Exception as e:
            logger.warning(f"Could not delete some image files: {e}")
    
    return BulkDeleteResponse(
        deleted_count=deleted_count,
        message=f"Successfully deleted {deleted_count} detection(s)"
    )

# Delete orphaned images
@app.delete("/api/images/orphaned", response_model=BulkDeleteResponse)
async def delete_orphaned_images():
    """Delete images that are not referenced in the database."""
    if not image_manager:
        raise HTTPException(status_code=503, detail="ImageManager not available")
    
    deleted_count = image_manager.delete_orphaned_images()
    
    return BulkDeleteResponse(
        deleted_count=deleted_count,
        message=f"Successfully deleted {deleted_count} orphaned image(s)"
    )

# Delete images by date range
@app.delete("/api/images/by-date-range", response_model=BulkDeleteResponse)
async def delete_images_by_date_range(
    start_date: datetime = Query(..., description="Start date"),
    end_date: datetime = Query(..., description="End date")
):
    """Delete images within a date range (also deletes associated detections)."""
    # First delete detections in date range
    deleted_count, image_paths = db.delete_detections_by_filter(
        start_date=start_date,
        end_date=end_date
    )
    
    # Delete image files if ImageManager is available
    if image_manager and image_paths:
        try:
            image_manager.delete_image_files(image_paths)
        except Exception as e:
            logger.warning(f"Could not delete some image files: {e}")
    
    return BulkDeleteResponse(
        deleted_count=deleted_count,
        message=f"Successfully deleted {deleted_count} detection(s) and associated images"
    )

# Get statistics
@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get statistics about detections."""
    stats = db.get_stats()
    return StatsResponse(**stats)

# Get current weather
@app.get("/api/weather", response_model=WeatherResponse)
async def get_current_weather():
    """Get current weather conditions."""
    zip_code = config.get('zip_code', '34232')
    try:
        weather_data = get_weather_for_zip(zip_code)
        if weather_data:
            return WeatherResponse(**weather_data)
        else:
            raise HTTPException(status_code=503, detail="Weather service unavailable")
    except Exception as e:
        logger.error(f"Error fetching current weather: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to fetch weather: {str(e)}")

# Get latest/live image from capture service
@app.get("/api/live")
async def get_live():
    """Get a live frame from the capture service."""
    capture_url = config['capture_service_url']
    
    try:
        # Request live frame from capture service
        # Increased timeout since capturing a frame can take a moment
        response = requests.get(
            f"{capture_url}/capture/live",
            timeout=15
        )
        
        if response.status_code == 503:
            raise HTTPException(status_code=503, detail="Capture service unavailable or camera not connected")
        
        response.raise_for_status()
        
        # Return the image directly as a streaming response
        return StreamingResponse(
            iter([response.content]),
            media_type='image/jpeg',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Error requesting live frame from capture service: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to get live frame: {str(e)}")

# Get high-quality snapshot from capture service
@app.get("/api/capture-snapshot")
async def get_capture_snapshot():
    """Fetch a high-quality snapshot via the capture service."""
    capture_url = config['capture_service_url']
    try:
        response = requests.get(
            f"{capture_url}/capture/snapshot",
            timeout=10
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Snapshot unavailable")
        return StreamingResponse(
            iter([response.content]),
            media_type='image/jpeg',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Error requesting snapshot from capture service: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to get snapshot: {str(e)}")

# Serve images
@app.get("/api/images/{image_path:path}")
async def get_image(image_path: str, size: Optional[str] = Query(None, description="Image size: 'thumb' for thumbnail")):
    """Serve images from the shared volume. Use ?size=thumb for thumbnails."""
    # If thumbnail requested, modify path
    if size == 'thumb':
        # Insert 'thumbnails' directory before filename
        path_parts = image_path.split('/')
        if len(path_parts) >= 3:  # YYYY-MM/DD/filename.jpg
            path_parts.insert(-1, 'thumbnails')
            image_path = '/'.join(path_parts)
    
    full_path = Path(config['images_path']) / image_path
    
    # Security: prevent directory traversal
    try:
        full_path.resolve().relative_to(Path(config['images_path']).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid image path")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(full_path)

# Serve thumbnails
@app.get("/api/images/{image_path:path}/thumbnail")
async def get_thumbnail(image_path: str):
    """Serve thumbnail for an image."""
    # Insert 'thumbnails' directory before filename
    path_parts = image_path.split('/')
    if len(path_parts) >= 3:  # YYYY-MM/DD/filename.jpg
        path_parts.insert(-1, 'thumbnails')
        thumbnail_path = '/'.join(path_parts)
    else:
        raise HTTPException(status_code=400, detail="Invalid image path format")
    
    full_path = Path(config['images_path']) / thumbnail_path
    
    # Security: prevent directory traversal
    try:
        full_path.resolve().relative_to(Path(config['images_path']).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid image path")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    
    return FileResponse(full_path)

@app.get("/api/videos/{video_path:path}")
async def get_video(video_path: str):
    """Serve video files from the shared volume."""
    full_path = Path(config['images_path']) / video_path
    
    # Security: prevent directory traversal
    try:
        full_path.resolve().relative_to(Path(config['images_path']).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid video path")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Determine content type based on file extension
    content_type = "video/mp4"
    if video_path.lower().endswith('.webm'):
        content_type = "video/webm"
    elif video_path.lower().endswith('.avi'):
        content_type = "video/x-msvideo"
    
    return FileResponse(full_path, media_type=content_type)

# Annotation endpoints
@app.post("/api/detections/{detection_id}/annotate", response_model=AnnotationResponse)
async def annotate_detection(detection_id: int, request: AnnotationRequest = Body(...)):
    """Create or update an annotation for a detection."""
    # First check if detection exists
    detection = db.get_detection_by_id(detection_id)
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    
    # Determine incorrect_class from detection if not provided
    incorrect_class = request.incorrect_class
    if not incorrect_class and not request.is_correct:
        # Infer from detection category
        if detection.get('category'):
            incorrect_class = detection['category']
        elif detection.get('is_bird'):
            incorrect_class = 'bird'
        elif detection.get('is_squirrel'):
            incorrect_class = 'squirrel'
        elif detection.get('is_human'):
            incorrect_class = 'human'
    
    # Create or update annotation
    annotation_id = db.create_or_update_annotation(
        detection_id=detection_id,
        is_correct=request.is_correct,
        correct_class=request.correct_class,
        incorrect_class=incorrect_class,
        notes=request.notes
    )
    
    if not annotation_id:
        raise HTTPException(status_code=500, detail="Failed to create/update annotation")
    
    # Get the annotation back
    annotation = db.get_annotation_by_detection_id(detection_id)
    if not annotation:
        raise HTTPException(status_code=500, detail="Failed to retrieve created annotation")
    
    return AnnotationResponse(**annotation)

@app.get("/api/detections/{detection_id}/annotation", response_model=AnnotationResponse)
async def get_detection_annotation(detection_id: int):
    """Get annotation for a detection."""
    # Check if detection exists
    detection = db.get_detection_by_id(detection_id)
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    
    annotation = db.get_annotation_by_detection_id(detection_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    
    return AnnotationResponse(**annotation)

@app.delete("/api/detections/{detection_id}/annotation", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection_annotation(detection_id: int):
    """Delete an annotation for a detection."""
    success = db.delete_annotation(detection_id)
    if not success:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return None

@app.get("/api/annotations", response_model=AnnotationListResponse)
async def get_annotations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    is_correct: Optional[bool] = Query(None, description="Filter by correctness")
):
    """Get list of annotations with pagination and filters."""
    annotations, total = db.get_annotations(
        page=page,
        page_size=page_size,
        is_correct=is_correct
    )
    
    total_pages = (total + page_size - 1) // page_size
    
    return AnnotationListResponse(
        annotations=[AnnotationResponse(**a) for a in annotations],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )

# Serve frontend
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the frontend HTML page."""
    index_path = Path(config['static_path']) / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    else:
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Bird Monitor</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                .endpoint { margin: 20px 0; padding: 10px; background: #f5f5f5; }
            </style>
        </head>
        <body>
            <h1>Bird Monitor API</h1>
            <p>API is running. Frontend coming soon.</p>
            <div class="endpoint">
                <strong>API Endpoints:</strong>
                <ul>
                    <li><a href="/api/health">GET /api/health</a> - Health check</li>
                    <li><a href="/api/detections">GET /api/detections</a> - List detections</li>
                    <li><a href="/api/stats">GET /api/stats</a> - Statistics</li>
                </ul>
            </div>
        </body>
        </html>
        """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

