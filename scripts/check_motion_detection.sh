#!/bin/bash
# Script to check motion detection status

echo "=== Motion Detection Diagnostics ==="
echo ""

# Check if capture service is running
if ! docker ps | grep -q bird-monitor-capture; then
    echo "❌ Capture service is not running"
    exit 1
fi

echo "✓ Capture service is running"
echo ""

# Get recent logs
echo "=== Recent Status Messages ==="
docker logs bird-monitor-capture --tail 5 2>&1 | grep -E "(Status|Motion|warmup|Background)" | tail -5
echo ""

# Try to get status from HTTP endpoint (if accessible)
echo "=== HTTP Status Endpoint ==="
if curl -s http://localhost:8080/capture/status > /dev/null 2>&1; then
    curl -s http://localhost:8080/capture/status | python3 -m json.tool 2>/dev/null || echo "Could not parse JSON response"
else
    echo "⚠️  HTTP endpoint not accessible (service may be in Docker)"
    echo "   Try: docker exec bird-monitor-capture curl -s http://localhost:8080/capture/status"
fi
echo ""

# Check current configuration
echo "=== Current Motion Detection Settings ==="
docker exec bird-monitor-capture printenv | grep -E "MOTION_" | sort
echo ""

echo "=== Recommendations ==="
echo "If motion_area is consistently below motion_min_area:"
echo "  1. Lower MOTION_MIN_AREA (currently: check above)"
echo "  2. Lower MOTION_MOG2_VAR_THRESHOLD (currently: check above)"
echo "  3. Lower MOTION_BINARY_THRESHOLD (currently: check above)"
echo ""
echo "To enable verbose motion debugging, set MOTION_DEBUG=true and restart"
echo ""

