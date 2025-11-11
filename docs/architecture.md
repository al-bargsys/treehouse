# Bird Feeder Monitoring System - Architecture Document

## System Overview

A modular, self-hosted bird monitoring system that captures, analyzes, and catalogs bird visitors to a feeder using computer vision and provides real-time notifications.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Docker Compose Stack                               │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Host System (macOS/Linux)                                             │  │
│  │  ┌────────────────┐      ┌──────────────┐      ┌──────────────┐      │  │
│  │  │  USB Webcam    │─────▶│   FFmpeg     │─────▶│  MediaMTX    │      │  │
│  │  │  (1080p)       │      │  (Streamer)  │      │  (RTSP       │      │  │
│  │  └────────────────┘      └──────────────┘      │   Server)    │      │  │
│  │                                                 └──────┬───────┘      │  │
│  └────────────────────────────────────────────────────────┼───────────────┘  │
│                                                            │ RTSP Stream      │
│                                                            │ (port 8554)      │
│  ┌────────────────────────────────────────────────────────▼───────────────┐  │
│  │  Docker Network                                                         │  │
│  │                                                                          │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  capture-service (Container)                                      │  │  │
│  │  │  - Consumes RTSP stream via OpenCV                                │  │  │
│  │  │  - Motion detection                                                │  │  │
│  │  │  - Publishes to Redis queue                                        │  │  │
│  │  └───────┬──────────────────────────────────────────────────────────┘  │  │
│          │ (Redis: images queue)                                            │
│          │                                                                   │
│  ┌───────▼───────────────────────────────────────────────────────────────┐  │
│  │  detection-service (Container)                                         │  │
│  │  - Consumes images from Redis                                          │  │
│  │  - YOLO/MobileNet inference                                            │  │
│  │  - Publishes results to Redis                                          │  │
│  └───────┬───────────────────────────────────────────────────────────────┘  │
│          │ (Redis: detections queue)                                        │
│          │                                                                   │
│  ┌───────┴───────────────────────────────────────────────────────────────┐  │
│  │  storage-service (Container)                                           │  │
│  │  - Consumes detections from Redis                                      │  │
│  │  - Writes to PostgreSQL                                                │  │
│  │  - Manages image files on shared volume                                │  │
│  └───────┬───────────────────────────────────────────────────────────────┘  │
│          │ (PostgreSQL connection)                                          │
│          │                                                                   │
│  ┌───────▼───────────────────────────────────────────────────────────────┐  │
│  │  notification-service (Container)                                      │  │
│  │  - Consumes detections from Redis                                      │  │
│  │  - Slack webhook integration                                           │  │
│  │  - Rate limiting & cooldown                                            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  api-service (Container)                                               │  │
│  │  - FastAPI REST API                                                    │  │
│  │  - Serves static frontend files                                        │  │
│  │  - Queries PostgreSQL                                                  │  │
│  │  - Serves images from shared volume                                    │  │
│  └───────┬───────────────────────────────────────────────────────────────┘  │
│          │ (HTTP:8000)                                                      │
│          │                                                                   │
│  ┌───────▼───────────────────────────────────────────────────────────────┐  │
│  │  Web UI (Static Files)                                                 │  │
│  │  - HTML/CSS/JS                                                         │  │
│  │  - Real-time updates via API                                           │  │
│  │  - Image gallery                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Supporting Services                                                   │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │  │
│  │  │   Redis      │  │  PostgreSQL  │  │   (Optional) │                │  │
│  │  │   (Queue)    │  │  (Database)  │  │   Nginx      │                │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Shared Volumes                                                        │  │
│  │  - ./data/images (image storage)                                       │  │
│  │  - ./models (ML model files)                                           │  │
│  │  - ./config (configuration files)                                      │  │
│  │  - ./logs (log files)                                                  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Container Specifications

### 1. capture-service (Container)

**Purpose**: Continuously monitor webcam for motion and capture frames

**Key Components**:
- RTSP stream consumer using OpenCV (reads from network stream)
- Motion detection algorithm (background subtraction or frame differencing)
- Image preprocessing pipeline
- Configurable sensitivity and cooldown periods
- Redis client for publishing images

**Inputs**:
- RTSP video stream from host (e.g., `rtsp://host.docker.internal:8554/webcam`)
- Configuration parameters (from environment variables)

