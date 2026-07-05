"""
Automatic solar radio burst detection (CNN + MIL).
Ported from Burst_No_Burst by Sahan S Liyanage (models/window_cnn.py,
models/mil_head.py, data/windowing.py, preprocess/*, infer/*).

torch is an OPTIONAL dependency: if it is not installed the module still
imports fine and `is_available()` reports why detection is disabled, so the
backend never fails to start because of it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import timedelta

import numpy as np
from scipy.ndimage import median_filter, percentile_filter

logger = logging.getLogger(__name__)

try:
    import torch
    from torch import nn
    _TORCH_ERROR: str | None = None
except ImportError as exc:  # torch is optional — degrade gracefully
    torch = None
    nn = None
    _TORCH_ERROR = str(exc)

# Deployment bundle shipped with Sahan's Burst_No_Burst (trained CNN+MIL).
_DEFAULT_BUNDLE_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..",
        "Sahan", "Burst_No_Burst-master", "deploy", "deploy_v1",
    )
)
BUNDLE_DIR = os.environ.get("BURST_MODEL_DIR", _DEFAULT_BUNDLE_DIR)


def is_available() -> tuple[bool, str]:
    """Return (available, reason). Detection needs torch AND the model bundle."""
    if torch is None:
        return False, (
            f"torch is not installed ({_TORCH_ERROR}). "
            "Install with: pip install torch --index-url https://download.pytorch.org/whl/cpu"
        )
    if not os.path.isfile(os.path.join(BUNDLE_DIR, "model.pt")):
        return False, f"Model bundle not found in {BUNDLE_DIR}"
    return True, ""


# ── Model definitions (ported from models/window_cnn.py + mil_head.py) ───────

if torch is not None:

    class _ConvBlock(nn.Module):
        def __init__(self, in_ch: int, out_ch: int) -> None:
            super().__init__()
            self.block = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(kernel_size=2),
            )

        def forward(self, x):
            return self.block(x)

    class WindowCNN(nn.Module):
        """Compact 2D CNN that predicts a logit per spectrogram window."""

        def __init__(self, in_channels: int = 1, base_channels: int = 16, dropout: float = 0.2) -> None:
            super().__init__()
            c1, c2, c3, c4 = (base_channels, base_channels * 2, base_channels * 4, base_channels * 8)
            self.features = nn.Sequential(
                _ConvBlock(in_channels, c1),
                _ConvBlock(c1, c2),
                _ConvBlock(c2, c3),
                _ConvBlock(c3, c4),
            )
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.dropout = nn.Dropout(p=dropout)
            self.head = nn.Linear(c4, 1)
            self.embedding_dim = c4

        def forward(self, x):
            feat = self.features(x)
            emb = self.pool(feat).flatten(1)
            emb = self.dropout(emb)
            logits = self.head(emb).squeeze(1)
            return logits, emb

    class _AttentionMILPool(nn.Module):
        def __init__(self, embed_dim: int) -> None:
            super().__init__()
            hidden = max(8, embed_dim // 2)
            self.attn = nn.Sequential(
                nn.Linear(embed_dim, hidden),
                nn.Tanh(),
                nn.Linear(hidden, 1),
            )

        def forward(self, embeddings):
            logits = self.attn(embeddings).squeeze(1)
            return torch.softmax(logits, dim=0)

    class MILHead(nn.Module):
        """Bag-level pooling from window scores (noisy_or/attention/max/topk_mean)."""

        def __init__(self, pooling: str = "noisy_or", embed_dim: int = 128, topk: int = 8) -> None:
            super().__init__()
            pooling = pooling.lower().strip()
            if pooling not in {"noisy_or", "attention", "max", "topk_mean"}:
                raise ValueError(f"Unsupported MIL pooling: {pooling}")
            self.pooling = pooling
            self.topk = max(1, int(topk))
            self.attention = _AttentionMILPool(embed_dim) if pooling == "attention" else None

        def forward(self, window_logits, embeddings=None):
            probs = torch.sigmoid(window_logits)
            if probs.numel() == 0:
                raise ValueError("Empty bag: no windows available")
            if self.pooling == "noisy_or":
                p = probs.clamp(1e-6, 1.0 - 1e-6)
                bag_prob = 1.0 - torch.prod(1.0 - p)
            elif self.pooling == "max":
                bag_prob = torch.max(probs)
            elif self.pooling == "topk_mean":
                k = max(1, min(self.topk, probs.numel()))
                topk_vals, _ = torch.topk(probs, k=k, dim=0)
                bag_prob = torch.mean(topk_vals)
            else:
                if embeddings is None or self.attention is None:
                    raise ValueError("Attention pooling requires embeddings")
                weights = self.attention(embeddings)
                bag_prob = torch.sum(weights * probs)
            return bag_prob.clamp(1e-6, 1.0 - 1e-6), probs


# ── Model-specific preprocessing (ported from preprocess/*.py) ───────────────
# NOTE: this pipeline is intentionally SEPARATE from the portal's display
# pipeline — the model was trained on exactly these transforms.

def _apply_log1p_nonnegative(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return np.log1p(np.clip(x, a_min=0.0, a_max=None))


def _running_quantile_baseline(x_log: np.ndarray, quantile: float = 0.2, window: int = 121) -> np.ndarray:
    x_log = np.asarray(x_log, dtype=np.float32)
    if window < 3:
        window = 3
    if window % 2 == 0:
        window += 1
    percentile = float(np.clip(quantile, 0.0, 1.0) * 100.0)
    baseline = percentile_filter(x_log, percentile=percentile, size=(1, window), mode="nearest")
    return baseline.astype(np.float32)


def _robust_per_frequency_normalize(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    med = np.median(x, axis=1, keepdims=True)
    mad = np.median(np.abs(x - med), axis=1, keepdims=True)
    return ((x - med) / (mad + eps)).astype(np.float32)


def _preprocess_for_model(x_raw: np.ndarray, cfg: dict) -> np.ndarray:
    """Full model preprocessing (ported from preprocess/pipeline.preprocess_spectrum)."""
    from backend.main import _mitigate_rfi  # deferred to avoid a circular import

    x = np.asarray(x_raw, dtype=np.float32)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    x_log = _apply_log1p_nonnegative(x)
    baseline = _running_quantile_baseline(
        x_log,
        quantile=float(cfg.get("bg_quantile", 0.2)),
        window=int(cfg.get("bg_window", 121)),
    )
    x_bg = x_log - baseline
    if bool(cfg.get("floor_zero", True)):
        x_bg = np.maximum(x_bg, 0.0).astype(np.float32)

    x_norm = _robust_per_frequency_normalize(x_bg)

    x_rfi, _, _ = _mitigate_rfi(
        x_norm,
        z_thresh=float(cfg.get("rfi_z_thresh", 6.0)),
        occupancy_thresh=float(cfg.get("rfi_occupancy_thresh", 0.15)),
        min_component_size=int(cfg.get("rfi_min_component_size", 9)),
    )

    return np.clip(
        x_rfi,
        float(cfg.get("clip_min", -6.0)),
        float(cfg.get("clip_max", 12.0)),
    ).astype(np.float32)


# ── Windowing (ported from data/windowing.py) ────────────────────────────────

def _start_positions(length: int, win: int, stride: int) -> list[int]:
    if length <= win:
        return [0]
    starts = list(range(0, length - win + 1, stride))
    last_start = length - win
    if starts[-1] != last_start:
        starts.append(last_start)
    return starts


def _extract_windows(x: np.ndarray, wcfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return windows [N,1,H,W] and coords [N,4] with (f0,f1,t0,t1)."""
    height = int(wcfg.get("height", 128))
    width = int(wcfg.get("width", 128))
    stride_h = int(wcfg.get("stride_h", 64))
    stride_w = int(wcfg.get("stride_w", 64))

    x = np.asarray(x, dtype=np.float32)
    pad_h = max(0, height - x.shape[0])
    pad_w = max(0, width - x.shape[1])
    if pad_h or pad_w:
        x = np.pad(x, ((0, pad_h), (0, pad_w)), mode="edge").astype(np.float32)

    coords: list[tuple[int, int, int, int]] = []
    for f0 in _start_positions(x.shape[0], height, stride_h):
        for t0 in _start_positions(x.shape[1], width, stride_w):
            coords.append((f0, f0 + height, t0, t0 + width))

    windows = np.stack([x[f0:f1, t0:t1] for (f0, f1, t0, t1) in coords], axis=0)
    return windows[:, None, :, :].astype(np.float32), np.asarray(coords, dtype=np.int64)


