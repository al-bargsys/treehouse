#!/bin/bash
# Stream macOS webcam to RTSP server using FFmpeg with MJPEG (lightweight for still image capture)
# This script should be run after starting the RTSP server
#
# MJPEG is much lighter than H.264 for still image capture because:
# - Each frame is independently encoded (no inter-frame compression)
# - Lower CPU usage (typically 10-30% vs 200%+ for H.264 slow preset)
# - Still provides high quality for still images
# - Easier to decode

set -e

# Configuration
RTSP_SERVER=${RTSP_SERVER:-localhost:8554}
RTSP_PATH=${RTSP_PATH:-webcam}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
RESOLUTION=${RESOLUTION:-1920x1080}
FPS=${FPS:-15}
RTSP_URL="rtsp://${RTSP_SERVER}/${RTSP_PATH}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Webcam to RTSP Stream (MJPEG - Lightweight)"
echo "=========================================="
echo ""

# Check if FFmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "Error: FFmpeg is not installed"
    echo "Install with: brew install ffmpeg"
    exit 1
fi

# Check if RTSP server is accessible
if ! nc -z localhost 8554 2>/dev/null; then
    echo -e "${YELLOW}Warning: RTSP server doesn't appear to be running on port 8554${NC}"
    echo "Start it with: ./scripts/start_rtsp_server.sh"
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
echo "  Codec: MJPEG (lightweight for still image capture)"
echo ""
echo -e "${GREEN}Starting stream...${NC}"
echo "Press Ctrl+C to stop"
echo ""

# Stream to RTSP using FFmpeg with MJPEG
# MJPEG is perfect for still image capture:
# - Each frame is independently encoded (no motion estimation)
# - Much lower CPU usage than H.264
# - High quality for still images
# - Quality setting (q:v) ranges from 2-31, lower = better quality
#
# Note: MJPEG over RTSP can be problematic. If this fails, try:
# - stream_webcam_to_rtsp_lightweight.sh (H.264 veryfast preset)
# - stream_webcam_to_http_mjpeg.sh (HTTP MJPEG stream)
#
# Convert from camera's native format (uyvy422) to yuvj422p for MJPEG
# Set pixel range correctly to avoid deprecation warnings
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
    -f rtsp \
    -rtsp_transport tcp \
    -rtsp_flags prefer_tcp \
    "${RTSP_URL}" 2>&1 | grep -v --line-buffered \
        "VBV underflow\|Non-monotonic DTS\|Invalid level prefix\|corrupted macroblock\|error while decoding\|co located POCs\|mmco: unref\|reference picture missing\|Missing reference picture\|illegal short term buffer\|bytestream\|Only 1x1 chroma blocks\|not enough frames to estimate rate\|deprecated pixel format\|Configuration of video device failed" || true

