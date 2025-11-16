#!/bin/bash
# Stream macOS webcam to RTSP server using FFmpeg with H.264 I-frame only encoding
# This eliminates ghosting artifacts by using only I-frames (no B/P frames)
# Perfect for still image capture where each frame should be independent
#
# I-frame only encoding:
# - No inter-frame compression artifacts
# - No ghosting from B-frames
# - Each frame is independently decodable
# - Slightly larger file size but much cleaner still images

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
echo "Webcam to RTSP Stream (H.264 I-frame Only)"
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
echo "  Codec: H.264 (I-frame only - no ghosting artifacts)"
echo ""
echo -e "${GREEN}Starting stream...${NC}"
echo "Press Ctrl+C to stop"
echo ""

# Stream to RTSP using FFmpeg with H.264 I-frame only encoding
# Key settings to eliminate ghosting:
# - -g 1: Force I-frame every frame (no P/B frames)
# - -bf 0: No B-frames
# - -x264-params "keyint=1:min-keyint=1": Force I-frame every frame
# - preset veryfast: Lower CPU usage while maintaining quality
# - tune stillimage: Optimized for still image quality
ffmpeg -hide_banner -loglevel warning \
    -f avfoundation \
    -framerate ${FPS} \
    -video_size ${RESOLUTION} \
    -pixel_format uyvy422 \
    -i "${CAMERA_DEVICE}:none" \
    -c:v libx264 \
    -preset veryfast \
    -tune stillimage \
    -profile:v high \
    -level 4.2 \
    -pix_fmt yuv420p \
    -b:v 6M \
    -maxrate 7M \
    -bufsize 14M \
    -g 1 \
    -keyint_min 1 \
    -bf 0 \
    -x264-params "keyint=1:min-keyint=1:scenecut=0:force-cfr=1:ref=1:me=hex:subme=4:trellis=0:fast-pskip=1" \
    -fflags +genpts+igndts \
    -avoid_negative_ts make_zero \
    -vsync cfr \
    -r ${FPS} \
    -f rtsp \
    -rtsp_transport tcp \
    -rtsp_flags prefer_tcp \
    "${RTSP_URL}" 2>&1 | grep -v --line-buffered \
        "VBV underflow\|Non-monotonic DTS\|Invalid level prefix\|corrupted macroblock\|error while decoding\|co located POCs\|mmco: unref\|reference picture missing\|Missing reference picture\|illegal short term buffer\|bytestream" || true

