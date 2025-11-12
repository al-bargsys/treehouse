#!/bin/bash
# Stream macOS webcam to RTSP server using FFmpeg with H.264 (lightweight preset)
# This script should be run after starting the RTSP server
#
# Uses H.264 with "veryfast" preset instead of "slow" - much lower CPU usage
# (typically 30-50% vs 200%+ for slow preset) while still providing good quality
# for still image capture.

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
echo "Webcam to RTSP Stream (H.264 - Lightweight)"
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
echo "  Codec: H.264 (veryfast preset - lightweight)"
echo ""
echo -e "${GREEN}Starting stream...${NC}"
echo "Press Ctrl+C to stop"
echo ""

# Stream to RTSP using FFmpeg with H.264 veryfast preset
# This is much lighter than "slow" preset while still providing good quality
# - preset veryfast: Fast encoding, ~30-50% CPU (vs 200%+ for slow)
# - tune zerolatency: Optimized for low latency streaming
# - Lower bitrate: 4M instead of 8M (still good quality for stills)
ffmpeg -hide_banner -loglevel warning \
    -f avfoundation \
    -framerate ${FPS} \
    -video_size ${RESOLUTION} \
    -i "${CAMERA_DEVICE}:none" \
    -c:v libx264 \
    -preset veryfast \
    -tune zerolatency \
    -profile:v high \
    -level 4.0 \
    -pix_fmt yuv420p \
    -b:v 4M \
    -maxrate 5M \
    -bufsize 10M \
    -g $((FPS * 2)) \
    -keyint_min $((FPS * 2)) \
    -f rtsp \
    -rtsp_transport tcp \
    -rtsp_flags prefer_tcp \
    "${RTSP_URL}" 2>&1 | grep -v --line-buffered \
        "VBV underflow\|Non-monotonic DTS\|Invalid level prefix\|corrupted macroblock\|error while decoding\|co located POCs\|mmco: unref\|reference picture missing\|Missing reference picture\|illegal short term buffer\|bytestream" || true

