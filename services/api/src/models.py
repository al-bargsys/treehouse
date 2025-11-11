"""
Pydantic models for API responses.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class DetectionBase(BaseModel):
    id: int
    timestamp: datetime
    image_path: str
    is_bird: bool
    is_human: Optional[bool] = False
    category: Optional[str] = None
    confidence: Optional[float] = None
    species: Optional[str] = None
    bounding_boxes: Optional[List[Dict[str, Any]]] = None
    motion_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    detected_at: Optional[datetime] = None
    created_at: datetime
    weather: Optional[Dict[str, Any]] = None

class DetectionResponse(DetectionBase):
    """Detection response model."""
    pass

class DetectionListResponse(BaseModel):
    """List of detections with pagination."""
    detections: List[DetectionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

class StatsResponse(BaseModel):
    """Statistics response model."""
    total_detections: int
    birds_detected: int
    humans_detected: int
    recent_activity_24h: int
    recent_activity_7d: int
    average_confidence: Optional[float] = None

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    database: str
    timestamp: datetime

class WeatherResponse(BaseModel):
    """Weather response model."""
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    weather_code: Optional[int] = None
    weather_description: Optional[str] = None
    wind_speed: Optional[float] = None
    timestamp: Optional[str] = None

