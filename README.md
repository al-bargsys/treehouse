# Bird Feeder Monitoring System

A modular, self-hosted bird monitoring system that captures, analyzes, and catalogs bird visitors to a feeder using computer vision.

## Architecture

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- USB webcam connected to your system
- Python 3.11+ (for local development)

### RTSP Streaming Setup

The system uses RTSP (Real-Time Streaming Protocol) to stream the webcam from the host to Docker containers. This approach works on macOS, Linux, and Windows.

#### Quick Start

1. **Install prerequisites** (macOS):
   ```bash
   brew install ffmpeg mediamtx
   ```

2. **Start RTSP server** (in one terminal):
   ```bash
   ./scripts/start_rtsp_server.sh
   ```

3. **Stream webcam** (in another terminal):
   ```bash
   ./scripts/stream_webcam_to_rtsp.sh
   ```

4. **Start Docker services**:
   ```bash
   docker-compose up
   ```

The capture service will automatically connect to the RTSP stream.

#### Testing RTSP Stream

Test RTSP access from Docker container:

```bash
docker-compose run --rm --profile test webcam-test-rtsp
```

For detailed setup instructions, see [RTSP_SETUP.md](RTSP_SETUP.md).

## Configuration

### Performance Tuning

**Framerate (CPU Usage):**
- Default FPS: `15` (reduced from 30 to lower CPU usage)
- Configure via `FPS` environment variable in streaming scripts or `CAMERA_FPS` in docker-compose.yml
- Lower FPS = less CPU usage (encoding, decoding, and motion detection)
- 15 FPS is typically sufficient for bird monitoring and reduces CPU usage by ~50%
- To change: Set `FPS=10` or `FPS=20` in your streaming script, and update `CAMERA_FPS` in docker-compose.yml

### Motion Detection Sensitivity

The system is configured for moderate sensitivity by default to capture bird activity without excessive false positives. You can adjust these settings in `docker-compose.yml` or via environment variables:

**Motion Detection Settings:**
- `MOTION_MIN_AREA` (default: `3000`) - Minimum pixel area to trigger motion detection. Lower = more sensitive. For birds, try 2000-5000.
- `MOTION_COOLDOWN` (default: `5.0`) - Seconds between captures. Lower = more frequent captures.
- `MOTION_DELAY` (default: `0.5`) - Delay after motion detected before capturing. Lower = faster response.
- `MOTION_MOG2_VAR_THRESHOLD` (default: `35`) - MOG2 background subtractor sensitivity. Lower = more sensitive (range: 10-50).
- `MOTION_BINARY_THRESHOLD` (default: `175`) - Binary threshold for motion mask. Lower = more sensitive (range: 100-200).

**Detection Settings:**
- `CONFIDENCE_THRESHOLD` (default: `0.4`) - YOLOv8 detection confidence threshold. Lower = more detections (may include false positives).

**Notification Settings:**
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
├── services/
│   ├── capture/      # Camera capture service
│   ├── detection/    # ML detection service
│   ├── storage/      # Database storage service
│   ├── notification/ # Slack notifications
│   └── api/          # FastAPI web service
├── shared/           # Shared utilities
├── frontend/         # Web UI
├── models/           # ML model files
├── data/             # Persistent data
└── docs/             # Documentation
```

## License

See LICENSE file.

