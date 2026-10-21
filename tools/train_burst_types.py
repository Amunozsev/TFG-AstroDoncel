"""Train the burst-type detector (YOLO11) on the dataset built by tools/burst_dataset.py.

Runs in the separate training environment (requirements-train.txt), not in the
API image. Example:
  python tools/train_burst_types.py D:/data/yolo/data.yaml D:/runs --epochs 3 --name trial
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", type=Path, help="data.yaml written by burst_dataset.py convert")
    parser.add_argument("project", type=Path, help="folder for training runs")
    parser.add_argument("--model", default="yolo11s.pt", help="pretrained COCO weights")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--patience", type=int, default=20, help="stop after this many epochs without improvement")
    parser.add_argument("--name", default="burst_types")
    args = parser.parse_args()

    from ultralytics import YOLO

    YOLO(args.model).train(
        data=str(args.data),
        project=str(args.project),
        name=args.name,
        epochs=args.epochs,
        imgsz=1024,      # image width of backend.burst_types.spectrogram_image
        batch=args.batch,
        patience=args.patience,
        seed=0,
        deterministic=True,
        # Flipping a spectrogram reverses time or frequency: a drifting burst
        # would drift the wrong way, which is part of what defines its type.
        fliplr=0.0,
        flipud=0.0,
    )


if __name__ == "__main__":
    main()
