#!/usr/bin/env python3
"""
macOS-specific webcam test using AVFoundation backend.
This tests camera access on macOS host system (not in Docker).
"""
import cv2
import sys
import os

def test_webcam_macos(device_id=0, num_frames=5):
    """Test webcam access on macOS using AVFoundation backend."""
    print(f"Testing webcam access on macOS (device {device_id})...")
    print(f"OpenCV version: {cv2.__version__}")
    
    # On macOS, OpenCV uses AVFoundation backend
    # Try to open the camera
    print(f"\nAttempting to open camera with AVFoundation backend...")
    cap = cv2.VideoCapture(device_id, cv2.CAP_AVFOUNDATION)
    
    if not cap.isOpened():
        print(f"ERROR: Could not open camera device {device_id} with AVFoundation")
        print("Trying default backend...")
        cap = cv2.VideoCapture(device_id)
        
        if not cap.isOpened():
            print(f"ERROR: Could not open camera device {device_id} with default backend")
            return False
    
    print(f"✓ Camera opened successfully")
    
    # Get camera properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    backend = cap.getBackendName()
    
    print(f"  Backend: {backend}")
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
        print("\nNote: On macOS, Docker containers cannot access cameras directly.")
        print("The capture service should run on the host system for macOS deployments.")
        return True
    else:
        print(f"\n✗ WARNING: Only captured {frames_captured}/{num_frames} frames")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("macOS Webcam Access Test (Host System)")
    print("=" * 60)
    print("Running on macOS host (not in Docker)")
    print("")
    
    device_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    
    success = test_webcam_macos(device_id)
    
    sys.exit(0 if success else 1)

