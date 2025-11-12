#!/bin/bash
# Check status of RTSP streaming setup

echo "=========================================="
echo "RTSP Stream Status Check"
echo "=========================================="
echo ""

# Check MediaMTX
echo "1. MediaMTX (RTSP Server):"
if pgrep -f "mediamtx" > /dev/null; then
    PID=$(pgrep -f "mediamtx")
    echo "   ✓ Running (PID: $PID)"
    if lsof -i :8554 > /dev/null 2>&1; then
        echo "   ✓ Port 8554 is listening"
    else
        echo "   ✗ Port 8554 is NOT listening"
    fi
else
    echo "   ✗ NOT running"
    echo "   Start with: ./scripts/start_rtsp_server.sh"
fi
echo ""

# Check FFmpeg stream
echo "2. FFmpeg Stream:"
FFMPEG_PID=$(pgrep -f "ffmpeg.*rtsp://.*webcam")
if [ -n "$FFMPEG_PID" ]; then
    echo "   ✓ Running (PID: $FFMPEG_PID)"
    # Check CPU usage
    CPU=$(ps -p $FFMPEG_PID -o %cpu= | tr -d ' ')
    echo "   CPU Usage: ${CPU}%"
    # Check if it's connected to RTSP server
    if lsof -p $FFMPEG_PID 2>/dev/null | grep -q "rtsp-alt"; then
        echo "   ✓ Connected to RTSP server"
    else
        echo "   ✗ NOT connected to RTSP server"
    fi
else
    echo "   ✗ NOT running"
    echo "   Start with: ./scripts/stream_webcam_to_rtsp.sh"
fi
echo ""

# Check camera
echo "3. Camera:"
if ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep -q "HD Pro Webcam"; then
    echo "   ✓ Camera detected (HD Pro Webcam C920)"
else
    echo "   ✗ Camera not detected or error accessing"
fi
echo ""

# Check Docker connection
echo "4. Docker Container Connection:"
if docker ps | grep -q "capture-service"; then
    echo "   ✓ Capture service container is running"
    # Test if container can reach RTSP
    if docker exec $(docker ps -q -f name=capture-service) 2>/dev/null ping -c 1 host.docker.internal > /dev/null 2>&1; then
        echo "   ✓ Container can reach host"
    else
        echo "   ⚠ Container connectivity to host unclear"
    fi
else
    echo "   ✗ Capture service container is NOT running"
fi
echo ""

echo "=========================================="
echo "Quick Fixes:"
echo "=========================================="
echo "If FFmpeg is not running or having issues:"
echo "  ./scripts/restart_rtsp_stream.sh"
echo ""
echo "If MediaMTX is not running:"
echo "  ./scripts/start_rtsp_server.sh"
echo ""
echo "If camera is not detected:"
echo "  - Unplug and replug the camera"
echo "  - Check System Settings > Privacy & Security > Camera"
echo ""

