#!/usr/bin/env python3
"""
FastAPI application for bird monitoring system.
Provides REST API and serves frontend.
"""
import os
import logging
import requests
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from database import Database
from models import DetectionResponse, DetectionListResponse, StatsResponse, HealthResponse, WeatherResponse
from shared.utils.weather import get_weather_for_zip

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
    
    # Delete the detection
    success = db.delete_detection(detection_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete detection")
    
    return None

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
        response = requests.get(
            f"{capture_url}/capture/live",
            timeout=5
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

# Serve images
@app.get("/api/images/{image_path:path}")
async def get_image(image_path: str):
    """Serve images from the shared volume."""
    full_path = Path(config['images_path']) / image_path
    
    # Security: prevent directory traversal
    try:
        full_path.resolve().relative_to(Path(config['images_path']).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid image path")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(full_path)

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

