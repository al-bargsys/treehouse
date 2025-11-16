#!/bin/bash
# Coordinated single snapshot:
# - Stop preview ffmpeg on HTTP_PORT (if running)
# - Capture one high-quality frame from the camera
# - Restart preview ffmpeg with previous parameters
# - Write JPEG bytes to stdout

set -e

HTTP_PORT=${HTTP_PORT:-8082}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
SNAPSHOT_RESOLUTION=${SNAPSHOT_RESOLUTION:-1920x1080}
SNAPSHOT_QUALITY=${SNAPSHOT_QUALITY:-2}
PREVIEW_FPS=${PREVIEW_FPS:-7.5}
PREVIEW_WIDTH=${PREVIEW_WIDTH:-640}
CAPTURE_RES=${CAPTURE_RES:-1280x720}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to stop preview on port if present
stop_preview_if_running() {
  if lsof -Pi :${HTTP_PORT} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    PIDS=$(lsof -Pi :${HTTP_PORT} -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
      kill $PIDS 2>/dev/null || true
      sleep 0.2
    fi
  fi
}

# Capture one frame to stdout
capture_snapshot() {
  ffmpeg -hide_banner -loglevel error \
    -f avfoundation -framerate 30 -video_size ${SNAPSHOT_RESOLUTION} \
    -pixel_format uyvy422 \
    -i "${CAMERA_DEVICE}:none" \
    -frames:v 1 -q:v ${SNAPSHOT_QUALITY} \
    -f image2pipe - </dev/null
}

# Restart preview in background
start_preview() {
  HTTP_PORT=${HTTP_PORT} PREVIEW_FPS=${PREVIEW_FPS} PREVIEW_WIDTH=${PREVIEW_WIDTH} \
  CAPTURE_RES=${CAPTURE_RES} CAMERA_DEVICE=${CAMERA_DEVICE} \
    bash "${SCRIPT_DIR}/preview_mjpeg_low.sh" >/tmp/preview_mjpeg.log 2>&1 &
}

stop_preview_if_running

# Capture to temp then write to stdout to avoid partial pipes on failure
TMP_JPG=$(mktemp /tmp/snapXXXXXX.jpg)
if capture_snapshot > "${TMP_JPG}"; then
  start_preview
  cat "${TMP_JPG}"
  rm -f "${TMP_JPG}"
  exit 0
else
  start_preview
  rm -f "${TMP_JPG}"
  exit 1
fi


