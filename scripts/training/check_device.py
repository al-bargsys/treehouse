#!/usr/bin/env python3
"""Quick script to check what device PyTorch will use for training."""
import torch

print("PyTorch Device Check")
print("=" * 50)

# Check MPS (Apple Silicon)
if hasattr(torch.backends, 'mps'):
    mps_available = torch.backends.mps.is_available()
    mps_built = torch.backends.mps.is_built()
    print(f"MPS (Apple Silicon GPU):")
    print(f"  Available: {mps_available}")
    print(f"  Built:     {mps_built}")
    if mps_available:
        print("  ✓ MPS can be used for training")
    else:
        print("  ✗ MPS not available (may need macOS 12.3+ and Apple Silicon)")
else:
    print("MPS (Apple Silicon GPU): Not available in this PyTorch build")

# Check CUDA
cuda_available = torch.cuda.is_available()
print(f"\nCUDA (NVIDIA GPU):")
print(f"  Available: {cuda_available}")
if cuda_available:
    print(f"  Device count: {torch.cuda.device_count()}")
    print(f"  Device name:  {torch.cuda.get_device_name(0)}")
    print("  ✓ CUDA can be used for training")
else:
    print("  ✗ CUDA not available")

# Recommended device
print(f"\nRecommended device for training:")
if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print("  → mps (Apple Silicon GPU)")
elif cuda_available:
    print("  → cuda (NVIDIA GPU)")
else:
    print("  → cpu (CPU only - will be slow)")

print("\nTo check if your current training run is using MPS:")
print("  grep 'device:' models/yolov8_person_bird_squirrel/*/args.yaml | tail -1")

