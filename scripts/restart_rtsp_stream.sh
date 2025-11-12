#!/bin/bash
# Restart the RTSP stream (FFmpeg) to fix stream issues
# This will kill the existing FFmpeg process and restart it

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "Restart RTSP Stream"
echo "=========================================="
echo ""

# Find and kill existing FFmpeg processes streaming to RTSP
echo "Looking for existing FFmpeg RTSP stream processes..."
FFMPEG_PIDS=$(ps aux | grep -E "ffmpeg.*rtsp://.*webcam" | grep -v grep | awk '{print $2}')

if [ -z "$FFMPEG_PIDS" ]; then
    echo -e "${YELLOW}No FFmpeg RTSP stream process found${NC}"
else
    echo "Found FFmpeg processes: $FFMPEG_PIDS"
    for PID in $FFMPEG_PIDS; do
        echo "Killing FFmpeg process $PID..."
        kill $PID 2>/dev/null || true
    done
    echo "Waiting for processes to terminate..."
    sleep 2
    
    # Force kill if still running
    for PID in $FFMPEG_PIDS; do
        if kill -0 $PID 2>/dev/null; then
            echo "Force killing process $PID..."
            kill -9 $PID 2>/dev/null || true
        fi
    done
    sleep 1
    echo -e "${GREEN}✓ FFmpeg processes stopped${NC}"
fi

echo ""
echo "Restarting RTSP stream..."
echo ""

# Restart the stream
exec ./scripts/stream_webcam_to_rtsp.sh

