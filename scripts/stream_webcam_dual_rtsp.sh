#!/bin/bash
# Dual RTSP streaming:
# - webcam-live: hardware-accelerated H.264 (VideoToolbox) for smooth, low CPU live view
# - webcam-hi:   high-quality, I-frame only H.264 for artifact-free still capture
#
# Requirements: macOS (avfoundation input), MediaMTX running locally on :8554
#
# Live stream (webcam-live):
#   - h264_videotoolbox, realtime, moderate bitrate
#   - goal: watchable preview with low CPU usage
# Hi-quality stream (webcam-hi):
#   - libx264, I-frame only (-g 1, -bf 0), higher bitrate
#   - goal: best single-frame quality, no ghosting

set -e

# Configuration
RTSP_SERVER=${RTSP_SERVER:-localhost:8554}
LIVE_PATH=${LIVE_PATH:-webcam-live}
HI_PATH=${HI_PATH:-webcam-hi}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
RESOLUTION=${RESOLUTION:-1920x1080}
FPS=${FPS:-15}
LIVE_URL="rtsp://${RTSP_SERVER}/${LIVE_PATH}"
HI_URL="rtsp://${RTSP_SERVER}/${HI_PATH}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Dual RTSP Stream (Live + Hi-quality)"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Camera Device : ${CAMERA_DEVICE}"
echo "  Resolution    : ${RESOLUTION}"
echo "  FPS           : ${FPS}"
echo "  Live URL      : ${LIVE_URL}"
echo "  Hi-Quality URL: ${HI_URL}"
echo ""

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
  echo "Error: FFmpeg is not installed (brew install ffmpeg)"
  exit 1
fi

# Basic RTSP server port check
if ! nc -z localhost 8554 2>/dev/null; then
  echo -e "${YELLOW}Warning: RTSP server doesn't appear to be running on port 8554${NC}"
  echo "Start it with: ./scripts/start_rtsp_server.sh"
  read -p "Continue anyway? (y/N) " -n 1 -r
  echo ""
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi

echo -e "${GREEN}Starting dual stream...${NC}"
echo "Press Ctrl+C to stop"
echo ""

# One input, split into two outputs
# Live branch (VideoToolbox):
#   ~2.5-3 Mbps, realtime, low CPU
# Hi branch (libx264, I-frame only):
#   8-10 Mbps, -g 1, -bf 0, stillimage tune
ffmpeg -hide_banner -loglevel warning \
  -f avfoundation \
  -framerate ${FPS} \
  -video_size ${RESOLUTION} \
  -i "${CAMERA_DEVICE}:none" \
  -filter_complex "[0:v]split=2[vL][vH]" \
  \
  -map "[vL]" -c:v h264_videotoolbox -realtime 1 -b:v 2500k -maxrate 3000k -bufsize 6000k \
  -g $((FPS * 2)) -bf 0 -pix_fmt yuv420p \
  -f rtsp -rtsp_transport tcp -rtsp_flags prefer_tcp "${LIVE_URL}" \
  \
  -map "[vH]" -c:v libx264 -preset veryfast -tune stillimage -profile:v high -level 4.2 -pix_fmt yuv420p \
  -b:v 8M -maxrate 10M -bufsize 20M \
  -g 1 -keyint_min 1 -bf 0 \
  -x264-params "keyint=1:min-keyint=1:scenecut=0:force-cfr=1:ref=1:me=hex:subme=4:trellis=0:fast-pskip=1" \
  -f rtsp -rtsp_transport tcp -rtsp_flags prefer_tcp "${HI_URL}" 2>&1 | grep -v --line-buffered \
    "VBV underflow\|Non-monotonic DTS\|Invalid level prefix\|corrupted macroblock\|error while decoding\|co located POCs\|mmco: unref\|reference picture missing\|Missing reference picture\|illegal short term buffer\|bytestream" || true