**Outputs**:
- Motion-triggered image frames published to Redis queue
- Images saved to shared volume
- Metadata (timestamp, motion score) included in queue messages

**Container Configuration**:
- **No device passthrough required** - uses network stream
- Mounts: `./data/images`, `./config`, `./logs`
- Environment: 
  - `CAMERA_URL`: RTSP stream URL (e.g., `rtsp://host.docker.internal:8554/webcam`)
  - Redis connection details
  - Motion detection parameters
- Network: Connects to Redis service and RTSP stream on host

**RTSP Streaming Architecture**:
- **Host System**: Runs FFmpeg to capture webcam and stream to RTSP server (MediaMTX)
- **RTSP Server**: MediaMTX runs on host, serves stream on port 8554
- **Container**: Connects to RTSP stream via network (works on macOS, Linux, Windows)
- **Benefits**: Fully portable, no device passthrough needed, standard protocol

**Technologies**:
- OpenCV (cv2) with FFmpeg backend for RTSP support
- NumPy for image processing
- Redis client (redis-py)

---

### 2. detection-service (Container)

**Purpose**: Identify birds in captured images using computer vision

**Key Components**:
- Pre-trained model loader (YOLO or MobileNet-SSD)
- Inference engine
- Bird classification logic
- Confidence threshold filtering
- Redis consumer for images queue
- Redis publisher for detection results

**Inputs**:
- Image frames from Redis queue (published by capture-service)
- Pre-trained model weights (from shared volume)

**Outputs**:
- Detection results (bird/not-bird) published to Redis queue
- Bounding boxes and confidence scores
- Species classification (optional enhancement)
- Results consumed by storage-service and notification-service

**Container Configuration**:
- Mounts: `./models`, `./config`, `./data/images`
- Environment: Redis connection details, model path, confidence threshold
- Network: Connects to Redis service
- Resource limits: May need GPU access or higher CPU/memory for inference

**Technologies**:
- PyTorch or TensorFlow/Keras
- YOLO v5/v8 or MobileNet-SSD
- Ultralytics library (for YOLO)
- Redis client (redis-py)

**Model Options**:
1. **YOLOv8** - Fast, accurate, easy to use
2. **MobileNet-SSD** - Lightweight alternative
3. Fine-tune on bird-specific dataset later

---

### 3. storage-service (Container)

**Purpose**: Persist detection results and images

**Key Components**:
- Database manager (PostgreSQL client)
- File system manager for images
- Redis consumer for detection results
- Data retention policies
- Query interface (used by api-service)

**Inputs**:
- Detection results from Redis queue (published by detection-service)
- Images already saved to shared volume by capture-service

**Outputs**:
- Database records in PostgreSQL
- Image file organization on shared volume

**Container Configuration**:
- Mounts: `./data/images`, `./config`
- Environment: PostgreSQL connection details, Redis connection details
- Network: Connects to PostgreSQL and Redis services
- Depends on: postgres service

**Database Schema**:
```sql
CREATE TABLE detections (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    image_path TEXT NOT NULL,
    is_bird BOOLEAN NOT NULL,
    confidence REAL,
    species TEXT,
    motion_score REAL,
    metadata JSONB
);

CREATE INDEX idx_timestamp ON detections(timestamp);
CREATE INDEX idx_is_bird ON detections(is_bird);
```

**File Structure** (on shared volume):
```
./data/images/
  /2025-11
    /11
      /20250111_143022_001.jpg
      /20250111_143045_002.jpg
```

**Technologies**:
- PostgreSQL (psycopg2 or asyncpg)
- Python pathlib
- Redis client (redis-py)

---

### 4. notification-service (Container)

**Purpose**: Send alerts when birds are detected

**Key Components**:
- Slack webhook integration
- Redis consumer for detection results
- Alert queue/buffer to prevent spam
- Message formatting
- Rate limiting

**Inputs**:
- Detection results from Redis queue (published by detection-service)
- Images from shared volume (for attachments)

**Outputs**:
- Slack notifications via webhook

**Container Configuration**:
- Mounts: `./data/images`, `./config`
- Environment: Slack webhook URL, Redis connection details, cooldown settings
- Network: Connects to Redis service
- Optional: Can be disabled via environment variable

