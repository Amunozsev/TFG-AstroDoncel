"""Burst-type detector: input contract shared with training, and ONNX inference.

The detector sees each FITS file as the portal shows it by default: relative
digits, robust background subtraction, no RFI filter and a 2-98 % intensity
clip. The image keeps the FITS channel order (high frequency on top) and spans
the whole file in time.

Inference needs onnxruntime and the model folder; if either is missing,
`is_available()` says why and the backend still starts.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from backend.main import _percentile_clip_global, _subtract_background

IMAGE_WIDTH = 1024   # time; a 26 s type III spans about 30 px of a 900 s file
IMAGE_HEIGHT = 400   # frequency; receivers have 100-300 channels
CLASSES = ("type2", "type3", "type3s", "type4", "type5")


def spectrogram_image(data_raw: np.ndarray) -> np.ndarray:
    """Return the detector input for one FITS matrix (channels x samples) as uint8 (H, W)."""
    data = _subtract_background(np.asarray(data_raw, dtype=np.float32))
    vmin, vmax = _percentile_clip_global(data)
    scaled = np.clip((data - vmin) / max(vmax - vmin, 1e-9), 0.0, 1.0)
    scaled = np.nan_to_num(scaled, nan=0.0).astype(np.float32)
    resized = Image.fromarray(scaled, mode="F").resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.BILINEAR)
    return (np.asarray(resized) * 255.0).round().clip(0, 255).astype(np.uint8)


def box_to_physical(box: tuple[float, float, float, float], duration_s: float,
                    freqs_mhz: np.ndarray) -> dict[str, float]:
    """Convert a box in image fractions (x0, y0, x1, y1; y down) to seconds and MHz.

    Rows follow the FITS channel order, so a fraction maps to a channel index
    and the frequency is read from that channel, not interpolated linearly.
    """
    x0, y0, x1, y1 = box
    n = len(freqs_mhz)
    top = min(int(np.floor(y0 * n)), n - 1)
    bottom = min(max(int(np.ceil(y1 * n)) - 1, top), n - 1)
    channel_freqs = (float(freqs_mhz[top]), float(freqs_mhz[bottom]))
    return {
        "start_s": x0 * duration_s,
        "end_s": x1 * duration_s,
        "freq_low_mhz": min(channel_freqs),
        "freq_high_mhz": max(channel_freqs),
    }


MODEL_DIR = Path(os.environ.get("BURST_MODEL_DIR", Path(__file__).parent / "model" / "burst_types"))
_MODEL_LOCK = threading.Lock()
_MODEL: dict | None = None


def is_available() -> tuple[bool, str]:
    """Return (available, reason). Detection needs onnxruntime and the model folder."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError as exc:
        return False, f"onnxruntime is not installed ({exc}). Install the production requirements."
    if not (MODEL_DIR / "model.onnx").is_file() or not (MODEL_DIR / "config.json").is_file():
        return False, "Burst model not found; check BURST_MODEL_DIR on the server"
    return True, ""


def _load_model() -> dict:
    """Load and cache the ONNX session, its configuration and the file hash."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = max(1, int(os.environ.get("BURST_INTRA_OP_THREADS", "1")))
            options.inter_op_num_threads = 1
            path = MODEL_DIR / "model.onnx"
            _MODEL = {
                "session": ort.InferenceSession(str(path), sess_options=options,
                                                providers=["CPUExecutionProvider"]),
                "config": json.loads((MODEL_DIR / "config.json").read_text(encoding="utf-8")),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        return _MODEL


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    """Greedy non-maximum suppression; returns the kept indices by descending score."""
    order = np.argsort(-scores)
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    keep = []
    while order.size:
        i, rest = order[0], order[1:]
        keep.append(int(i))
        lt = np.maximum(boxes[i, :2], boxes[rest, :2])
        rb = np.minimum(boxes[i, 2:], boxes[rest, 2:])
        inter = np.prod(np.clip(rb - lt, 0, None), axis=1)
        order = rest[inter / (area[i] + area[rest] - inter + 1e-9) <= iou]
    return keep


def decode(output: np.ndarray, conf: float, iou: float, pad: int) -> list[tuple[float, ...]]:
    """Turn the raw YOLO output (4 + classes, anchors) into boxes in image fractions.

    Same rules as Ultralytics: best class per anchor, confidence threshold,
    per-class NMS, then the padding is removed and boxes are clipped to the image.
    Returns (x0, y0, x1, y1, score, class) sorted by descending score.
    """
    cx, cy, w, h = output[:4]
    cls = output[4:].argmax(axis=0)
    score = output[4:].max(axis=0)
    sel = score > conf
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)[sel]
    score, cls = score[sel], cls[sel]
    # Shifting each class far apart makes a single NMS pass work per class.
    keep = _nms(boxes + cls[:, None] * 4096.0, score, iou)
    out = []
    for i in keep:
        x0, x1 = np.clip(boxes[i, [0, 2]], 0, IMAGE_WIDTH) / IMAGE_WIDTH
        y0, y1 = np.clip(boxes[i, [1, 3]] - pad, 0, IMAGE_HEIGHT) / IMAGE_HEIGHT
        out.append((float(x0), float(y0), float(x1), float(y1), float(score[i]), int(cls[i])))
    return out


def _utc(start: datetime, seconds: float) -> str:
    ts = start + timedelta(seconds=seconds)
    return f"{ts.strftime('%Y-%m-%dT%H:%M:%S')}.{ts.microsecond // 1000:03d}Z"


def detect(data_raw: np.ndarray, freqs: np.ndarray, time_s: np.ndarray, obs_start: datetime) -> dict:
    """Detect and classify the bursts of one FITS file; JSON-serialisable result."""
    model = _load_model()
    config = model["config"]
    t0 = time.perf_counter()

    size = config["input"]
    pad = (size["height"] - IMAGE_HEIGHT) // 2
    image = np.full((size["height"], size["width"]), size["pad_value"], np.float32)
    image[pad:pad + IMAGE_HEIGHT] = spectrogram_image(data_raw)
    tensor = np.repeat(image[None, None] / 255.0, 3, axis=1).astype(np.float32)
    session = model["session"]
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
    boxes = decode(output, config["confidence_threshold"], config["nms_iou"], pad)

    # The image spans the whole file: fraction x of its width is sample x * n.
    time_s = np.asarray(time_s, dtype=float)
    step = float(np.median(np.diff(time_s))) if time_s.size > 1 else 0.0
    first = float(time_s[0]) if time_s.size else 0.0
    detections = []
    for x0, y0, x1, y1, score, cls in boxes:
        physical = box_to_physical((x0, y0, x1, y1), step * time_s.size, np.asarray(freqs, dtype=float))
        start_s, end_s = first + physical["start_s"], first + physical["end_s"]
        detections.append({
            "type": CLASSES[cls],
            "score": round(score, 3),
            "experimental": CLASSES[cls] in config["experimental_classes"],
            "start_utc": _utc(obs_start, start_s),
            "end_utc": _utc(obs_start, end_s),
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
            "freq_low_mhz": round(physical["freq_low_mhz"], 3),
            "freq_high_mhz": round(physical["freq_high_mhz"], 3),
        })
    return {
        "model_version": config["model_version"],
        "model_sha256": model["sha256"],
        "threshold": config["confidence_threshold"],
        "detections": detections,
        "inference_ms": round((time.perf_counter() - t0) * 1000.0, 1),
    }
