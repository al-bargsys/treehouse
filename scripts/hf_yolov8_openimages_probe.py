from huggingface_hub import HfApi, hf_hub_download, list_repo_files
import re, json

def main():
    api = HfApi()
    queries = ["yolov8 open images","openimages yolov8","keremberke yolov8 open images"]
    seen=set(); repos=[]
    for q in queries:
        for m in api.list_models(search=q, sort=downloads, direction=-1, limit=30):
            rid=m.modelId
            if rid in seen: continue
            seen.add(rid)
            rl=rid.lower()
            if yolov8 in rl and any(s in rl for s in [openimages,open-images,open
