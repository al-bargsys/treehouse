#!/bin/bash
# Hardware-encoded single RTSP stream (macOS VideoToolbox)
# Purpose: Low CPU live stream with enough bitrate to avoid blockiness.
# Stream URL: rtsp://localhost:8554/webcam-live

set -e

RTSP_SERVER=${RTSP_SERVER:-localhost:8554}
LIVE_PATH=${LIVE_PATH:-webcam-live}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
RESOLUTION=${RESOLUTION:-1920x1080}
FPS=${FPS:-15}
# Bitrate defaults (tune as needed)
LIVE_BITRATE=${LIVE_BITRATE:-6000k}
LIVE_MAXRATE=${LIVE_MAXRATE:-7500k}
LIVE_BUFSIZE=${LIVE_BUFSIZE:-15000k}

LIVE_URL="rtsp://${RTSP_SERVER}/${LIVE_PATH}"

echo "=========================================="
echo "VideoToolbox Live Stream (webcam-live)"
echo "=========================================="
echo "Device     : ${CAMERA_DEVICE}"
echo "Resolution : ${RESOLUTION}"
echo "FPS        : ${FPS}"
echo "Bitrate    : ${LIVE_BITRATE} (max ${LIVE_MAXRATE}, buf ${LIVE_BUFSIZE})"
echo "RTSP URL   : ${LIVE_URL}"
echo ""

if ! command -v ffmpeg &>/dev/null; then
  echo "Error: ffmpeg not found (brew install ffmpeg)."
  exit 1
fi

if ! nc -z localhost 8554 2>/dev/null; then
  echo "Warning: RTSP server not running on :8554"
  echo "Start it with: ./scripts/start_rtsp_server.sh"
  read -p "Continue anyway? (y/N) " -n 1 -r; echo ""
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi

echo "Starting stream... (Ctrl+C to stop)"

ffmpeg -hide_banner -loglevel warning \
  -f avfoundation \
  -framerate ${FPS} \
  -video_size ${RESOLUTION} \
  -i "${CAMERA_DEVICE}:none" \
  -c:v h264_videotoolbox -realtime 1 \
  -b:v ${LIVE_BITRATE} -maxrate ${LIVE_MAXRATE} -bufsize ${LIVE_BUFSIZE} \
  -g $((FPS * 2)) -bf 0 -pix_fmt yuv420p \
  -f rtsp -rtsp_transport tcp -rtsp_flags prefer_tcp "${LIVE_URL}" 2>&1 | grep -v --line-buffered \
  "VBV underflow\|Non-monotonic DTS\|Invalid level prefix\|corrupted macroblock\|error while decoding\|co located POCs\|mmco: unref\|reference picture missing\|Missing reference picture\|illegal short term buffer\|bytestream" || true


