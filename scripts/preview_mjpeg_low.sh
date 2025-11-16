#!/bin/bash
# Low-CPU preview stream for motion detection and live view
# - Produces HTTP MJPEG at low resolution and low FPS
# - Very easy to decode inside Docker (no hardware decode needed)
# URL: http://0.0.0.0:${HTTP_PORT}/preview.mjpg
#
# Recommended to run on host. Point capture service CAMERA_URL at:
#   http://host.docker.internal:${HTTP_PORT}/preview.mjpg

set -e

HTTP_PORT=${HTTP_PORT:-8082}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
# Capture at 1280x720 for better source quality, then scale down
CAPTURE_RES=${CAPTURE_RES:-1280x720}
PREVIEW_WIDTH=${PREVIEW_WIDTH:-640}
# Many macOS webcams accept 7.5 fps, not 7. Use fractional 7.5 by default.
PREVIEW_FPS=${PREVIEW_FPS:-7.5}
# MJPEG quality (lower number = better quality)
PREVIEW_Q=${PREVIEW_Q:-7}

echo "=========================================="
echo "Low-CPU Preview MJPEG"
echo "=========================================="
echo "Device     : ${CAMERA_DEVICE}"
echo "Input size : ${CAPTURE_RES}"
echo "Preview    : width=${PREVIEW_WIDTH}, fps=${PREVIEW_FPS}, q=${PREVIEW_Q}"
echo "URL        : http://0.0.0.0:${HTTP_PORT}/preview.mjpg"
echo ""

if ! command -v ffmpeg &>/dev/null; then
  echo "Error: ffmpeg not found (brew install ffmpeg)."
  exit 1
fi

if lsof -Pi :${HTTP_PORT} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
  echo "Port ${HTTP_PORT} already in use."
  exit 1
fi

# Use Python MJPEG server that properly binds to all interfaces
# FFmpeg's HTTP server only binds to localhost, so we need a proxy
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTTP_PORT=${HTTP_PORT} CAMERA_DEVICE=${CAMERA_DEVICE} PREVIEW_FPS=${PREVIEW_FPS} \
PREVIEW_WIDTH=${PREVIEW_WIDTH} CAPTURE_RES=${CAPTURE_RES} PREVIEW_Q=${PREVIEW_Q} \
python3 "${SCRIPT_DIR}/mjpeg_server.py" >/tmp/preview_mjpeg.log 2>&1 &
PREVIEW_PID=$!
echo $PREVIEW_PID > /tmp/preview_mjpeg.pid