**Features**:
- Configurable cooldown periods
- Rich message formatting with image attachments
- Error handling and retry logic
- Filters detections by confidence threshold

**Configuration**:
```python
{
    "slack_webhook_url": "https://hooks.slack.com/...",
    "min_confidence": 0.7,
    "cooldown_seconds": 300,
    "include_image": true
}
```

**Technologies**:
- requests library
- Redis client (redis-py)
- asyncio for async processing

---

### 5. api-service (Container)

**Purpose**: Provide REST API for web UI and external integrations

**Key Components**:
- FastAPI application
- PostgreSQL client for queries
- Static file server for frontend
- Image file server from shared volume

**Inputs**:
- Database queries to PostgreSQL
- Image files from shared volume
- Static frontend files from volume mount

**Outputs**:
- REST API responses
- Served static files (HTML/CSS/JS)
- Image files

**Container Configuration**:
- Mounts: `./frontend`, `./data/images`, `./config`
- Environment: PostgreSQL connection details, API host/port
- Network: Connects to PostgreSQL service, exposes port 8000
- Depends on: postgres service

**Endpoints**:
```
GET  /api/detections              - List recent detections
GET  /api/detections/{id}         - Get specific detection
GET  /api/detections/latest       - Get most recent bird
GET  /api/detections/random       - Get random bird detection
GET  /api/stats                   - Get summary statistics
GET  /api/images/{filename}       - Serve image files
GET  /api/health                  - System health check
POST /api/config                  - Update configuration
GET  /                            - Serve frontend index.html
GET  /gallery                     - Serve gallery page
GET  /stats                       - Serve stats page
```

**Technologies**:
- FastAPI (recommended) or Flask
- Uvicorn ASGI server
- Pydantic for data validation
- PostgreSQL client (asyncpg or psycopg2)

---

### 6. Web UI (Static Files)

**Purpose**: User interface for viewing and browsing bird detections

**Deployment**:
- Served as static files by api-service container
- Mounted as volume: `./frontend` → container `/app/frontend`
- No separate container needed

**Features**:
- Live feed status indicator
- Latest bird detection display
- Gallery view with pagination
- Random bird button
- Statistics dashboard
- Basic filtering (date range, confidence)

**Pages**:
- `/` - Home page with latest detection
- `/gallery` - Browse all detections
- `/stats` - Statistics and charts
- `/settings` - Configuration UI (optional)

**Technologies**:
- Vanilla HTML/CSS/JavaScript
- Or lightweight framework (Alpine.js, htmx)
- No build process required
- Fetches data from api-service REST endpoints

### 7. postgres (Container)

**Purpose**: Database service for storing detection metadata

**Container Configuration**:
- Official PostgreSQL image
- Persistent volume for database data
- Environment: Database name, user, password
- Network: Internal Docker network
- Exposes: Port 5432 (internal only)

**Technologies**:
- PostgreSQL 15+

---

### 8. redis (Container)

**Purpose**: Message queue for asynchronous communication between services

**Container Configuration**:
- Official Redis image
- Persistent volume for queue data (optional)
- Network: Internal Docker network
- Exposes: Port 6379 (internal only)

**Queue Channels**:
- `images` - Images from capture-service to detection-service
- `detections` - Detection results from detection-service to storage-service and notification-service

**Technologies**:
- Redis 7+

---

## Data Flow

1. **Host System** (RTSP Streaming):
   - FFmpeg captures video from USB webcam
   - Streams to RTSP server (MediaMTX) on port 8554
   - RTSP server makes stream available at `rtsp://host:8554/webcam`

2. **Capture Service** (continuous):
   - Connects to RTSP stream via network (OpenCV with FFmpeg backend)
   - Grabs frames from RTSP stream
   - Detect motion
   - If motion detected:
     - Save frame to shared volume (`./data/images`)
     - Publish image path + metadata to Redis queue (`images`)

3. **Detection Service** (continuous):
   - Consume images from Redis queue (`images`)
   - Load image from shared volume
   - Run ML inference (YOLO/MobileNet)
   - If bird detected (confidence > threshold):
     - Publish detection result to Redis queue (`detections`)
     - Include: image path, confidence, bounding boxes, metadata

4. **Storage Service** (event-driven):
   - Consume detection results from Redis queue (`detections`)
   - Write detection record to PostgreSQL
   - Organize image files on shared volume (if needed)
   - Update statistics

