#!/usr/bin/env python3
"""
Test RTSP stream access from Docker container.
Tests webcam access via RTSP stream.
"""
import cv2
import sys
import os

def test_rtsp_stream(rtsp_url, num_frames=5, timeout=10):
    """Test RTSP stream access by capturing frames."""
    print(f"Testing RTSP stream: {rtsp_url}")
    print(f"OpenCV version: {cv2.__version__}")
    print(f"Timeout: {timeout} seconds")
    
    # Open RTSP stream
    # Note: OpenCV's RTSP support can be finicky, may need GStreamer backend
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    
    if not cap.isOpened():
        print(f"ERROR: Could not open RTSP stream: {rtsp_url}")
        print("\nTroubleshooting tips:")
        print("1. Ensure RTSP server is running on host")
        print("2. Check RTSP URL is correct")
        print("3. Verify network connectivity (use host.docker.internal on macOS)")
        print("4. Check firewall settings")
        print("5. Try using GStreamer backend if available")
        return False
    
    print(f"✓ RTSP stream opened successfully")
    
    # Set timeout for frame reading
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
    
    # Get stream properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    print(f"  Resolution: {width}x{height}")
    print(f"  FPS: {fps}")
    
    # Try to capture frames
    print(f"\nAttempting to capture {num_frames} frames...")
    frames_captured = 0
    
    for i in range(num_frames):
        ret, frame = cap.read()
        if ret and frame is not None:
            frames_captured += 1
            print(f"  Frame {i+1}: ✓ Captured ({frame.shape[1]}x{frame.shape[0]})")
        else:
            print(f"  Frame {i+1}: ✗ Failed to capture")
            # Give it a moment for stream to stabilize
            import time
            time.sleep(0.5)
    
    cap.release()
    
    if frames_captured == num_frames:
        print(f"\n✓ SUCCESS: Captured all {num_frames} frames from RTSP stream")
        return True
    elif frames_captured > 0:
        print(f"\n⚠ PARTIAL SUCCESS: Captured {frames_captured}/{num_frames} frames")
        print("Stream may be slow to start or unstable")
        return True  # Consider partial success as acceptable
    else:
        print(f"\n✗ FAILED: Could not capture any frames")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("RTSP Stream Access Test")
    print("=" * 60)
    
    # Check if running in Docker
    if os.path.exists("/.dockerenv"):
        print("Running inside Docker container")
        # On macOS Docker, use host.docker.internal
        default_url = "rtsp://host.docker.internal:8554/webcam"
    else:
        print("Running on host system")
        default_url = "rtsp://localhost:8554/webcam"
    
    # Get RTSP URL from command line or use default
    rtsp_url = sys.argv[1] if len(sys.argv) > 1 else default_url
    
    print(f"Default URL: {default_url}")
    print("")
    
    success = test_rtsp_stream(rtsp_url)
    
    sys.exit(0 if success else 1)

