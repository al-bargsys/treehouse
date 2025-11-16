#!/usr/bin/env python3
"""
Download a YOLO-format squirrel dataset from Roboflow Universe.

Requirements:
  pip install -r scripts/training/requirements.txt
  export ROBOFLOW_API_KEY=...   # from your Roboflow account

Usage:
  python scripts/training/fetch_roboflow_universe.py \
    --workspace squirrel-iest3 \
    --project squirrel \
    --version 1 \
    --format yolov8 \
    --out-dir data/external/squirrel_roboflow

Notes:
 - You can find workspace/project/version on the Roboflow Universe dataset page.
 - Formats: yolov5, yolov7, yolov8 etc. Prefer 'yolov8'.
 - This script just wraps roboflow's SDK download and relocates the dataset.
"""
import argparse
import os
import shutil
from pathlib import Path

from roboflow import Roboflow


def main():
    parser = argparse.ArgumentParser(description="Fetch Roboflow Universe dataset (YOLO format)")
    parser.add_argument("--workspace", required=True, help="Roboflow workspace slug")
    parser.add_argument("--project", required=True, help="Roboflow project slug")
    parser.add_argument("--version", type=int, required=True, help="Roboflow dataset version")
    parser.add_argument("--format", default="yolov8", help="Export format (e.g., yolov8)")
    parser.add_argument("--out-dir", default="data/external/squirrel_roboflow", help="Output directory")
    args = parser.parse_args()

    api_key = os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        raise SystemExit("ROBOFLOW_API_KEY not set.")

    rf = Roboflow(api_key=api_key)
    ws = rf.workspace(args.workspace)
    proj = ws.project(args.project)
    ver = proj.version(args.version)

    print(f"Downloading from Roboflow: {args.workspace}/{args.project}/{args.version} as {args.format} ...")
    dataset = ver.download(args.format)
    dl_path = Path(dataset.location)

    out_dir = Path(args.out_dir).resolve()
    out_dir.parent.mkdir(parents=True, exist_ok=True)

    if out_dir.exists():
        print(f"Output exists, removing: {out_dir}")
        shutil.rmtree(out_dir)
    print(f"Moving dataset to: {out_dir}")
    shutil.move(str(dl_path), str(out_dir))

    # Normalize expected structure: images/ and labels/ at root or split subdirs
    # Roboflow typically provides train/valid/test under separate folders.
    print("✓ Download complete.")
    print(f"Location: {out_dir}")
    print("You can now point --squirrel-yolo-dir to this folder when running prepare_three_class_dataset.py")


if __name__ == "__main__":
    main()