5. **Notification Service** (event-driven):
   - Consume detection results from Redis queue (`detections`)
   - Check cooldown timer (in-memory or Redis-based)
   - If cooldown expired:
     - Load image from shared volume
     - Format Slack message with image attachment
     - Send webhook request to Slack

6. **API Service** (always running):
   - Serve REST API endpoints
   - Query PostgreSQL for detection data
   - Serve static frontend files from volume
   - Serve image files from shared volume
   - Handle health checks and status endpoints

---

## RTSP Streaming Setup

**Overview**: The system uses RTSP (Real-Time Streaming Protocol) to stream the webcam from the host to Docker containers. This approach provides:
- ✅ Full portability across macOS, Linux, and Windows
- ✅ No device passthrough required
- ✅ Standard protocol (RTSP)
- ✅ Multiple consumers can access the same stream

**Host Components** (run on host system):
1. **MediaMTX** (RTSP Server): Receives and serves RTSP streams
2. **FFmpeg**: Captures webcam and streams to RTSP server

**Setup Steps**:
1. Install MediaMTX and FFmpeg on host
2. Start RTSP server: `./scripts/start_rtsp_server.sh`
3. Stream webcam: `./scripts/stream_webcam_to_rtsp.sh`
4. Start Docker services: `docker-compose up`

See [RTSP_SETUP.md](../RTSP_SETUP.md) for detailed setup instructions.

---

## Docker Compose Configuration

**File**: `docker-compose.yml`

```yaml
version: '3.8'

services:
  # Message Queue
  redis:
    image: redis:7-alpine
    container_name: bird-monitor-redis
    volumes:
      - redis-data:/data
    networks:
      - bird-monitor-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Database
  postgres:
    image: postgres:15-alpine
    container_name: bird-monitor-db
    environment:
      POSTGRES_DB: birdmonitor
      POSTGRES_USER: birdmonitor
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - bird-monitor-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U birdmonitor"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Capture Service (consumes RTSP stream)
  capture-service:
    build:
      context: ./services/capture
      dockerfile: Dockerfile
    container_name: bird-monitor-capture
    # No device passthrough needed - uses RTSP stream
    volumes:
      - ./data/images:/app/data/images
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_QUEUE=images
      # RTSP URL - on macOS Docker, use host.docker.internal
      # On Linux, use host IP or hostname
      - CAMERA_URL=rtsp://host.docker.internal:8554/webcam
      - IMAGES_PATH=/app/data/images
      - CAMERA_RESOLUTION=1920,1080
      - CAMERA_FPS=30
      - MOTION_THRESHOLD=25
      - MOTION_MIN_AREA=500
      - MOTION_COOLDOWN=2.0
    networks:
      - bird-monitor-network
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  # Detection Service
  detection-service:
    build:
      context: ./services/detection
      dockerfile: Dockerfile
    container_name: bird-monitor-detection
    volumes:
      - ./data/images:/app/data/images
      - ./config:/app/config
      - ./models:/app/models
      - ./logs:/app/logs
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - MODEL_PATH=/app/models/yolov8n.pt
      - CONFIDENCE_THRESHOLD=0.6
      - DEVICE=cpu  # or cuda for GPU support
    networks:
      - bird-monitor-network
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G

  # Storage Service
  storage-service:
    build:
      context: ./services/storage
      dockerfile: Dockerfile
    container_name: bird-monitor-storage
    volumes:
      - ./data/images:/app/data/images
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - POSTGRES_DB=birdmonitor
      - POSTGRES_USER=birdmonitor
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-changeme}
      - MAX_IMAGES=10000
    networks:
      - bird-monitor-network
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  # Notification Service
  notification-service:
    build:
      context: ./services/notification
      dockerfile: Dockerfile
    container_name: bird-monitor-notification
    volumes:
      - ./data/images:/app/data/images
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-}
      - NOTIFICATION_ENABLED=${NOTIFICATION_ENABLED:-true}
      - COOLDOWN_SECONDS=300
      - MIN_CONFIDENCE=0.7
      - INCLUDE_IMAGE=true
    networks:
      - bird-monitor-network
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  # API Service
  api-service:
    build:
      context: ./services/api
      dockerfile: Dockerfile
    container_name: bird-monitor-api
    ports:
      - "8000:8000"
    volumes:
      - ./frontend:/app/frontend
      - ./data/images:/app/data/images
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - POSTGRES_DB=birdmonitor
      - POSTGRES_USER=birdmonitor
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-changeme}
      - API_HOST=0.0.0.0
      - API_PORT=8000
      - DEBUG=false
    networks:
      - bird-monitor-network
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres-data:
  redis-data:

networks:
  bird-monitor-network:
    driver: bridge
```

