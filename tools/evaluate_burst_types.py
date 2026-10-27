"""Final evaluation of the burst-type detector on one split (normally test, used once).

Runs in the training environment (requirements-train.txt). Reports mAP per
class with bootstrap 95 % intervals, class-agnostic detection, false alarms on
burst-free files and per-station recall/precision at a fixed confidence
threshold chosen beforehand on validation. Example:
  python tools/evaluate_burst_types.py D:/data/yolo/data.yaml D:/runs/v4/weights/best.pt D:/eval --conf 0.32
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

CLASSES = ("type2", "type3", "type3s", "type4", "type5")  # backend.burst_types.CLASSES
IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)


def _labels(image: Path, width: int, height: int) -> np.ndarray:
    """YOLO label file -> array of [class, x0, y0, x1, y1] in pixels."""
    path = Path(str(image).replace("images", "labels")).with_suffix(".txt")
    rows = [list(map(float, line.split())) for line in path.read_text().splitlines() if line.strip()]
    out = np.zeros((len(rows), 5))
    for i, (c, cx, cy, w, h) in enumerate(rows):
        out[i] = [c, (cx - w / 2) * width, (cy - h / 2) * height, (cx + w / 2) * width, (cy + h / 2) * height]
    return out


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between boxes a (N, 4) and b (M, 4) given as x0, y0, x1, y1."""
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.prod(np.clip(rb - lt, 0, None), axis=2)
    area = lambda x: np.prod(x[:, 2:] - x[:, :2], axis=1)  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


def _true_positives(pred: np.ndarray, gt: np.ndarray, agnostic: bool) -> np.ndarray:
    """COCO matching: predictions by descending confidence, each to the free box with the highest IoU."""
    tp = np.zeros((len(pred), len(IOU_THRESHOLDS)), bool)
    if not len(pred) or not len(gt):
        return tp
    iou = _iou(gt[:, 1:], pred[:, :4])
    if not agnostic:
        iou *= gt[:, :1] == pred[None, :, 5]
    for j, threshold in enumerate(IOU_THRESHOLDS):
        free = np.ones(len(gt), bool)
        for p in np.argsort(-pred[:, 4]):
            candidates = np.where(free, iou[:, p], 0.0)
            g = int(candidates.argmax())
            if candidates[g] >= threshold:
                free[g] = False
                tp[p, j] = True
    return tp


def average_precision(tp: np.ndarray, conf: np.ndarray, n_gt: int) -> np.ndarray:
    """AP at each IoU threshold, computed by Ultralytics so it matches its validation report."""
    from ultralytics.utils.metrics import ap_per_class

    if n_gt == 0 or not len(conf):
        return np.zeros(len(IOU_THRESHOLDS))
    return ap_per_class(tp, conf, np.zeros(len(conf)), np.zeros(n_gt))[5][0]


def class_ap(samples: list[dict], cls: int | None) -> np.ndarray:
    """AP over the given images for one class (None: class-agnostic)."""
    key = "tp_any" if cls is None else "tp"
    tps, confs, n_gt = [], [], 0
    for s in samples:
        keep = slice(None) if cls is None else s["pred"][:, 5] == cls
        tps.append(s[key][keep])
        confs.append(s["pred"][keep, 4])
        n_gt += len(s["gt"]) if cls is None else int((s["gt"][:, 0] == cls).sum())
    return average_precision(np.concatenate(tps), np.concatenate(confs), n_gt)


def bootstrap(samples: list[dict], cls: int | None, rounds: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95 % percentile interval of mAP50 resampling images with replacement."""
    rng = np.random.default_rng(seed)
    values = [class_ap([samples[i] for i in rng.integers(0, len(samples), len(samples))], cls)[0]
              for _ in range(rounds)]
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", type=Path)
    parser.add_argument("weights", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--conf", type=float, required=True, help="operating threshold chosen on validation")
    parser.add_argument("--min-station-boxes", type=int, default=20)
    args = parser.parse_args()

    from ultralytics import YOLO

    model = YOLO(str(args.weights))
    # Ultralytics' own report and plots (confusion matrix, PR and F1 curves).
    model.val(data=str(args.data), split=args.split, imgsz=1024, project=str(args.output), name="ultralytics",
              exist_ok=True, plots=True, verbose=False)

    root = Path(str(args.data)).parent
    images = sorted((root / "images" / args.split).glob("*.png"))
    samples = []
    for i in range(0, len(images), 32):
        for r in model.predict([str(p) for p in images[i:i + 32]], imgsz=1024, conf=0.001, iou=0.7,
                               max_det=300, verbose=False):
            b = r.boxes
            pred = np.c_[b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), b.cls.cpu().numpy()]
            gt = _labels(Path(r.path), r.orig_shape[1], r.orig_shape[0])
            samples.append({"name": Path(r.path).stem, "pred": pred, "gt": gt,
                            "tp": _true_positives(pred, gt, agnostic=False),
                            "tp_any": _true_positives(pred, gt, agnostic=True)})

    report = {"split": args.split, "weights": str(args.weights), "conf": args.conf, "images": len(samples),
              "classes": {}}
    for cls in [*range(len(CLASSES)), None]:
        name = "any_burst" if cls is None else CLASSES[cls]
        ap = class_ap(samples, cls)
        n_gt = sum(len(s["gt"]) if cls is None else int((s["gt"][:, 0] == cls).sum()) for s in samples)
        low, high = bootstrap(samples, cls)
        report["classes"][name] = {"boxes": n_gt, "mAP50": round(float(ap[0]), 3),
                                   "mAP50_95": round(float(ap.mean()), 3),
                                   "mAP50_ci95": [round(low, 3), round(high, 3)]}
    per_class = [report["classes"][c] for c in CLASSES]
    report["mAP50_mean_classes"] = round(float(np.mean([c["mAP50"] for c in per_class])), 3)
    report["mAP50_95_mean_classes"] = round(float(np.mean([c["mAP50_95"] for c in per_class])), 3)

    # At the operating threshold: false alarms on burst-free files and per-station detection.
    negatives = [s for s in samples if not len(s["gt"])]
    alarms = [int((s["pred"][:, 4] >= args.conf).sum()) for s in negatives]
    report["negatives"] = {"files": len(negatives), "files_with_alarm": int(sum(a > 0 for a in alarms)),
                           "boxes": int(sum(alarms))}
    # Class-agnostic at IoU 0.5; matching is one-to-one, so correct boxes == bursts found.
    stations = defaultdict(lambda: {"gt": 0, "pred": 0, "correct": 0})
    for s in samples:
        keep = s["pred"][:, 4] >= args.conf
        st = stations[s["name"].rsplit("_", 3)[0]]
        st["gt"] += len(s["gt"])
        st["pred"] += int(keep.sum())
        st["correct"] += int(s["tp_any"][keep, 0].sum())
    report["stations"] = {
        name: {"boxes": v["gt"], "recall": round(v["correct"] / v["gt"], 3),
               "precision": round(v["correct"] / v["pred"], 3) if v["pred"] else None}
        for name, v in sorted(stations.items()) if v["gt"] >= args.min_station_boxes
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
