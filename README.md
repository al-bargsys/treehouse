# Bird Feeder Monitoring System

A modular, self-hosted bird monitoring system that captures, analyzes, and catalogs bird visitors to a feeder using computer vision.

## Architecture

The system uses a **unified capture architecture**:

- **Host Capture Service**: Runs directly on the host to access USB webcam, performs motion detection, captures high-res images, and publishes to Redis
- **Docker Services**: Redis (message queue), Detection (YOLOv8 inference), Storage (PostgreSQL), API (FastAPI web service)

The capture service communicates with Docker services via:
- Redis (for image queue) - accessible on `localhost:6379`
- HTTP endpoints (for live view) - accessible on `localhost:8080`

See [docs/unified_capture_architecture.md](docs/unified_capture_architecture.md) for detailed architecture documentation.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- USB webcam connected to your system
- Python 3.11+ (for host capture service)

### Unified Capture Architecture

The system uses a **unified host capture service** that runs directly on the host (not in Docker) to access the USB webcam. This eliminates the complexity of multiple streaming services and provides more reliable camera access.

#### Quick Start

1. **Start Docker services**:
   ```bash
   docker compose up -d
   ```

2. **Start the host capture service**:
   ```bash
   ./scripts/start_host_capture.sh
   ```

   The script will:
   - Check Redis connectivity
   - Create a virtual environment if needed
   - Install required Python dependencies
   - Start the capture service

3. **Verify everything is working**:
   ```bash
   # Check capture service status
   curl http://localhost:8080/capture/status | python3 -m json.tool
   
   # Check Docker services
   docker compose ps
   ```

4. **Access the web interface**:
   - Open http://localhost:8000 in your browser
   - View live camera feed and detections

#### Managing the Capture Service

**Start the capture service:**
```bash
./scripts/start_host_capture.sh
```

**Stop the capture service:**
```bash
./scripts/stop_host_capture.sh
```

**Check capture service status:**
```bash
curl http://localhost:8080/capture/status | python3 -m json.tool
```

**View capture service logs:**
If running in foreground, logs appear in the terminal. If running in background, check the process output or restart in foreground mode.

For detailed architecture information, see [docs/unified_capture_architecture.md](docs/unified_capture_architecture.md).

## Configuration

### Capture Service Configuration

The host capture service can be configured via environment variables. Set these before running `./scripts/start_host_capture.sh`:

**Camera Settings:**
- `CAMERA_DEVICE_ID` (default: `0`) - USB camera device ID
- `CAMERA_RESOLUTION` (default: `1920,1080`) - Camera resolution (width,height)
- `CAMERA_FPS` (default: `15`) - Target frames per second

**Redis Connection:**
- `REDIS_HOST` (default: `localhost`) - Redis host
- `REDIS_PORT` (default: `6379`) - Redis port
- `REDIS_QUEUE` (default: `images`) - Redis queue name for images

**HTTP Server:**
- `CAPTURE_HTTP_PORT` (default: `8080`) - HTTP server port for live view
- `CAPTURE_HTTP_HOST` (default: `0.0.0.0`) - HTTP server host

**Performance Tuning:**

**Framerate (CPU Usage):**
- Default FPS: `15` (reduced from 30 to lower CPU usage)
- Configure via `CAMERA_FPS` environment variable
- Lower FPS = less CPU usage (encoding, decoding, and motion detection)
- 15 FPS is typically sufficient for bird monitoring and reduces CPU usage by ~50%
- To change: Set `CAMERA_FPS=10` or `CAMERA_FPS=20` before starting the capture service

### Motion Detection Sensitivity

The system is configured for moderate sensitivity by default to capture bird activity without excessive false positives. You can adjust these settings via environment variables before starting the capture service:

**Motion Detection Settings:**
- `MOTION_MIN_AREA` (default: `3000`) - Minimum pixel area to trigger motion detection. Lower = more sensitive. For birds, try 2000-5000.
- `MOTION_COOLDOWN` (default: `5.0`) - Seconds between captures. Lower = more frequent captures.
- `MOTION_DELAY` (default: `1.5`) - Delay after motion detected before capturing. Lower = faster response.
- `MOTION_MOG2_VAR_THRESHOLD` (default: `35`) - MOG2 background subtractor sensitivity. Lower = more sensitive (range: 10-50).
- `MOTION_BINARY_THRESHOLD` (default: `175`) - Binary threshold for motion mask. Lower = more sensitive (range: 100-200).

**Example:**
```bash
export MOTION_MIN_AREA=2000
export MOTION_COOLDOWN=3.0
./scripts/start_host_capture.sh
```

**Detection Settings (configured in docker-compose.yml):**
- `CONFIDENCE_THRESHOLD` (default: `0.25`) - YOLOv8 detection confidence threshold. Lower = more detections (may include false positives).
- `BIRD_CONFIDENCE_THRESHOLD` (default: `0.1`) - Per-class threshold for birds
- `HUMAN_CONFIDENCE_THRESHOLD` (default: `0.5`) - Per-class threshold for humans
- `SQUIRREL_CONFIDENCE_THRESHOLD` (default: `0.1`) - Per-class threshold for squirrels

**Notification Settings (configured in docker-compose.yml):**
- `MIN_CONFIDENCE` (default: `0.5`) - Minimum confidence for notifications. Lower = more notifications.

**Tips for tuning:**
- Current defaults are set for moderate sensitivity - should capture birds without excessive false positives
- If you get too many captures, increase `MOTION_MIN_AREA` (try 5000-8000) and `MOTION_COOLDOWN` (try 8-10s)
- If you miss birds, decrease `MOTION_MIN_AREA` (try 2000-2500) and `MOTION_MOG2_VAR_THRESHOLD` (try 25-30)
- Adjust `CONFIDENCE_THRESHOLD` based on your validation results (0.3-0.5 range)

## Exposing to the Internet (Optional)

To expose the API service to the internet with basic authentication using ngrok:

```bash
ngrok http 8000 --basic-auth="username:password"
```

Replace `username` and `password` with your desired credentials. This will create a public HTTPS URL that requires basic authentication to access your bird monitoring API.

**Note:** This is an optional feature and not part of the docker-compose setup. Make sure you have ngrok installed and configured with your auth token.

### Development Status

Currently in Phase 1: Foundation & Docker Setup

## Project Structure

```
treehouse/
├── docker-compose.yml
├── scripts/
│   ├── start_host_capture.sh  # Start host capture service
│   └── stop_host_capture.sh   # Stop host capture service
├── services/
│   ├── capture/      # Host capture service (runs on host, not in Docker)
│   │   └── src/
│   │       └── host_capture_service.py  # Unified capture service
│   ├── detection/    # ML detection service (Docker)
│   ├── storage/      # Database storage service (Docker)
│   ├── notification/ # Slack notifications (Docker)
│   └── api/          # FastAPI web service (Docker)
├── shared/           # Shared utilities
├── frontend/         # Web UI
├── models/           # ML model files
├── data/             # Persistent data
└── docs/             # Documentation
```

## License

See LICENSE file.

