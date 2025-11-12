#!/bin/bash
# Stream macOS webcam via HTTP MJPEG (lightweight for still image capture)
# This creates a simple HTTP server that serves MJPEG stream
# OpenCV can consume this directly without needing RTSP server
#
# MJPEG over HTTP is simpler and more reliable than RTSP for still image capture
# - Much lower CPU usage than H.264 (typically 10-30% vs 200%+)
# - Each frame is independently encoded
# - High quality for still images
# - No RTSP server needed

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
HTTP_PORT=${HTTP_PORT:-8081}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
RESOLUTION=${RESOLUTION:-1920x1080}
FPS=${FPS:-15}
HTTP_URL="http://localhost:${HTTP_PORT}/stream.mjpg"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Webcam to HTTP MJPEG Stream (Lightweight)"
echo "=========================================="
echo ""

# Check if FFmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "Error: FFmpeg is not installed"
    echo "Install with: brew install ffmpeg"
    exit 1
fi

# Check if port is in use
if lsof -Pi :${HTTP_PORT} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}Warning: Port ${HTTP_PORT} is already in use${NC}"
    echo "Either stop the process using that port, or set HTTP_PORT to a different value"
    exit 1
fi

echo "Configuration:"
echo "  Camera Device: ${CAMERA_DEVICE}"
echo "  Resolution: ${RESOLUTION}"
echo "  FPS: ${FPS}"
echo "  HTTP URL: ${HTTP_URL}"
echo "  Codec: MJPEG (lightweight for still image capture)"
echo ""
echo "To use this stream, update CAMERA_URL in docker-compose.yml to:"
echo "  http://host.docker.internal:${HTTP_PORT}/stream.mjpg"
echo ""
echo -e "${GREEN}Starting stream...${NC}"
echo "Press Ctrl+C to stop"
echo ""

# Stream to HTTP using FFmpeg with MJPEG
# HTTP MJPEG is simpler and more reliable than RTSP for this use case
# - No RTSP server needed  
# - OpenCV can consume HTTP MJPEG directly
# - Lower CPU usage
#
# Note: FFmpeg can serve HTTP MJPEG directly using the http protocol
# This requires FFmpeg to be built with HTTP server support
# If this doesn't work, use stream_webcam_to_rtsp_lightweight.sh instead

ffmpeg -hide_banner -loglevel warning \
    -f avfoundation \
    -framerate ${FPS} \
    -video_size ${RESOLUTION} \
    -pixel_format uyvy422 \
    -i "${CAMERA_DEVICE}:none" \
    -vf "format=yuvj422p" \
    -c:v mjpeg \
    -q:v 3 \
    -r ${FPS} \
    -f mjpeg \
    -listen 1 \
    -timeout 5000000 \
    "http://0.0.0.0:${HTTP_PORT}/stream.mjpg" 2>&1 | grep -v --line-buffered \
        "deprecated pixel format\|Configuration of video device failed" || true