**Environment File**: `.env`

```bash
# Database
POSTGRES_PASSWORD=your_secure_password_here

# Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
NOTIFICATION_ENABLED=true
```

---

## Configuration Management

**Configuration Strategy**: Hybrid approach using environment variables and optional config files

**Environment Variables** (primary):
- Service-specific settings via Docker Compose environment section
- Sensitive data (passwords, API keys) via `.env` file
- Runtime configuration changes without rebuilding images

**Config Files** (optional, for complex settings):
- `config.yaml` mounted as volume for advanced configuration
- Can override environment variables if needed
- Useful for development and testing

**Configuration Priority**:
1. Environment variables (highest priority)
2. Config file values
3. Default values in code

---

## Deployment Architecture

### Docker Compose Management

Services are managed by Docker Compose with automatic restart policies:

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f [service-name]

# Stop all services
docker-compose down

# Restart a specific service
docker-compose restart [service-name]

# Scale detection service (if needed)
docker-compose up -d --scale detection-service=2
```

**Service Dependencies**:
- `redis` and `postgres` start first (health checks)
- `capture-service` and `detection-service` depend on `redis`
- `storage-service` depends on `postgres` and `redis`
- `notification-service` depends on `redis`
- `api-service` depends on `postgres`

**Health Checks**:
- All services include health check endpoints
- Docker Compose waits for dependencies to be healthy
- Automatic restart on failure (unless-stopped policy)

### Directory Structure

```
bird-monitor/
├── docker-compose.yml          # Main compose configuration
├── .env                        # Environment variables (gitignored)
├── .dockerignore
├── README.md
│
├── services/                   # Service-specific code
│   ├── capture/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   └── capture_service.py
│   │   └── entrypoint.sh
│   │
│   ├── detection/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   └── detection_service.py
│   │   └── entrypoint.sh
│   │
│   ├── storage/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   └── storage_service.py
│   │   └── entrypoint.sh
│   │
│   ├── notification/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   └── notification_service.py
│   │   └── entrypoint.sh
│   │
│   └── api/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── src/
│       │   ├── __init__.py
│       │   ├── api_service.py
│       │   └── routes/
│       └── entrypoint.sh
│
├── shared/                     # Shared utilities
│   └── utils/
│       ├── __init__.py
│       ├── config.py
│       ├── logger.py
│       └── redis_client.py
│
├── frontend/                   # Static web UI
│   ├── index.html
│   ├── gallery.html
│   ├── stats.html
│   ├── css/
│   └── js/
│
├── models/                     # ML model files
│   └── yolov8n.pt
│
├── config/                     # Configuration files (optional)
│   └── config.yaml
│
├── data/                       # Persistent data (volumes)
│   └── images/                 # Captured images
│       └── [year-month]/
│           └── [day]/
│
└── logs/                       # Log files
    └── [service-name].log
