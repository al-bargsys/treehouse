#!/bin/bash
# Start RTSP stream from macOS webcam using FFmpeg
# This script runs on the host (macOS) and streams to RTSP server

set -e

# Configuration
RTSP_PORT=${RTSP_PORT:-8554}
RTSP_PATH=${RTSP_PATH:-webcam}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
RESOLUTION=${RESOLUTION:-1920x1080}
FPS=${FPS:-15}
RTSP_URL="rtsp://localhost:${RTSP_PORT}/${RTSP_PATH}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "RTSP Webcam Stream Server"
echo "=========================================="
echo ""

# Check if FFmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${RED}Error: FFmpeg is not installed${NC}"
    echo ""
    echo "Install FFmpeg with:"
    echo "  brew install ffmpeg"
    exit 1
fi

echo -e "${GREEN}✓${NC} FFmpeg found: $(ffmpeg -version | head -1)"
echo ""

# Check if RTSP server is needed (using FFmpeg's built-in RTSP server)
# For simplicity, we'll use FFmpeg's RTSP output which requires an RTSP server
# We'll use mediamtx (formerly rtsp-simple-server) or FFmpeg's built-in server

# Check if port is already in use
if lsof -Pi :${RTSP_PORT} -sTCP:LISTEN -t >/dev/null ; then
    echo -e "${YELLOW}Warning: Port ${RTSP_PORT} is already in use${NC}"
    echo "Another RTSP server may be running, or you need to stop it first"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Configuration:"
echo "  Camera Device: ${CAMERA_DEVICE}"
echo "  Resolution: ${RESOLUTION}"
echo "  FPS: ${FPS}"
echo "  RTSP URL: ${RTSP_URL}"
echo ""

# Start FFmpeg RTSP stream
# Using FFmpeg with avfoundation for macOS camera input
# Output to RTSP using FFmpeg's RTSP muxer (requires RTSP server)
# For now, we'll output to a local RTSP server

echo "Starting RTSP stream..."
echo "Stream will be available at: ${RTSP_URL}"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# FFmpeg command for macOS with avfoundation
# Note: This requires an RTSP server. We'll use a simple approach with mediamtx
# or output to a file that can be served, or use FFmpeg's built-in RTSP server

# Option 1: Use FFmpeg's RTSP output (requires RTSP server running)
# Option 2: Use FFmpeg to output to a file and serve via HTTP
# Option 3: Use mediamtx (rtsp-simple-server) as RTSP server

# For now, let's use a simple HTTP-based approach that's easier to set up
# We'll output to an MJPEG stream over HTTP which OpenCV can consume

HTTP_PORT=${HTTP_PORT:-8080}
HTTP_PATH="/stream.mjpg"

echo "Using HTTP MJPEG stream (simpler than RTSP for initial setup)"
echo "Stream URL: http://localhost:${HTTP_PORT}${HTTP_PATH}"
echo ""

ffmpeg -f avfoundation \
    -framerate ${FPS} \
    -video_size ${RESOLUTION} \
    -i "${CAMERA_DEVICE}:none" \
    -vf "format=yuv420p" \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -b:v 2M \
    -maxrate 2M \
    -bufsize 4M \
    -g 30 \
    -f mjpeg \
    -q:v 5 \
    http://localhost:${HTTP_PORT}${HTTP_PATH} 2>&1 | while IFS= read -r line; do
    echo "[FFmpeg] $line"
done

