# Testing Guide

This guide walks you through testing the bird monitoring system step by step.

## Prerequisites

1. **RTSP Server Running**: `./scripts/start_rtsp_server.sh`
2. **Webcam Streaming**: `./scripts/stream_webcam_to_rtsp.sh`
3. **Docker Running**: Docker Desktop should be active

## Step-by-Step Testing

### Step 1: Test RTSP Stream Access (✓ Already Done!)

Test that Docker containers can access the RTSP stream:

```bash
docker compose run --rm webcam-test-rtsp
```

**Expected Output**: Should capture 5 frames successfully from the RTSP stream.

### Step 2: Start Supporting Services

Start Redis (and optionally PostgreSQL) for the capture service:

```bash
# Start Redis only
docker compose up -d redis

# Or start both Redis and PostgreSQL
docker compose up -d redis postgres
```

Verify they're running:
```bash
docker compose ps
```

### Step 3: Test Capture Service

Start the capture service to test motion detection and Redis publishing:

```bash
docker compose up capture-service
```

**What to expect:**
- Service connects to RTSP stream
- Service connects to Redis
- Motion detection runs
- When motion is detected, images are saved and published to Redis

**Check logs for:**
- `✓ Connected to Redis`
- `✓ Camera opened: 1920x1080 @ 30.0 FPS`
- `Published to Redis queue 'images': ...`

### Step 4: Verify Images and Redis Queue

In another terminal, check:

**View captured images:**
```bash
ls -lh data/images/*/*/*.jpg | head -5
```

**Check Redis queue:**
```bash
docker compose exec redis redis-cli LLEN images
docker compose exec redis redis-cli LRANGE images 0 4
```

### Step 5: Test Full Stack (Optional)

Once capture service works, test the full pipeline:

```bash
# Start all services
docker compose up

# Or start in background
docker compose up -d
```

**Services to test:**
1. ✅ capture-service - Captures and publishes to Redis
2. ⏭️ detection-service - Consumes from Redis, runs ML inference
3. ⏭️ storage-service - Saves detections to PostgreSQL
4. ⏭️ notification-service - Sends Slack notifications
5. ⏭️ api-service - Serves web UI and API

## Troubleshooting

### RTSP Stream Not Accessible

**Error**: `Could not open RTSP stream`

**Solutions:**
- Verify RTSP server is running: `pgrep -f mediamtx`
- Verify FFmpeg stream is running: `pgrep -f "ffmpeg.*rtsp"`
- Test stream locally: `ffplay rtsp://localhost:8554/webcam`
- Check Docker can reach host: `docker compose run --rm webcam-test-rtsp`

### Redis Connection Failed

**Error**: `Failed to connect to Redis`

**Solutions:**
- Start Redis: `docker compose up -d redis`
- Check Redis is healthy: `docker compose ps`
- Test Redis connection: `docker compose exec redis redis-cli ping`

### No Images Captured

**Possible causes:**
- Motion detection too sensitive/insensitive
- No motion in camera view
- Images path not writable

**Solutions:**
- Check motion detection settings in docker-compose.yml
- Verify camera view has movement
- Check logs for motion detection messages
- Verify `data/images` directory exists and is writable

## Quick Test Commands

```bash
# Test RTSP access
docker compose run --rm webcam-test-rtsp

# Start capture service
docker compose up capture-service

# View logs
docker compose logs -f capture-service

# Check Redis queue
docker compose exec redis redis-cli LLEN images

# View captured images
ls -lh data/images/*/*/*.jpg

# Stop all services
docker compose down
```

## Next Steps

Once capture service is working:
1. Implement detection-service (ML inference)
2. Implement storage-service (PostgreSQL)
3. Implement notification-service (Slack)
4. Implement api-service (FastAPI + frontend)