# ── Bundle loading (singleton, ported from infer/deploy.py) ──────────────────

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict | None = None


def _load_bundle() -> dict:
    """Load and cache the deployment bundle (model + MIL head + config)."""
    global _MODEL_CACHE
    with _MODEL_LOCK:
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE

        profile_path = os.path.join(BUNDLE_DIR, "deploy_profile.json")
        profile: dict = {}
        if os.path.isfile(profile_path):
            with open(profile_path, "r", encoding="utf-8") as fh:
                profile = json.load(fh)

        # The profile stores the author's absolute paths — always resolve the
        # checkpoint and threshold locally inside the bundle directory.
        ckpt_path = os.path.join(BUNDLE_DIR, "model.pt")
        threshold = float(profile.get("threshold", 0.6))
        th_path = os.path.join(BUNDLE_DIR, "threshold.json")
        if os.path.isfile(th_path):
            try:
                with open(th_path, "r", encoding="utf-8") as fh:
                    obj = json.load(fh)
                if isinstance(obj, dict):
                    if isinstance(obj.get("selected"), dict) and "threshold" in obj["selected"]:
                        threshold = float(obj["selected"]["threshold"])
                    elif "threshold" in obj:
                        threshold = float(obj["threshold"])
            except Exception:
                pass

        logger.info("Loading burst-detection bundle from %s", ckpt_path)
        # Trusted local academic bundle → weights_only=False (the checkpoint
        # stores the training config dict alongside the state_dicts).
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        cfg = ckpt.get("config", {})
        mcfg = cfg.get("model", {})

        model = WindowCNN(
            in_channels=1,
            base_channels=int(mcfg.get("base_channels", 16)),
            dropout=float(mcfg.get("dropout", 0.2)),
        )
        mil_head = MILHead(
            pooling=str(mcfg.get("mil_pooling", "noisy_or")),
            embed_dim=model.embedding_dim,
            topk=int(mcfg.get("mil_topk", 8)),
        )
        model.load_state_dict(ckpt["model_state"])
        mil_head.load_state_dict(ckpt["mil_state"])
        model.eval()
        mil_head.eval()

        _MODEL_CACHE = {
            "model": model,
            "mil_head": mil_head,
            "cfg": cfg,
            "threshold": threshold,
            "model_version": str(ckpt.get("model_version", profile.get("model_version", "unknown"))),
            "bundle_name": profile.get("bundle_name"),
        }
        return _MODEL_CACHE


