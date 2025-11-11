# RTSP Streaming Setup Guide

This guide explains how to set up RTSP streaming for the bird monitoring system, allowing Docker containers to access the webcam via network stream.

## Overview

The system uses RTSP (Real-Time Streaming Protocol) to stream the webcam from the host to Docker containers. This approach:
- ✅ Works on macOS, Linux, and Windows
- ✅ Fully containerized (no host dependencies in containers)
- ✅ Portable and standard-based
- ✅ Allows multiple consumers of the stream

## Architecture

```
┌─────────────────┐
│  macOS Host     │
│                 │
│  ┌───────────┐  │
│  │  Webcam   │  │
│  └─────┬─────┘  │
│        │        │
│  ┌─────▼─────┐  │
│  │  FFmpeg   │──┼──► RTSP Stream
│  └───────────┘  │    (port 8554)
│                 │
│  ┌───────────┐  │
│  │ MediaMTX  │  │
│  │ (RTSP     │  │
│  │  Server)  │  │
│  └───────────┘  │
└─────────────────┘
        │
        │ rtsp://host.docker.internal:8554/webcam
        │
┌───────▼──────────────────────────────┐
│  Docker Container                     │
│                                       │
│  ┌─────────────────────────────────┐ │
│  │  capture-service                │ │
│  │  (OpenCV reads RTSP stream)     │ │
│  └─────────────────────────────────┘ │
└───────────────────────────────────────┘
```

## Prerequisites

### macOS

1. **Install FFmpeg**:
   ```bash
   brew install ffmpeg
   ```

2. **Install MediaMTX** (RTSP server):
   ```bash
   brew install mediamtx
   ```

### Linux

1. **Install FFmpeg**:
   ```bash
   sudo apt-get install ffmpeg  # Debian/Ubuntu
   # or
   sudo yum install ffmpeg      # RHEL/CentOS
   ```

2. **Install MediaMTX**:
   ```bash
   # Download from https://github.com/bluenviron/mediamtx/releases
   # Or use package manager if available
   ```

## Setup Steps

### Step 1: Start RTSP Server

On the host machine, start the RTSP server:

```bash
./scripts/start_rtsp_server.sh
```

This will:
- Start MediaMTX on port 8554 (RTSP) and 9997 (HTTP)
- Create a config file at `~/.mediamtx.yml` if it doesn't exist
- Listen for incoming RTSP streams

**Keep this terminal open** - the server must remain running.

### Step 2: Stream Webcam to RTSP

In a **new terminal**, start streaming the webcam:

```bash
./scripts/stream_webcam_to_rtsp.sh
```

This will:
- Capture video from your webcam using FFmpeg
- Stream it to the RTSP server at `rtsp://localhost:8554/webcam`
- Use optimal settings for low latency

**Keep this terminal open** - the stream must remain active.

### Step 3: Start Docker Services

In a **third terminal**, start the Docker services:

```bash
docker-compose up
```

The `capture-service` will automatically connect to the RTSP stream at:
- **macOS**: `rtsp://host.docker.internal:8554/webcam`
- **Linux**: `rtsp://<host-ip>:8554/webcam` (update CAMERA_URL in .env)

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# RTSP Configuration
CAMERA_URL=rtsp://host.docker.internal:8554/webcam  # macOS
# CAMERA_URL=rtsp://192.168.1.100:8554/webcam      # Linux (use host IP)

# Camera Settings
CAMERA_RESOLUTION=1920,1080
CAMERA_FPS=30

# Motion Detection
MOTION_THRESHOLD=25
MOTION_MIN_AREA=500
MOTION_COOLDOWN=2.0

# Database
POSTGRES_PASSWORD=your_secure_password
```

### Customizing Stream Settings

Edit `scripts/stream_webcam_to_rtsp.sh` to adjust:
- Resolution: `RESOLUTION=1280x720`
- FPS: `FPS=15`
- Bitrate: Modify `-b:v 2M` in FFmpeg command

## Testing

### Test RTSP Stream from Host

```bash
# Using FFplay (comes with FFmpeg)
ffplay rtsp://localhost:8554/webcam

# Or using VLC
vlc rtsp://localhost:8554/webcam
```

### Test from Docker Container

```bash
# Test RTSP access
docker-compose run --rm webcam-test-rtsp

# Or manually
docker-compose run --rm capture-service python src/webcam_test_rtsp.py rtsp://host.docker.internal:8554/webcam
```

## Troubleshooting

### RTSP Server Won't Start

**Issue**: Port 8554 already in use
```bash
# Check what's using the port
lsof -i :8554

# Kill the process or change port in script
```

### FFmpeg Can't Find Camera

**Issue**: Camera device not found
```bash
# List available cameras (macOS)
system_profiler SPCameraDataType

# Try different device ID
CAMERA_DEVICE=1 ./scripts/stream_webcam_to_rtsp.sh
```

### Container Can't Connect to RTSP

**Issue**: Connection refused from container
- **macOS**: Ensure using `host.docker.internal` not `localhost`
- **Linux**: Use host machine's IP address, not `localhost`
- Check firewall settings
- Verify RTSP server is running: `nc -z localhost 8554`

### Stream is Laggy or Dropping Frames

**Solutions**:
- Reduce resolution: `RESOLUTION=1280x720`
- Reduce FPS: `FPS=15`
- Increase bitrate buffer: Modify `-bufsize` in FFmpeg command
- Check network bandwidth

### OpenCV Can't Open RTSP Stream

**Issue**: `cv2.VideoCapture()` fails to open RTSP URL
- Ensure OpenCV was built with FFmpeg support (opencv-python-headless includes it)
- Try adding timeout: `cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)`
- Check RTSP URL is correct and accessible

## Alternative: HTTP MJPEG Stream

If RTSP causes issues, you can use HTTP MJPEG streaming instead:

```bash
# Stream to HTTP (simpler, but less efficient)
ffmpeg -f avfoundation -i "0:none" -vf "format=yuv420p" -c:v libx264 -f mjpeg http://localhost:8080/stream.mjpg
```

Then use `http://host.docker.internal:8080/stream.mjpg` as CAMERA_URL.

## Production Considerations

1. **Auto-restart**: Use `systemd` or `launchd` to auto-start RTSP server and stream
2. **Monitoring**: Monitor RTSP server and stream processes
3. **Security**: Consider RTSP authentication for production
4. **Performance**: Tune FFmpeg settings for your hardware
5. **Backup**: Have fallback mechanism if stream fails

## Next Steps

Once RTSP streaming is working:
1. ✅ Verify capture-service receives frames
2. ✅ Test motion detection
3. ✅ Verify images are saved and published to Redis
4. ✅ Test end-to-end pipeline

