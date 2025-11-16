# Unified Capture Architecture

## Overview

The capture system has been redesigned to use a **unified host capture service** that runs directly on the host (not in Docker) to access the USB webcam. This eliminates the complexity of multiple host services (MJPEG server, snapshot server, RTSP server) and connection issues between Docker and host.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Host (macOS/Linux)                                      │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Host Capture Service                           │   │
│  │  - Direct USB webcam access                     │   │
│  │  - Motion detection                              │   │
│  │  - High-res image capture                        │   │
│  │  - HTTP endpoints (port 8080)                    │   │
│  │  - Publishes to Redis                            │   │
│  └──────────────┬───────────────────────────────────┘   │
│                 │                                        │
│                 │ Redis (localhost:6379)                  │
│                 │                                        │
└─────────────────┼────────────────────────────────────────┘
                   │
                   │ Docker Network
                   │
┌──────────────────▼──────────────────────────────────────┐
│  Docker Containers                                       │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Redis      │  │  Detection   │  │   Storage    │ │
│  │  (port 6379) │  │   Service    │  │   Service    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  API Service                                      │  │
│  │  - Connects to host capture via                   │  │
│  │    host.docker.internal:8080                      │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Benefits

1. **Simpler Architecture**: Single service instead of multiple (MJPEG server, snapshot server, RTSP server, proxy)
2. **More Reliable**: Direct USB access eliminates network streaming issues
3. **Better Performance**: No network overhead for camera access
4. **Easier to Debug**: Single process to monitor
5. **Still Containerized**: Detection, storage, and API services remain in Docker

## Components

### Host Capture Service

- **Location**: `services/capture/src/host_capture_service.py`
- **Purpose**: 
  - Direct USB webcam access
  - Motion detection using MOG2 background subtractor
  - High-resolution image capture
  - HTTP endpoints for live view
  - Publishes images to Redis queue

- **Configuration**: Set via environment variables (see `scripts/start_host_capture.sh`)

### Docker Services

- **Redis**: Exposed on port 6379 for host access
- **Detection Service**: Consumes images from Redis queue
- **Storage Service**: Consumes detections from Redis queue
- **API Service**: Connects to host capture service via `host.docker.internal:8080`

## Setup

### 1. Start Docker Services

```bash
docker-compose up -d
```

This starts:
- Redis (exposed on port 6379)
- Detection service
- Storage service
- API service (port 8000)

### 2. Start Host Capture Service

```bash
./scripts/start_host_capture.sh
```

Or run directly:

```bash
cd services/capture/src
python3 host_capture_service.py
```

### 3. Stop Host Capture Service

```bash
./scripts/stop_host_capture.sh
```

Or:

```bash
pkill -f host_capture_service.py
```

## Configuration

### Environment Variables

The host capture service can be configured via environment variables:

- `REDIS_HOST`: Redis host (default: `localhost`)
- `REDIS_PORT`: Redis port (default: `6379`)
- `CAMERA_DEVICE_ID`: USB camera device ID (default: `0`)
- `CAMERA_RESOLUTION`: Camera resolution (default: `1920,1080`)
- `CAMERA_FPS`: Target FPS (default: `15`)
- `MOTION_MIN_AREA`: Minimum motion area threshold (default: `3000`)
- `MOTION_COOLDOWN`: Seconds between captures (default: `5.0`)
- `CAPTURE_HTTP_PORT`: HTTP server port (default: `8080`)

See `scripts/start_host_capture.sh` for all available options.

## Troubleshooting

### Camera Not Opening

1. Check camera device ID:
   ```bash
   # macOS
   system_profiler SPCameraDataType
   
   # Linux
   ls /dev/video*
   ```

2. Try different device IDs (0, 1, 2, etc.)

3. Check if camera is in use by another application

### Redis Connection Failed

1. Ensure Docker services are running:
   ```bash
   docker-compose ps
   ```

2. Check Redis is accessible:
   ```bash
   nc -z localhost 6379
   ```

3. Verify Redis port is exposed in `docker-compose.yml`

### API Service Can't Connect to Capture Service

1. Check host capture service is running:
   ```bash
   ps aux | grep host_capture_service
   ```

2. Verify HTTP endpoint is accessible:
   ```bash
   curl http://localhost:8080/capture/health
   ```

3. Check Docker can reach host:
   ```bash
   docker exec bird-monitor-api curl http://host.docker.internal:8080/capture/health
   ```

## Migration from Old Architecture

The old architecture used:
- MJPEG server (port 8082)
- Snapshot server (port 8083)
- Camera proxy (port 8084)
- RTSP server (port 8554)

These services are **no longer needed** and can be stopped:

```bash
./scripts/stop_preview_and_snapshot.sh
# Stop any RTSP servers manually
```

The new unified service replaces all of these.