def _score_windows(model, mil_head, windows_np: np.ndarray, batch_size: int = 64) -> tuple[float, np.ndarray]:
    """Ported from infer/scoring.score_windows_batched (CPU inference)."""
    windows = torch.from_numpy(windows_np)
    all_logits, all_emb = [], []
    with torch.no_grad():
        for start in range(0, windows.shape[0], batch_size):
            batch = windows[start : start + batch_size]
            logits, emb = model(batch)
            all_logits.append(logits)
            all_emb.append(emb)
    logits_cat = torch.cat(all_logits, dim=0)
    emb_cat = torch.cat(all_emb, dim=0)
    bag_prob, win_probs = mil_head(logits_cat, emb_cat)
    return float(bag_prob.item()), win_probs.detach().cpu().numpy().astype(np.float32)


# ── Event extraction (ported from infer/event_postprocess.py) ────────────────

def _collapse_scores_by_time_start(window_scores: np.ndarray, coords: np.ndarray):
    """Average scores over frequency windows for each window time-start index."""
    starts = coords[:, 2]
    ends = coords[:, 3]
    unique_starts = np.unique(starts)
    avg_scores = np.array(
        [float(np.mean(window_scores[starts == t0])) for t0 in unique_starts],
        dtype=np.float32,
    )
    widths = np.maximum(1, ends - starts)
    typical_width = int(np.median(widths)) if widths.size > 0 else 1
    return unique_starts.astype(np.int64), avg_scores, typical_width


