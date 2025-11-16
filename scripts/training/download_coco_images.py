#!/usr/bin/env python3
"""
Download COCO 2017 images for a specific split (train2017 or val2017).
"""
import argparse
import urllib.request
import zipfile
import tempfile
import os
from pathlib import Path


def download_coco_split(split: str, output_dir: Path) -> None:
    """Download and extract COCO images for the given split."""
    if split not in ("train2017", "val2017"):
        raise ValueError(f"Split must be 'train2017' or 'val2017', got: {split}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    zip_url = f"http://images.cocodataset.org/zips/{split}.zip"
    zip_name = f"{split}.zip"
    
    print(f"Downloading {split} from {zip_url}...")
    print("This may take a while (several GB)...")
    
    # Download to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_zip:
        def progress_hook(count, block_size, total_size):
            percent = int(count * block_size * 100 / total_size)
            if percent % 10 == 0:
                print(f"  Progress: {percent}%", end='\r', flush=True)
        
        urllib.request.urlretrieve(zip_url, tmp_zip.name, reporthook=progress_hook)
        print()  # New line after progress
        
        # Extract
        print(f"Extracting to {output_dir}...")
        with zipfile.ZipFile(tmp_zip.name, 'r') as zip_ref:
            zip_ref.extractall(output_dir)
        
        # Cleanup
        os.unlink(tmp_zip.name)
    
    print(f"✓ {split} downloaded and extracted to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Download COCO 2017 images")
    parser.add_argument("--split", type=str, required=True, choices=["train2017", "val2017"],
                        help="COCO split to download")
    parser.add_argument("--output", type=str, default=os.path.expanduser("~/.cache/coco/2017"),
                        help="Output directory (will create <split> subdirectory)")
    args = parser.parse_args()
    
    output_dir = Path(args.output) / args.split
    download_coco_split(args.split, output_dir.parent)  # Extract to parent so split dir is created


if __name__ == "__main__":
    main()

