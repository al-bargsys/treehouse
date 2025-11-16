#!/usr/bin/env python3
"""
Train a YOLOv8 model for 3 classes: person (0), bird (1), squirrel (2).

Usage:
  python scripts/training/train_yolov8_three_class.py \\
    --data data/datasets/person_bird_squirrel/data.yaml \\
    --base yolov8s.pt --epochs 50 --imgsz 640 --batch 16

Output:
  Runs are stored under models/yolov8_person_bird_squirrel/ by default.
"""
import argparse
from pathlib import Path
from datetime import datetime

from ultralytics import YOLO
import torch


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 (person, bird, squirrel)")
    parser.add_argument("--data", type=str, required=True, help="Path to data.yaml")
    parser.add_argument("--base", type=str, default="yolov8s.pt", help="Base weights (e.g., yolov8n.pt, yolov8s.pt)")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Training image size")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--workers", type=int, default=8, help="Dataloader workers")
    parser.add_argument("--device", type=str, default=None, 
                        help="Device to use (auto-detects MPS/GPU/CPU if not set)")
    parser.add_argument("--project", type=str, default="models/yolov8_person_bird_squirrel",
                        help="Project directory for runs")
    parser.add_argument("--name", type=str, default=None, help="Run name (auto if not set)")
    args = parser.parse_args()
    
    # Auto-detect device if not specified
    if args.device is None:
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            args.device = 'mps'
            print("✓ Detected Apple Silicon GPU (MPS), using for training", flush=True)
        elif torch.cuda.is_available():
            args.device = 'cuda'
            print("✓ Detected CUDA GPU, using for training", flush=True)
        else:
            args.device = 'cpu'
            print("⚠ Using CPU (no GPU detected). Training will be slow.", flush=True)
    else:
        print(f"Using specified device: {args.device}", flush=True)

    run_name = args.name or datetime.now().strftime("%Y%m%d_%H%M%S")
    project_dir = Path(args.project)
    project_dir.mkdir(parents=True, exist_ok=True)

    print("Loading base model:", args.base, flush=True)
    model = YOLO(args.base)

    print("Starting training...", flush=True)
    print(f"Device: {args.device}", flush=True)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        device=args.device,
        project=str(project_dir),
        name=run_name,
        exist_ok=True
    )
    print("✓ Training complete.", flush=True)
    print(f"  Project: {project_dir}")
    print(f"  Run:     {run_name}")
    print(f"  Weights: {project_dir / run_name / 'weights' / 'best.pt'}")
    print("Set in docker-compose.yml:\n"
          "  MODEL_PATH=<absolute path to best.pt>\n"
          "  SQUIRREL_CLASS_ID=2  # names: [person, bird, squirrel]")


if __name__ == "__main__":
    main()