def _find_contiguous_segments(binary: np.ndarray) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(binary.tolist()):
        if v and start is None:
            start = i
        if not v and start is not None:
            segments.append((start, i - 1))
            start = None
    if start is not None:
        segments.append((start, len(binary) - 1))
    return segments


def _extract_events(
    window_scores: np.ndarray,
    coords: np.ndarray,
    time_axis_s: np.ndarray,
    freq_axis_mhz: np.ndarray,
    obs_start_dt,
    threshold: float,
    smooth_kernel: int = 5,
    min_event_windows: int = 3,
) -> list[dict]:
    """Convert window probabilities into burst event intervals."""
    if len(window_scores) == 0:
        return []

    t_starts, t_scores, win_width = _collapse_scores_by_time_start(window_scores, coords)
    smooth_kernel = max(1, int(smooth_kernel))
    if smooth_kernel % 2 == 0:
        smooth_kernel += 1
    smooth_scores = median_filter(t_scores, size=smooth_kernel, mode="nearest")

    segments = _find_contiguous_segments(smooth_scores >= float(threshold))

    def _t_seconds(idx: int) -> float:
        if time_axis_s.size == 0:
            return float(idx)
        return float(time_axis_s[int(np.clip(idx, 0, len(time_axis_s) - 1))])

    def _f_mhz(idx: int) -> float:
        if freq_axis_mhz.size == 0:
            return float(idx)
        return float(freq_axis_mhz[int(np.clip(idx, 0, len(freq_axis_mhz) - 1))])

    def _iso(seconds: float) -> str | None:
        if obs_start_dt is None:
            return None
        ts = obs_start_dt + timedelta(seconds=float(seconds))
        return ts.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    events: list[dict] = []
    for seg_start_idx, seg_end_idx in segments:
        if seg_end_idx - seg_start_idx + 1 < int(min_event_windows):
            continue

        start_s = _t_seconds(int(t_starts[seg_start_idx]))
        end_s = _t_seconds(int(t_starts[seg_end_idx] + win_width))

        seg_range = set(t_starts[seg_start_idx : seg_end_idx + 1].tolist())
        sel = np.array([c[2] in seg_range for c in coords], dtype=bool)
        if np.any(sel):
            seg_coords = coords[sel]
            seg_scores_full = window_scores[sel]
            strong = seg_scores_full >= float(threshold)
            if np.any(strong):
                seg_coords = seg_coords[strong]
                seg_scores = seg_scores_full[strong]
            else:
                seg_scores = seg_scores_full
            f_low = _f_mhz(int(np.min(seg_coords[:, 0])))
            f_high = _f_mhz(int(np.max(seg_coords[:, 1])) - 1)
        else:
            seg_scores = smooth_scores[seg_start_idx : seg_end_idx + 1]
            f_low = float(np.min(freq_axis_mhz)) if freq_axis_mhz.size else 0.0
            f_high = float(np.max(freq_axis_mhz)) if freq_axis_mhz.size else 0.0

        events.append({
            "start_utc": _iso(start_s),
            "end_utc": _iso(end_s),
            "start_s": round(float(start_s), 3),
            "end_s": round(float(end_s), 3),
            "peak_score": round(float(np.max(seg_scores)), 4),
            "mean_score": round(float(np.mean(seg_scores)), 4),
            "freq_band_mhz": [
                round(float(min(f_low, f_high)), 3),
                round(float(max(f_low, f_high)), 3),
            ],
        })
    return events


