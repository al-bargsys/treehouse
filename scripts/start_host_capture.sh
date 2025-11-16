#!/bin/bash
# Start the unified host capture service
# This service runs on the host (not in Docker) to directly access USB webcam
#
# Usage:
#   ./scripts/start_host_capture.sh
# Stop:
#   pkill -f host_capture_service.py
#   or Ctrl+C if running in foreground

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default configuration (can be overridden via environment variables)
export REDIS_HOST=${REDIS_HOST:-localhost}
export REDIS_PORT=${REDIS_PORT:-6379}
export REDIS_QUEUE=${REDIS_QUEUE:-images}
export CAMERA_DEVICE_ID=${CAMERA_DEVICE_ID:-0}
export IMAGES_PATH=${IMAGES_PATH:-${PROJECT_ROOT}/data/images}
export CAMERA_RESOLUTION=${CAMERA_RESOLUTION:-1920,1080}
export CAMERA_FPS=${CAMERA_FPS:-15}
export MOTION_MIN_AREA=${MOTION_MIN_AREA:-3000}
export MOTION_COOLDOWN=${MOTION_COOLDOWN:-5.0}
export MOTION_DELAY=${MOTION_DELAY:-1.5}
export CAPTURE_SAMPLES=${CAPTURE_SAMPLES:-5}
export CAPTURE_SAMPLE_INTERVAL=${CAPTURE_SAMPLE_INTERVAL:-0.1}
export JPEG_QUALITY=${JPEG_QUALITY:-95}
export MOTION_MOG2_VAR_THRESHOLD=${MOTION_MOG2_VAR_THRESHOLD:-35}
export MOTION_BINARY_THRESHOLD=${MOTION_BINARY_THRESHOLD:-175}
export MOTION_DEBUG=${MOTION_DEBUG:-false}
export CAPTURE_HTTP_PORT=${CAPTURE_HTTP_PORT:-8080}
export CAPTURE_HTTP_HOST=${CAPTURE_HTTP_HOST:-0.0.0.0}

# Check if Redis is accessible
echo "Checking Redis connection at ${REDIS_HOST}:${REDIS_PORT}..."
if ! nc -z ${REDIS_HOST} ${REDIS_PORT} 2>/dev/null; then
    echo "Warning: Cannot connect to Redis at ${REDIS_HOST}:${REDIS_PORT}"
    echo "Make sure Docker services are running: docker-compose up -d"
    echo "Continuing anyway (will retry on startup)..."
fi

# Check if Python virtual environment exists
if [ -d "${PROJECT_ROOT}/venv" ]; then
    echo "Activating virtual environment..."
    source "${PROJECT_ROOT}/venv/bin/activate"
elif [ -d "${PROJECT_ROOT}/.venv" ]; then
    echo "Activating virtual environment..."
    source "${PROJECT_ROOT}/.venv/bin/activate"
else
    echo "Warning: No virtual environment found."
    echo "Creating virtual environment and installing dependencies..."
    python3 -m venv "${PROJECT_ROOT}/venv"
    source "${PROJECT_ROOT}/venv/bin/activate"
    pip install --quiet --upgrade pip
    pip install --quiet -r "${PROJECT_ROOT}/services/capture/requirements.txt"
fi

# Check if required Python packages are installed
echo "Checking Python dependencies..."
python3 -c "import cv2, redis, flask, PIL" 2>/dev/null || {
    echo "Error: Required Python packages not found."
    echo "Please install: pip install opencv-python-headless redis flask Pillow"
    exit 1
}

# Check if camera device is available (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Checking camera device ${CAMERA_DEVICE_ID}..."
    # On macOS, we can't easily check camera availability without trying to open it
    echo "Note: Camera will be opened when service starts"
fi

# Change to project root
cd "${PROJECT_ROOT}"

# Start the capture service
echo ""
echo "Starting host capture service..."
echo "  Redis: ${REDIS_HOST}:${REDIS_PORT}"
echo "  Camera device: ${CAMERA_DEVICE_ID}"
echo "  HTTP server: http://${CAPTURE_HTTP_HOST}:${CAPTURE_HTTP_PORT}"
echo "  Images path: ${IMAGES_PATH}"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 "${PROJECT_ROOT}/services/capture/src/host_capture_service.py"

