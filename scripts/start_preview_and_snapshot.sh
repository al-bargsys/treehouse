#!/bin/bash
# Start both the low-CPU preview MJPEG server and the on-demand snapshot server
# - Preview (HTTP MJPEG): http://localhost:${HTTP_PORT}/preview.mjpg
# - Snapshot (single JPEG): http://localhost:${SNAPSHOT_PORT}/snapshot.jpg
#
# Usage:
#   HTTP_PORT=8082 SNAPSHOT_PORT=8083 PREVIEW_FPS=7.5 ./scripts/start_preview_and_snapshot.sh
# Stop:
#   ./scripts/stop_preview_and_snapshot.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HTTP_PORT=${HTTP_PORT:-8082}
SNAPSHOT_PORT=${SNAPSHOT_PORT:-8083}
PREVIEW_FPS=${PREVIEW_FPS:-7.5}
PREVIEW_WIDTH=${PREVIEW_WIDTH:-640}
CAPTURE_RES=${CAPTURE_RES:-1280x720}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
SNAPSHOT_RESOLUTION=${SNAPSHOT_RESOLUTION:-1920x1080}

echo "Starting preview (HTTP ${HTTP_PORT}) and snapshot (HTTP ${SNAPSHOT_PORT})..."

# Check ports
for P in ${HTTP_PORT} ${SNAPSHOT_PORT}; do
  if lsof -Pi :${P} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "Port ${P} is already in use. Stop the process or choose a different port."
    exit 1
  fi
done

# Start snapshot server
SNAPSHOT_PORT=${SNAPSHOT_PORT} SNAPSHOT_RESOLUTION=${SNAPSHOT_RESOLUTION} \
  python3 "${SCRIPT_DIR}/snapshot_server.py" >/tmp/snapshot_server.log 2>&1 &
SNAP_PID=$!

# Start preview server
HTTP_PORT=${HTTP_PORT} PREVIEW_FPS=${PREVIEW_FPS} PREVIEW_WIDTH=${PREVIEW_WIDTH} \
  CAPTURE_RES=${CAPTURE_RES} CAMERA_DEVICE=${CAMERA_DEVICE} \
  bash "${SCRIPT_DIR}/preview_mjpeg_low.sh" >/tmp/preview_mjpeg.log 2>&1 &
PREVIEW_PID=$!

# Wait a moment for preview to start, then start proxy for Docker access
sleep 2
PROXY_PORT=${PROXY_PORT:-8084}
python3 "${SCRIPT_DIR}/camera_proxy.py" >/tmp/camera_proxy.log 2>&1 &
PROXY_PID=$!

echo ${SNAP_PID} > /tmp/snapshot_server.pid
echo ${PREVIEW_PID} > /tmp/preview_mjpeg.pid
echo ${PROXY_PID} > /tmp/camera_proxy.pid

echo "Preview PID : ${PREVIEW_PID}  -> http://localhost:${HTTP_PORT}/preview.mjpg"
echo "Snapshot PID: ${SNAP_PID}     -> http://localhost:${SNAPSHOT_PORT}/snapshot.jpg"
echo "Proxy PID   : ${PROXY_PID}    -> http://localhost:${PROXY_PORT}/preview.mjpg (for Docker)"
echo "Logs: tail -f /tmp/preview_mjpeg.log /tmp/snapshot_server.log /tmp/camera_proxy.log"