def _extract_visual_fallback_events(
    data_raw: np.ndarray,
    freqs: np.ndarray,
    time_axis_s: np.ndarray,
    obs_start_dt,
    file_score: float,
) -> list[dict]:
    """Locate visually obvious vertical transients when MIL says burst but
    Sahan's window-event heuristic cannot form a contiguous event.

    This is a fallback localizer, not a replacement for the calibrated CNN+MIL
    score. It uses row-wise background suppression similar to the portal's
    display pipeline, then searches for short high-percentile time spikes above
    30 MHz so low-frequency clutter and horizontal RFI do not dominate.
    """
    arr = np.asarray(data_raw, dtype=np.float32)
    freq_arr = np.asarray(freqs, dtype=float)
    time_arr = np.asarray(time_axis_s, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 8 or freq_arr.size == 0:
        return []

    baseline = np.nanpercentile(arr, 25.0, axis=1, keepdims=True).astype(np.float32)
    bg = arr - baseline
    row_med = np.nanmedian(bg, axis=1, keepdims=True)
    row_mad = np.nanmedian(np.abs(bg - row_med), axis=1, keepdims=True)
    norm = (bg - row_med) / (row_mad + np.float32(1e-6))

    band_mask = freq_arr >= 30.0
    if int(np.count_nonzero(band_mask)) < 8:
        band_mask = np.ones_like(freq_arr, dtype=bool)

    score = np.nanpercentile(norm[band_mask, :], 98.0, axis=0)
    score = median_filter(score.astype(np.float32), size=9, mode="nearest")
    finite = score[np.isfinite(score)]
    if finite.size == 0:
        return []

    med = float(np.median(finite))
    mad = float(np.median(np.abs(finite - med)))
    sigma = 1.4826 * mad
    if not np.isfinite(sigma) or sigma <= 1e-6:
        sigma = float(np.nanstd(finite))
    if not np.isfinite(sigma) or sigma <= 1e-6:
        return []

    z = (score - med) / sigma
    raw_segments = _find_contiguous_segments(z >= 8.0)
    if not raw_segments:
        return []

    merged: list[tuple[int, int]] = []
    for start, end in raw_segments:
        if merged and start - merged[-1][1] <= 16:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    def _t_seconds(idx: int) -> float:
        if time_arr.size == 0:
            return float(idx)
        return float(time_arr[int(np.clip(idx, 0, len(time_arr) - 1))])

    def _iso(seconds: float) -> str | None:
        if obs_start_dt is None:
            return None
        ts = obs_start_dt + timedelta(seconds=float(seconds))
        return ts.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    events: list[dict] = []
    band_indices = np.where(band_mask)[0]
    for start, end in merged:
        if end - start + 1 < 4:
            continue
        s0 = max(0, start - 8)
        s1 = min(arr.shape[1] - 1, end + 8)
        local_band = norm[band_mask, s0 : s1 + 1]
        if local_band.size == 0:
            continue

        strong_threshold = np.nanpercentile(local_band, 99.0)
        strong = np.argwhere(local_band >= strong_threshold)
        if strong.size:
            f_idx = band_indices[strong[:, 0]]
            f_low = float(np.nanmin(freq_arr[f_idx]))
            f_high = float(np.nanmax(freq_arr[f_idx]))
        else:
            f_low = float(np.nanmin(freq_arr[band_mask]))
            f_high = float(np.nanmax(freq_arr[band_mask]))

        start_s = _t_seconds(s0)
        end_s = _t_seconds(s1)
        local_z = float(np.nanmax(z[start : end + 1]))
        events.append({
            "start_utc": _iso(start_s),
            "end_utc": _iso(end_s),
            "start_s": round(float(start_s), 3),
            "end_s": round(float(end_s), 3),
            "peak_score": round(float(file_score), 4),
            "mean_score": round(float(file_score), 4),
            "freq_band_mhz": [
                round(float(min(f_low, f_high)), 3),
                round(float(max(f_low, f_high)), 3),
            ],
            "source": "visual_fallback",
            "localizer_z": round(local_z, 2),
        })

    events.sort(key=lambda ev: ev.get("localizer_z", 0.0), reverse=True)
    return events[:3]


# ── Public entry point ────────────────────────────────────────────────────────

def detect_bursts(
    data_raw: np.ndarray,
    freqs: np.ndarray,
    time_arr_s: np.ndarray,
    obs_start_dt,
) -> dict:
    """Run the full detection pipeline on one raw CALLISTO spectrogram.

    Mirrors infer/deploy.predict_with_deploy_model(): model-specific
    preprocessing → 128×128 windowing → CNN scoring → MIL bag pooling →
    event extraction. Returns a JSON-serialisable dict.
    """
    bundle = _load_bundle()
    cfg = bundle["cfg"]
    inf_cfg = cfg.get("inference", {})

    t0 = time.perf_counter()

    x_proc = _preprocess_for_model(data_raw, cfg.get("preprocess", {}))
    windows_np, coords = _extract_windows(x_proc, cfg.get("window", {}))
    file_score, win_scores = _score_windows(
        bundle["model"], bundle["mil_head"], windows_np,
        batch_size=int(inf_cfg.get("batch_size", 64)),
    )

    events = _extract_events(
        window_scores=win_scores,
        coords=coords,
        time_axis_s=np.asarray(time_arr_s, dtype=float),
        freq_axis_mhz=np.asarray(freqs, dtype=float),
        obs_start_dt=obs_start_dt,
        threshold=float(bundle["threshold"]),
        smooth_kernel=int(inf_cfg.get("smooth_kernel", 5)),
        min_event_windows=int(inf_cfg.get("min_event_windows", 3)),
    )
    event_source = "sahan_window_postprocess"
    threshold = float(bundle["threshold"])
    candidate_floor = 0.40
    if not events:
        visual_events = _extract_visual_fallback_events(
            data_raw=data_raw,
            freqs=np.asarray(freqs, dtype=float),
            time_axis_s=np.asarray(time_arr_s, dtype=float),
            obs_start_dt=obs_start_dt,
            file_score=float(file_score),
        )
        strongest_visual = max((float(ev.get("localizer_z", 0.0)) for ev in visual_events), default=0.0)
        widest_band = max(
            (
                abs(
                    float(ev.get("freq_band_mhz", [0.0, 0.0])[1])
                    - float(ev.get("freq_band_mhz", [0.0, 0.0])[0])
                )
                for ev in visual_events
            ),
            default=0.0,
        )
        # Some stations/focus codes (e.g. ALASKA-COHOE on 2026-06-29) are
        # clear false negatives for the trained CNN+MIL model. Keep Sahan's
        # calibrated score untouched, but surface very strong visual transients
        # as candidates so the user can inspect them instead of silently losing
        # the event.
        strong_visual_candidate = (
            (strongest_visual >= 10.0 and widest_band >= 5.0)
            or strongest_visual >= 14.0
        )
        if visual_events and (file_score >= candidate_floor or strong_visual_candidate):
            events = visual_events
            event_source = "visual_fallback" if file_score >= threshold else "visual_candidate"

    return {
        "model_version": bundle["model_version"],
        "bundle_name": bundle["bundle_name"],
        "threshold": threshold,
        "file_score": round(float(file_score), 4),
        "is_burst": bool(file_score >= threshold),
        "is_candidate": bool(len(events) > 0 and (file_score >= candidate_floor or event_source == "visual_candidate")),
        "n_windows": int(windows_np.shape[0]),
        "events": events,
        "event_source": event_source,
        "inference_ms": round((time.perf_counter() - t0) * 1000.0, 1),
    }
