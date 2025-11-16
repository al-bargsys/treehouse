#!/bin/bash
# Stop the unified host capture service

echo "Stopping host capture service..."

# Find and kill the process
pkill -f "host_capture_service.py" && echo "✓ Host capture service stopped" || echo "No running host capture service found"

