#!/usr/bin/env python3
"""
Normalize a Roboflow YOLO export into a single-folder YOLO structure:

Input (Roboflow export):
  <rf_root>/
    train/images/*.jpg|png
    train/labels/*.txt
    valid/images/*.jpg|png   (or 'val')
    valid/labels/*.txt
    test/images/*.jpg|png
    test/labels/*.txt

Output:
  <out_dir>/
    images/*.jpg|png
    labels/*.txt

Images and labels from all splits are merged. To avoid filename collisions,
files are prefixed with the split name: train_<name>.jpg, valid_<name>.jpg, etc.

This script does NOT change label class IDs. Our dataset prep step will remap
the squirrel class to index 2 during merge.
"""
import argparse
from pathlib import Path
import shutil
from typing import List

VALID_SPLITS = ["train", "valid", "val", "test"]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def merge_split(rf_root: Path, split: str, out_images: Path, out_labels: Path) -> int:
    split_dir = rf_root / split
    img_dir = split_dir / "images"
    lbl_dir = split_dir / "labels"
    if not img_dir.exists() or not lbl_dir.exists():
        return 0

    count = 0
    for img_path in sorted(img_dir.iterdir()):
        if img_path.suffix.lower() not in IMG_EXTS:
            continue
        stem = img_path.stem
        dst_img = out_images / f"{split}_{img_path.name}"
        dst_lbl = out_labels / f"{split}_{stem}.txt"
        src_lbl = lbl_dir / f"{stem}.txt"
        ensure_dir(dst_img.parent)
        ensure_dir(dst_lbl.parent)
        if not dst_img.exists():
            shutil.copy2(img_path, dst_img)
        if src_lbl.exists():
            shutil.copy2(src_lbl, dst_lbl)
        else:
            # Create empty label for images without labels (should be rare)
            dst_lbl.write_text("")
        count += 1
    return count


def main():
    ap = argparse.ArgumentParser(description="Normalize Roboflow YOLO export into a single images/labels folder")
    ap.add_argument("--rf-root", required=True, help="Path to unzipped Roboflow YOLO export root")
    ap.add_argument("--out-dir", required=True, help="Output directory for merged YOLO dataset")
    args = ap.parse_args()

    rf_root = Path(args.rf_root).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_images = out_dir / "images"
    out_labels = out_dir / "labels"
    ensure_dir(out_images)
    ensure_dir(out_labels)

    total = 0
    for split in VALID_SPLITS:
        merged = merge_split(rf_root, split, out_images, out_labels)
        if merged > 0:
            print(f"Merged {merged} images from split '{split}'")
        total += merged

    print(f"\n✓ Normalization complete. Total images: {total}")
    print(f"Output at: {out_dir}")
    print("Next: use --squirrel-yolo-dir pointing to this folder in prepare_three_class_dataset.py")


if __name__ == "__main__":
    main()


