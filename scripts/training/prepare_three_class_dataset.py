#!/usr/bin/env python3
"""
Prepare a 3-class YOLO dataset: person (0), bird (1), squirrel (2).

Sources:
 - COCO 2017 (person, bird) → converted to YOLO labels
 - A provided YOLO-format squirrel dataset (single-class) → remapped to class 2

Output structure:
  <out_root>/
    images/{train,val,test}/*.jpg
    labels/{train,val,test}/*.txt
    data.yaml  # names: [person, bird, squirrel]

Notes:
 - COCO download can be handled via torchvision if you don't have the files.
 - Squirrel dataset must be YOLO-format (images + labels) with a single class.
"""
import argparse
import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Set
import json
import random
import math

import numpy as np
from tqdm import tqdm

try:
    from pycocotools.coco import COCO
except ImportError:
    COCO = None

COCO_DEFAULT_ROOT = os.path.expanduser("~/.cache/coco/2017")
COCO_SPLITS = ("train2017", "val2017")

# Target classes and indices
CLASS_TO_INDEX = {
    "person": 0,
    "bird": 1,
    "squirrel": 2,
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_data_yaml(out_root: Path) -> None:
    data = {
        "path": str(out_root.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": ["person", "bird", "squirrel"],
    }
    yaml_path = out_root / "data.yaml"
    try:
        import yaml
        with open(yaml_path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)
    except Exception:
        # Fallback to JSON-ish dump if PyYAML missing at runtime
        with open(yaml_path, "w") as f:
            f.write(json.dumps(data, indent=2))


def download_coco_annotations(coco_root: Path) -> None:
    """Download COCO annotations if missing."""
    ann_dir = coco_root / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    
    annotations = {
        "instances_train2017.json": "http://images.cocodataset.org/annotations/annotations_trainval2017.zip",
        "instances_val2017.json": "http://images.cocodataset.org/annotations/annotations_trainval2017.zip",
    }
    
    # Check if we need to download
    need_download = False
    for ann_name in annotations.keys():
        if not (ann_dir / ann_name).exists():
            need_download = True
            break
    
    if not need_download:
        return
    
    # Download annotations zip
    import urllib.request
    import zipfile
    import tempfile
    
    zip_url = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
    print(f"Downloading COCO annotations from {zip_url}...")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_zip:
        urllib.request.urlretrieve(zip_url, tmp_zip.name)
        with zipfile.ZipFile(tmp_zip.name, 'r') as zip_ref:
            zip_ref.extractall(coco_root)
        os.unlink(tmp_zip.name)
    
    print("✓ COCO annotations downloaded")


def download_coco_images(coco_root: Path, split: str) -> None:
    """Download COCO images for the given split if missing."""
    images_dir = coco_root / split
    if images_dir.exists() and any(images_dir.iterdir()):
        return  # Already exists
    
    import urllib.request
    import zipfile
    import tempfile
    
    zip_url = f"http://images.cocodataset.org/zips/{split}.zip"
    print(f"Downloading COCO {split} images from {zip_url}...")
    print("This may take a while (several GB)...")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_zip:
        def progress_hook(count, block_size, total_size):
            if total_size > 0:
                percent = int(count * block_size * 100 / total_size)
                if percent % 10 == 0:
                    print(f"  Progress: {percent}%", end='\r', flush=True)
        
        try:
            urllib.request.urlretrieve(zip_url, tmp_zip.name, reporthook=progress_hook)
            print()  # New line after progress
            
            # Extract
            print(f"Extracting to {coco_root}...")
            with zipfile.ZipFile(tmp_zip.name, 'r') as zip_ref:
                zip_ref.extractall(coco_root)
            
            print(f"✓ {split} images downloaded and extracted")
        except Exception as e:
            raise RuntimeError(
                f"Failed to download COCO images for {split}: {e}\n"
                f"Please download manually from {zip_url} and extract to {coco_root}"
            )
        finally:
            if os.path.exists(tmp_zip.name):
                os.unlink(tmp_zip.name)


def load_or_download_coco(coco_root: Path, split: str, auto_download_images: bool = True) -> Tuple[Path, Path]:
    """
    Return (images_dir, annotations_json) for the given split.
    Downloads annotations and optionally images if missing.
    """
    images_dir = coco_root / split
    ann_dir = coco_root / "annotations"
    ann_file = ann_dir / f"instances_{split}.json"

    # Download annotations if missing
    if not ann_file.exists():
        download_coco_annotations(coco_root)
    
    # Download images if missing
    if not images_dir.exists() or not any(images_dir.iterdir()):
        if auto_download_images:
            download_coco_images(coco_root, split)
        else:
            raise RuntimeError(
                f"COCO images for {split} not found at {images_dir}.\n"
                f"Please download from:\n"
                f"  - Train: http://images.cocodataset.org/zips/train2017.zip\n"
                f"  - Val: http://images.cocodataset.org/zips/val2017.zip\n"
                f"Extract to: {coco_root}/\n"
                f"Or use: python scripts/training/download_coco_images.py --split {split} --output {coco_root}"
            )
    
    if not ann_file.exists():
        raise RuntimeError(f"COCO annotations missing at {ann_file}")
    
    return images_dir, ann_file


def coco_category_id_map(coco: COCO) -> Dict[str, int]:
    cats = coco.loadCats(coco.getCatIds())
    name_to_id = {c["name"]: c["id"] for c in cats}
    return name_to_id


def coco_to_yolo_bbox(bbox: List[float], img_w: int, img_h: int) -> Tuple[float, float, float, float]:
    # COCO bbox: [x_min, y_min, width, height] in pixels
    x, y, w, h = bbox
    cx = x + w / 2.0
    cy = y + h / 2.0
    # Normalize
    return cx / img_w, cy / img_h, w / img_w, h / img_h


def collect_coco_images(
    coco: COCO,
    images_dir: Path,
    person_id: int,
    bird_id: int,
    max_person_images: int,
    max_bird_images: int
) -> Tuple[Set[int], Dict[int, List[Dict]]]:
    """
    Return:
      selected_image_ids: set of image ids selected
      anns_by_img: mapping image_id -> list of annotations we care about (person/bird)
    """
    anns_by_img: Dict[int, List[Dict]] = {}
    selected_image_ids: Set[int] = set()

    # Query images containing person and bird separately; then we'll sample
    person_img_ids = set(coco.getImgIds(catIds=[person_id]))
    bird_img_ids = set(coco.getImgIds(catIds=[bird_id]))

    # Sample up to requested counts; shuffle to randomize
    person_ids = list(person_img_ids)
    bird_ids = list(bird_img_ids)
    random.shuffle(person_ids)
    random.shuffle(bird_ids)

    person_ids = set(person_ids[:max_person_images])
    bird_ids = set(bird_ids[:max_bird_images])

    selected_image_ids |= person_ids
    selected_image_ids |= bird_ids

    # Build anns
    for img_id in selected_image_ids:
        anns = []
        for cid, cname in [(person_id, "person"), (bird_id, "bird")]:
            ann_ids = coco.getAnnIds(imgIds=[img_id], catIds=[cid], iscrowd=None)
            anns.extend(coco.loadAnns(ann_ids))
        if anns:
            anns_by_img[img_id] = anns

    return selected_image_ids, anns_by_img


def copy_image(src_dir: Path, img_info: Dict, dst_dir: Path) -> Path:
    file_name = img_info["file_name"]
    src = src_dir / file_name
    dst = dst_dir / file_name
    ensure_dir(dst.parent)
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


def write_yolo_labels(label_path: Path, lines: List[str]) -> None:
    ensure_dir(label_path.parent)
    with open(label_path, "w") as f:
        for ln in lines:
            f.write(ln.rstrip() + "\n")


def generate_yolo_from_coco(
    coco: COCO,
    images_dir: Path,
    out_images: Path,
    out_labels: Path,
    selected_image_ids: Set[int],
    anns_by_img: Dict[int, List[Dict]],
    name_to_id: Dict[str, int]
) -> List[str]:
    img_paths: List[str] = []
    for img_id in tqdm(sorted(selected_image_ids), desc="Converting COCO -> YOLO"):
        info = coco.loadImgs([img_id])[0]
        dst_img = copy_image(images_dir, info, out_images)
        img_paths.append(dst_img.name)

        img_w = info["width"]
        img_h = info["height"]
        lines: List[str] = []
        for ann in anns_by_img.get(img_id, []):
            cid = ann["category_id"]
            cname = None
            if cid == name_to_id.get("person"):
                cname = "person"
            elif cid == name_to_id.get("bird"):
                cname = "bird"
            if not cname:
                continue
            yolo_cls = CLASS_TO_INDEX[cname]
            cx, cy, w, h = coco_to_yolo_bbox(ann["bbox"], img_w, img_h)
            # guard small/invalid boxes
            if w <= 0 or h <= 0:
                continue
            lines.append(f"{yolo_cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

        # Write label file (even if empty, to mark negatives)
        label_path = out_labels / (Path(info["file_name"]).stem + ".txt")
        write_yolo_labels(label_path, lines)
    return img_paths


def merge_squirrel_yolo(
    squirrel_yolo_dir: Path,
    out_images: Path,
    out_labels: Path
) -> List[str]:
    """
    Copy YOLO images/labels from squirrel dataset and remap all class ids to 2.
    Expect structure:
      squirrel_yolo_dir/
        images/*.jpg|png
        labels/*.txt
    """
    img_dir = squirrel_yolo_dir / "images"
    lbl_dir = squirrel_yolo_dir / "labels"
    if not img_dir.exists() or not lbl_dir.exists():
        raise RuntimeError(f"Squirrel YOLO dataset missing images/labels in {squirrel_yolo_dir}")

    img_paths: List[str] = []
    for img_path in tqdm(sorted(img_dir.glob("*")), desc="Merging squirrel dataset"):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        dst_img = out_images / img_path.name
        ensure_dir(dst_img.parent)
        if not dst_img.exists():
            shutil.copy2(img_path, dst_img)
        # Label file
        lbl_path = lbl_dir / (img_path.stem + ".txt")
        lines: List[str] = []
        if lbl_path.exists():
            with open(lbl_path, "r") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    parts = ln.split()
                    # Replace class id with 2 regardless of original
                    parts[0] = str(CLASS_TO_INDEX["squirrel"])
                    lines.append(" ".join(parts))
        # Write merged label
        write_yolo_labels(out_labels / (img_path.stem + ".txt"), lines)
        img_paths.append(dst_img.name)
    return img_paths


def stratified_split(
    filenames: List[str],
    cls_counts: Dict[str, int],
    train_ratio: float = 0.8,
    val_ratio: float = 0.1
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Simple randomized split by filenames. Not strictly stratified here, but randomized.
    """
    files = list(filenames)
    random.shuffle(files)
    n = len(files)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    train = set(files[:n_train])
    val = set(files[n_train:n_train + n_val])
    test = set(files[n_train + n_val:])
    return train, val, test


def move_split_sets(
    all_names: Set[str],
    train_set: Set[str],
    val_set: Set[str],
    test_set: Set[str],
    tmp_images: Path,
    tmp_labels: Path,
    out_root: Path
) -> None:
    for split, names in (("train", train_set), ("val", val_set), ("test", test_set)):
        img_dst = out_root / "images" / split
        lbl_dst = out_root / "labels" / split
        ensure_dir(img_dst)
        ensure_dir(lbl_dst)
        for name in names:
            src_img = tmp_images / name
            src_lbl = tmp_labels / (Path(name).stem + ".txt")
            shutil.move(str(src_img), str(img_dst / name))
            shutil.move(str(src_lbl), str(lbl_dst / (Path(name).stem + ".txt")))
    # Cleanup any remaining temp files
    for p in [tmp_images, tmp_labels]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Prepare 3-class YOLO dataset (person, bird, squirrel)")
    parser.add_argument("--out-root", type=str, default="data/datasets/person_bird_squirrel",
                        help="Output root for merged dataset")
    parser.add_argument("--coco-root", type=str, default=COCO_DEFAULT_ROOT,
                        help="COCO root dir (images under <root>/<split>, annotations under <root>/annotations)")
    parser.add_argument("--coco-splits", type=str, default="train2017,val2017",
                        help="Comma-separated COCO splits to sample from")
    parser.add_argument("--max-person-images", type=int, default=1500,
                        help="Max number of images containing person to sample")
    parser.add_argument("--max-bird-images", type=int, default=1500,
                        help="Max number of images containing bird to sample")
    parser.add_argument("--squirrel-yolo-dir", type=str, required=True,
                        help="Path to YOLO-format squirrel dataset (images/ + labels/)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    out_root = Path(args.out_root)
    tmp_images = out_root / "_tmp_images"
    tmp_labels = out_root / "_tmp_labels"
    ensure_dir(tmp_images)
    ensure_dir(tmp_labels)

    # Aggregate selected images across provided splits
    all_names: Set[str] = set()

    # COCO person+bird
    if COCO is None:
        raise RuntimeError("pycocotools is required. Install from scripts/training/requirements.txt")

    name_to_id_global: Dict[str, int] = {}
    for split in [s.strip() for s in args.coco_splits.split(",") if s.strip()]:
        images_dir, ann_file = load_or_download_coco(Path(args.coco_root), split)
        coco = COCO(str(ann_file))
        name_to_id = coco_category_id_map(coco)
        # update global mapping
        name_to_id_global.update(name_to_id)
        if "person" not in name_to_id or "bird" not in name_to_id:
            raise RuntimeError("COCO categories missing 'person' or 'bird'")

        selected_image_ids, anns_by_img = collect_coco_images(
            coco=coco,
            images_dir=images_dir,
            person_id=name_to_id["person"],
            bird_id=name_to_id["bird"],
            max_person_images=args.max_person_images,
            max_bird_images=args.max_bird_images
        )

        img_names = generate_yolo_from_coco(
            coco=coco,
            images_dir=images_dir,
            out_images=tmp_images,
            out_labels=tmp_labels,
            selected_image_ids=selected_image_ids,
            anns_by_img=anns_by_img,
            name_to_id=name_to_id
        )
        all_names.update(img_names)

    # Merge squirrel YOLO dataset (class id remapped to 2)
    squirrel_names = merge_squirrel_yolo(
        squirrel_yolo_dir=Path(args.squirrel_yolo_dir),
        out_images=tmp_images,
        out_labels=tmp_labels
    )
    all_names.update(squirrel_names)

    # Split
    train_set, val_set, test_set = stratified_split(sorted(all_names), cls_counts={}, train_ratio=0.8, val_ratio=0.1)

    # Move to final structure
    move_split_sets(
        all_names=set(all_names),
        train_set=train_set,
        val_set=val_set,
        test_set=test_set,
        tmp_images=tmp_images,
        tmp_labels=tmp_labels,
        out_root=out_root
    )

    # Write data.yaml
    write_data_yaml(out_root)

    print("\n✓ Dataset prepared")
    print(f"  Root: {out_root}")
    print(f"  Train/Val/Test counts: {len(train_set)} / {len(val_set)} / {len(test_set)}")
    print(f"  Classes: {list(CLASS_TO_INDEX.keys())}")
    print(f"  SQUIRREL_CLASS_ID: {CLASS_TO_INDEX['squirrel']} (to use in detection)")


if __name__ == "__main__":
    main()


