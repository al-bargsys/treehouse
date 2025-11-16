## YOLOv8 single-model training (person, bird, squirrel)

This guide shows how to build a single YOLOv8 model that detects three classes:
`person` (0), `bird` (1), `squirrel` (2). You’ll deploy one `.pt` and set
`SQUIRREL_CLASS_ID=2`.

### 1) Prepare environment

Create a local venv and install training deps:

```bash
python3 -m venv .trainenv
source .trainenv/bin/activate
pip install -r scripts/training/requirements.txt
```

### 2) Prepare dataset

Inputs:
- COCO 2017 for person/bird (auto-downloaded if missing).
- A YOLO-format squirrel dataset (single-class) with:
  - `images/` (jpg/png)
  - `labels/` (per-image `.txt`, YOLO format)

Run:

```bash
python scripts/training/prepare_three_class_dataset.py \
  --out-root data/datasets/person_bird_squirrel \
  --squirrel-yolo-dir /absolute/path/to/your/squirrel_yolo \
  --max-person-images 1500 \
  --max-bird-images 1500
```

This will produce:
```
data/datasets/person_bird_squirrel/
  images/{train,val,test}/...
  labels/{train,val,test}/...
  data.yaml  # names: [person, bird, squirrel]
```

Notes:
- Class indices are fixed: person=0, bird=1, squirrel=2.
- You can reduce `--max-*` counts for a smaller/faster experiment.

### 3) Train YOLOv8

```bash
python scripts/training/train_yolov8_three_class.py \
  --data data/datasets/person_bird_squirrel/data.yaml \
  --base yolov8s.pt \
  --epochs 50 \
  --imgsz 640 \
  --batch 16
```

Outputs go under `models/yolov8_person_bird_squirrel/<RUN_NAME>/weights/best.pt`.

### 4) Deploy to the detection service

In `docker-compose.yml` for the detection service:
- Set `MODEL_PATH` to the absolute path of `best.pt`.
- Set `SQUIRREL_CLASS_ID=2`.

Example:
```yaml
environment:
  - MODEL_PATH=/absolute/path/to/models/yolov8_person_bird_squirrel/20250101_120000/weights/best.pt
  - SQUIRREL_CLASS_ID=2
```

Restart the stack. The logs should report Bird/Human/Squirrel counts.

### Tips
- Include some images from your camera/scene in the squirrel dataset to reduce domain gap.
- If mAP on squirrels is low, increase squirrel images, add augmentations, or train longer (more epochs).
- If you want faster training: start with `yolov8n.pt`. For better accuracy, try `yolov8m.pt`.