```

**Volume Mounts**:
- `./data/images` → Shared image storage across services
- `./models` → ML model files (read-only for detection-service)
- `./config` → Configuration files (optional)
- `./frontend` → Static web files (read-only for api-service)
- `./logs` → Log files from all services
- Docker volumes for `postgres-data` and `redis-data`

---

## Technology Stack Summary

- **Containerization**: Docker, Docker Compose
- **Language**: Python 3.10+
- **Computer Vision**: OpenCV, Ultralytics YOLO
- **Web Framework**: FastAPI
- **Database**: PostgreSQL 15+
- **Message Queue**: Redis 7+
- **Frontend**: HTML/CSS/Vanilla JS
- **HTTP Client**: requests
- **Configuration**: Environment variables, PyYAML (optional)
- **Process Management**: Docker Compose

---

## Container Communication Patterns

### Inter-Service Communication

**Redis Message Queues**:
- **images queue**: Capture → Detection
  - Message format: `{image_path, timestamp, motion_score, metadata}`
  - Pattern: Producer-consumer (one-to-one)
  
- **detections queue**: Detection → Storage & Notification
  - Message format: `{image_path, is_bird, confidence, bounding_boxes, species, metadata}`
  - Pattern: Pub-sub (one-to-many) - both storage and notification services consume

**Direct Database Access**:
- Storage service writes to PostgreSQL
- API service reads from PostgreSQL
- No direct communication needed between these services

**HTTP/REST**:
- API service exposes REST endpoints
- Frontend makes HTTP requests to API service
- External integrations can use REST API

**Shared Volumes**:
- Images stored on shared volume accessible by all services
- Models on shared volume (read-only for detection service)
- Logs written to shared volume for centralized logging

### Network Architecture

**Docker Network**: `bird-monitor-network` (bridge)
- All services on same network for service discovery
- Services communicate via service names (e.g., `redis`, `postgres`)
- Only `api-service` exposes port to host (8000)
- Internal services not accessible from host (security)

**Service Discovery**:
- Docker Compose provides DNS resolution
- Services reference each other by service name
- Example: `REDIS_HOST=redis` (not `localhost`)

---

## Development Phases

### Phase 1: Foundation & Docker Setup (Week 1)
- Set up Docker Compose structure
- Create base Dockerfiles for each service
- Set up PostgreSQL and Redis containers
- Implement RTSP streaming from host to container
- Implement capture service with motion detection (consumes RTSP stream)
- Test RTSP stream access from Docker container
- Basic Redis integration for image queue

### Phase 2: Detection Pipeline (Week 1-2)
- Integrate YOLO model in detection service
- Implement Redis consumer/producer pattern
- Database schema and storage service
- Test end-to-end: capture → detection → storage
- Performance testing with containerized services

### Phase 3: Notifications & API (Week 2)
- Slack integration in notification service
- Alert queue and rate limiting (Redis-based)
- FastAPI backend service
- Basic frontend for viewing detections
- Test notification flow through containers

### Phase 4: Web Interface (Week 2-3)
- Complete frontend pages (gallery, stats)
- API endpoints for all frontend needs
- Real-time updates via polling/SSE
- Image serving from shared volume

### Phase 5: Polish & Production (Week 3-4)
- Health checks for all services
- Error handling and logging
- Configuration management
- Performance optimization
- Docker image optimization
- Documentation and deployment guides

---

## Performance Considerations

### Service-Level Performance

- **Motion detection FPS**: Target 10-15 FPS (capture-service)
- **Detection inference**: 1-2 seconds per image (CPU), 0.1-0.5s (GPU)
- **Database**: PostgreSQL handles millions of records efficiently
- **Image storage**: 500KB per image × 10k images ≈ 5GB
- **Redis queue**: Handles thousands of messages per second

### Container Resource Allocation

**Memory Requirements**:
- `capture-service`: ~200MB
- `detection-service`: ~1-2GB (model loading + inference)
- `storage-service`: ~100MB
- `notification-service`: ~100MB
- `api-service`: ~200MB
- `postgres`: ~200MB (base) + data
- `redis`: ~50MB (base) + queue data
- **Total**: ~2-3GB typical usage

**CPU Requirements**:
- `detection-service`: High CPU usage during inference
- `capture-service`: Moderate CPU for motion detection
- Other services: Low CPU usage
- Consider CPU limits for detection-service to prevent resource starvation

**Scaling Options**:
- Scale `detection-service` horizontally (multiple instances) for higher throughput
- Use GPU support for detection-service if available
- Redis and PostgreSQL can handle multiple consumers efficiently

### Optimization Strategies

1. **Model Optimization**: Use quantized or smaller YOLO models for faster inference
2. **Queue Batching**: Batch process images in detection-service
3. **Database Indexing**: Ensure proper indexes on frequently queried columns
4. **Image Compression**: Compress images before storage if needed
5. **Caching**: Use Redis for caching frequently accessed API data
6. **Volume Performance**: Use local volumes (not network mounts) for image storage

---

## Future Enhancements

1. Species identification (fine-tuned model)
2. Activity timeline visualization
3. Multi-camera support
4. Video clip recording on detection
5. Bird count tracking
6. Weather correlation
7. Email notifications
8. Mobile app
9. Export data to CSV/JSON
10. Integration with eBird or similar platforms