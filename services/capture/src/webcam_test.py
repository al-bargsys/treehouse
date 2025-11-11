#!/usr/bin/env python3
"""
Simple webcam test script to validate camera access.
Tests both local and Docker container access.
"""
import cv2
import sys
import os

def test_webcam(device_id=0, num_frames=5):
    """Test webcam access by capturing a few frames."""
    print(f"Testing webcam access on device {device_id}...")
    print(f"OpenCV version: {cv2.__version__}")
    
    # Try to open the camera
    cap = cv2.VideoCapture(device_id)
    
    if not cap.isOpened():
        print(f"ERROR: Could not open camera device {device_id}")
        print("\nTroubleshooting tips:")
        print("1. Check if camera is connected")
        print("2. On macOS, Docker may need special setup")
        print("3. Try different device IDs (0, 1, 2, etc.)")
        return False
    
    print(f"✓ Camera opened successfully")
    
    # Get camera properties
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
        if ret:
            frames_captured += 1
            print(f"  Frame {i+1}: ✓ Captured ({frame.shape[1]}x{frame.shape[0]})")
        else:
            print(f"  Frame {i+1}: ✗ Failed to capture")
    
    cap.release()
    
    if frames_captured == num_frames:
        print(f"\n✓ SUCCESS: Captured all {num_frames} frames")
        return True
    else:
        print(f"\n✗ WARNING: Only captured {frames_captured}/{num_frames} frames")
        return False

def list_available_devices(max_devices=5):
    """Try to find available camera devices."""
    print("\nScanning for available camera devices...")
    available = []
    
    for i in range(max_devices):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                available.append(i)
                print(f"  Device {i}: ✓ Available")
            cap.release()
        else:
            print(f"  Device {i}: ✗ Not available")
    
    return available

if __name__ == "__main__":
    print("=" * 60)
    print("Webcam Access Test")
    print("=" * 60)
    
    # Check if running in Docker
    if os.path.exists("/.dockerenv"):
        print("Running inside Docker container")
    else:
        print("Running on host system")
    
    # List available devices
    available = list_available_devices()
    
    if not available:
        print("\nNo cameras found. Exiting.")
        sys.exit(1)
    
    # Test the first available device (or device 0)
    device_id = int(sys.argv[1]) if len(sys.argv) > 1 else available[0] if available else 0
    
    success = test_webcam(device_id)
    
    sys.exit(0 if success else 1)

