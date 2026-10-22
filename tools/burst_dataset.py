"""Build the burst-type detection dataset from the Wang et al. (2025) annotations.

Subcommands:
  split      group images by observation day and assign whole days to
             train/val/test, so one event seen by several stations never lands
             in two splits.
  negatives  pick FITS files without bursts (no event in the monthly
             e-CALLISTO burst list within a margin) from the same stations
             and period, and download them.
  convert    render every FITS with the portal's processing and write the
             YOLO dataset (images, labels and data.yaml).
  repeat     write a training list with repeat factor sampling (Gupta et al.
             2019, LVIS) so images with rare classes are seen more often.
  catalog    list archive files containing type II, IV or V events of the
             monthly burst lists, seen by the dataset's receivers.
  pseudo     box those files with a trained detector: the box comes from the
             model, the type from the burst list.
"""

from __future__ import annotations

import argparse
import http.client
import json
import random
import re
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

SPLITS = {"train": 0.70, "val": 0.15, "test": 0.15}
ARCHIVE_URL = "http://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto"
BURSTLIST_URL = "http://soleil.i4ds.ch/solarradio/data/BurstLists/2010-yyyy_Monstein"
FILE_SECONDS = 900
NEGATIVE_MARGIN = timedelta(minutes=30)
# Matplotlib axes of the 800x600 dataset images (x0, y0, x1, y1), measured on
# 300 images: the plot always spans the whole file in time and frequency.
PLOT_AREA = (100, 72, 720, 480)


def _day(file_name: str) -> str:
    # STATION_YYYYMMDD_HHMMSS_FC.jpg
    return file_name.rsplit("_", 3)[1]


def load_annotations(coco_root: Path) -> list[dict]:
    """Return one record per image: file name, day and list of (class, bbox)."""
    records = []
    for part in ("train2017", "val2017"):
        coco = json.loads((coco_root / "annotations" / f"instances_{part}.json").read_text())
        names = {c["id"]: c["name"] for c in coco["categories"]}
        boxes = defaultdict(list)
        for ann in coco["annotations"]:
            boxes[ann["image_id"]].append((names[ann["category_id"]], ann["bbox"]))
        for image in coco["images"]:
            records.append({
                "file": image["file_name"],
                "day": _day(image["file_name"]),
                "boxes": boxes[image["id"]],
            })
    return records


def _class_share_error(assignment: dict[str, str], day_counts: dict[str, Counter]) -> float:
    """Sum over classes of the squared gap between each split's box share and its target."""
    totals = Counter()
    per_split = {name: Counter() for name in SPLITS}
    for day, split in assignment.items():
        per_split[split].update(day_counts[day])
        totals.update(day_counts[day])
    error = 0.0
    for cls, total in totals.items():
        for split, target in SPLITS.items():
            error += (per_split[split][cls] / total - target) ** 2
    return error


def split_days(records: list[dict], seed: int = 0, tries: int = 2000) -> dict[str, str]:
    """Random 70/15/15 split of days; keep the draw whose class shares are closest to target."""
    day_counts: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        day_counts[record["day"]].update(cls for cls, _ in record["boxes"])
    days = sorted(day_counts)
    n_train = round(len(days) * SPLITS["train"])
    n_val = round(len(days) * SPLITS["val"])
    rng = random.Random(seed)
    best, best_error = None, float("inf")
    for _ in range(tries):
        rng.shuffle(days)
        assignment = {d: "train" for d in days[:n_train]}
        assignment.update({d: "val" for d in days[n_train:n_train + n_val]})
        assignment.update({d: "test" for d in days[n_train + n_val:]})
        error = _class_share_error(assignment, day_counts)
        if error < best_error:
            best, best_error = assignment, error
    return best


def _summary(records: list[dict], assignment: dict[str, str]) -> str:
    lines = []
    for split in SPLITS:
        chosen = [r for r in records if assignment[r["day"]] == split]
        classes = Counter(cls for r in chosen for cls, _ in r["boxes"])
        days = {r["day"] for r in chosen}
        lines.append(f"{split:5s} days={len(days):4d} images={len(chosen):5d} " + " ".join(
            f"{cls}={classes[cls]}" for cls in sorted(classes)))
    return "\n".join(lines)


def _fetch(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (OSError, http.client.HTTPException):  # includes truncated responses
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def burst_list_events(months: list[tuple[int, int]]) -> tuple[list[dict], set[str]]:
    """Parse the monthly e-CALLISTO burst lists.

    Returns the events ({start, end, type, stations}) and the days marked as
    missing data. The lists contain typos such as "11_25"; a day with an
    unreadable event is reported as missing rather than guessed.
    """
    events, missing_days = [], set()
    for year, month in months:
        text = _fetch(f"{BURSTLIST_URL}/{year:04d}/e-CALLISTO_{year:04d}_{month:02d}.txt").decode("utf-8", "replace")
        for line in text.splitlines():
            match = re.match(r"(\d{8})\s+(\S+)", line)
            if not match:
                continue
            day, span = match.groups()
            times = re.fullmatch(r"(\d{1,2})\D(\d{2})-(\d{1,2})\D(\d{2})", span)
            if not times:
                missing_days.add(day)
                continue
            h0, m0, h1, m1 = map(int, times.groups())
            base = datetime.strptime(day, "%Y%m%d")
            t0 = base + timedelta(hours=h0, minutes=m0)
            t1 = base + timedelta(hours=h1, minutes=m1 + 1)
            if t1 < t0:  # event crossing midnight
                t1 += timedelta(days=1)
            fields = re.split(r"\t+", line.strip())
            events.append({
                "start": t0, "end": t1,
                "type": fields[2].strip() if len(fields) > 2 else "",
                "stations": [s.strip() for s in fields[3].split(",")] if len(fields) > 3 else [],
            })
    return events, missing_days


def burst_intervals(months: list[tuple[int, int]]) -> tuple[list[tuple[datetime, datetime]], set[str]]:
    """Return every listed burst interval (any station) and the days marked as missing data."""
    events, missing_days = burst_list_events(months)
    return [(e["start"], e["end"]) for e in events], missing_days


def _file_start(stem: str) -> datetime:
    _, day, hms, _ = stem.rsplit("_", 3)
    return datetime.strptime(day + hms, "%Y%m%d%H%M%S")


def _is_quiet(start: datetime, intervals: list[tuple[datetime, datetime]]) -> bool:
    lo, hi = start - NEGATIVE_MARGIN, start + timedelta(seconds=FILE_SECONDS) + NEGATIVE_MARGIN
    return not any(t0 < hi and t1 > lo for t0, t1 in intervals)


def pick_negatives(records: list[dict], assignment: dict[str, str], count: int,
                   per_day: int = 3, seed: int = 0) -> list[dict]:
    """Sample quiet files from the dataset's own stations and receivers over the same period."""
    rng = random.Random(seed)
    receivers = sorted({r["file"].rsplit("_", 3)[0] + "_" + r["file"].rsplit("_", 3)[3].split(".")[0]
                        for r in records})
    used = {r["file"].rsplit(".", 1)[0] for r in records}
    first = datetime.strptime(min(r["day"] for r in records), "%Y%m%d")
    last = datetime.strptime(max(r["day"] for r in records), "%Y%m%d")
    months = sorted({(d.year, d.month) for d in (first + timedelta(days=i) for i in range((last - first).days + 1))})
    intervals, missing_days = burst_intervals(months)
    by_day = defaultdict(list)
    for t0, t1 in intervals:
        by_day[t0.strftime("%Y%m%d")].append((t0, t1))

    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    days = [d for d in days if d.strftime("%Y%m%d") not in missing_days]
    rng.shuffle(days)
    chosen: list[dict] = []
    for day in days:
        if len(chosen) >= count:
            break
        key = day.strftime("%Y%m%d")
        listing = _fetch(f"{ARCHIVE_URL}/{day:%Y/%m/%d}/").decode("utf-8", "replace")
        stems = sorted(set(re.findall(r'href="([^"]+)\.fit\.gz"', listing)))
        nearby = by_day[key] + by_day[(day - timedelta(days=1)).strftime("%Y%m%d")] \
            + by_day[(day + timedelta(days=1)).strftime("%Y%m%d")]
        candidates = [s for s in stems
                      if s not in used and s.rsplit("_", 3)[0] + "_" + s.rsplit("_", 3)[3] in receivers
                      and _is_quiet(_file_start(s), nearby)]
        rng.shuffle(candidates)
        stations = set()
        for stem in candidates:
            station = stem.rsplit("_", 3)[0]
            if station in stations:
                continue
            stations.add(station)
            split = assignment.get(key) or rng.choices(list(SPLITS), weights=list(SPLITS.values()))[0]
            chosen.append({"file": stem, "day": key, "split": split})
            if len(stations) >= per_day or len(chosen) >= count:
                break
    return chosen


def catalog_files(records: list[dict], months: list[tuple[int, int]],
                  types: tuple[str, ...] = ("type2", "type4", "type5")) -> list[dict]:
    """Archive files that contain a listed event of a rare type, seen by one of the dataset's receivers.

    Doubtful stations (in parentheses in the list) and types with a question
    mark are skipped. Each file keeps the event type and interval so a box can
    later be matched to it.
    """
    list_type = {"type2": "II", "type4": "IV", "type5": "V"}
    wanted = {list_type[t]: t for t in types}
    receivers = {r["file"].rsplit("_", 3)[0].upper() + "_" + r["file"].rsplit("_", 3)[3].split(".")[0]
                 for r in records}
    events, _ = burst_list_events(months)
    events = [e for e in events if e["type"] in wanted]
    by_day = defaultdict(list)
    for event in events:
        by_day[event["start"].date()].append(event)

    chosen = {}
    for day, day_events in sorted(by_day.items()):
        listing = _fetch(f"{ARCHIVE_URL}/{day:%Y/%m/%d}/").decode("utf-8", "replace")
        stems = sorted(set(re.findall(r'href="([^"]+)\.fit\.gz"', listing)))
        for event in day_events:
            stations = {s.upper() for s in event["stations"] if s and not s.startswith("(")}
            for stem in stems:
                station, _, _, focus = stem.rsplit("_", 3)
                start = _file_start(stem)
                if (station.upper() in stations and f"{station.upper()}_{focus}" in receivers
                        and start < event["end"] and start + timedelta(seconds=FILE_SECONDS) > event["start"]):
                    chosen.setdefault(stem, []).append({
                        "type": wanted[event["type"]],
                        "start": event["start"].isoformat(), "end": event["end"].isoformat(),
                    })
    return [{"file": stem, "events": found} for stem, found in sorted(chosen.items())]


EVENT_MARGIN = timedelta(minutes=1)  # the burst lists have minute resolution
# 5th percentile of the box duration per class in the Wang et al. training
# labels; shorter boxes inside a type II/IV/V event are usually type III bursts.
MIN_BOX_SECONDS = {"type2": 86.0, "type4": 163.0, "type5": 41.0}


def predict_boxes(model_path: Path, images: list[Path], conf: float,
                  agnostic: bool = True) -> dict[str, list[list[float]]]:
    """Detections per image as [x0, y0, x1, y1, confidence, class] in image fractions."""
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    found = {}
    for i in range(0, len(images), 32):
        for result in model.predict([str(p) for p in images[i:i + 32]], imgsz=1024, conf=conf,
                                    agnostic_nms=agnostic, verbose=False):
            boxes = result.boxes
            found[Path(result.path).stem] = [
                [*xyxy, c, k] for xyxy, c, k in zip(boxes.xyxyn.tolist(), boxes.conf.tolist(),
                                                     boxes.cls.tolist(), strict=True)
            ]
    return found


def _span(start: datetime, x0: float, x1: float) -> tuple[datetime, datetime]:
    """Time interval of a box given as fractions of a file that begins at `start`."""
    return start + timedelta(seconds=x0 * FILE_SECONDS), start + timedelta(seconds=x1 * FILE_SECONDS)


def _inside(small: list[float], big: list[float], share: float = 0.9) -> bool:
    """True when at least `share` of the small box area lies inside the big one."""
    w = max(0.0, min(small[2], big[2]) - max(small[0], big[0]))
    h = max(0.0, min(small[3], big[3]) - max(small[1], big[1]))
    area = (small[2] - small[0]) * (small[3] - small[1])
    return area > 0 and w * h / area >= share


def _drop_nested(boxes: list[tuple[str, list[float]]]) -> list[tuple[str, list[float]]]:
    """Remove boxes almost entirely inside a larger box of the same file."""
    def area(b: list[float]) -> float:
        return (b[2] - b[0]) * (b[3] - b[1])

    ordered = sorted(boxes, key=lambda item: area(item[1]), reverse=True)
    kept: list[tuple[str, list[float]]] = []
    for kind, box in ordered:
        if not any(_inside(box, other) for _, other in kept):
            kept.append((kind, box))
    return kept


def pseudo_labels(files: list[dict], detections: dict[str, list[list[float]]], conf: float,
                  min_duration: bool = True, types: tuple[str, ...] = ("type2", "type4", "type5"),
                  fill: dict[str, list[list[float]]] | None = None,
                  fill_conf: float = 0.5) -> dict[str, list[tuple[str, list[float]]]]:
    """Keep detections that overlap a listed event and give them that event's type.

    A detection overlapping several events takes the type of the largest
    overlap; boxes nested inside a larger one are dropped. Files with an
    event of a type left out are skipped, so that burst is never shown as
    background. With `fill` (class-aware detections), confident type III/IIIs
    detections outside the events are kept too, for the same reason.
    """
    labels = {}
    for entry in files:
        if any(e["type"] not in types for e in entry["events"]):
            continue
        stem, start = entry["file"], _file_start(entry["file"])
        events = [(datetime.fromisoformat(e["start"]) - EVENT_MARGIN,
                   datetime.fromisoformat(e["end"]) + EVENT_MARGIN, e["type"]) for e in entry["events"]]
        kept = []
        for x0, y0, x1, y1, score, *_ in detections.get(stem, []):
            if score < conf:
                continue
            b0, b1 = _span(start, x0, x1)
            overlap, kind = max((min(b1, t1) - max(b0, t0), kind) for t0, t1, kind in events)
            if overlap <= timedelta(0):
                continue
            if min_duration and (x1 - x0) * FILE_SECONDS < MIN_BOX_SECONDS[kind]:
                continue
            kept.append((kind, [x0, y0, x1, y1]))
        kept = _drop_nested(kept)
        if not kept:
            continue
        for x0, y0, x1, y1, score, cls in (fill or {}).get(stem, []):
            b0, b1 = _span(start, x0, x1)
            box = [x0, y0, x1, y1]
            if (score >= fill_conf and int(cls) in (1, 2)  # type3, type3s
                    and all(b1 <= t0 or b0 >= t1 for t0, t1, _ in events)
                    and not any(_inside(box, other) or _inside(other, box) for _, other in kept)):
                kept.append((("type3", "type3s")[int(cls) - 1], box))
        labels[stem] = kept
    return labels


def download(stems: list[str], output: Path, workers: int = 4) -> list[str]:
    """Download archive FITS files that are not already present; return the ones that failed."""
    output.mkdir(parents=True, exist_ok=True)

    def get(stem: str) -> str | None:
        target = output / f"{stem}.fit.gz"
        if target.exists() and target.stat().st_size > 0:
            return None
        day = stem.rsplit("_", 3)[1]
        try:
            target.write_bytes(_fetch(f"{ARCHIVE_URL}/{day[:4]}/{day[4:6]}/{day[6:]}/{stem}.fit.gz"))
        except OSError:
            return stem
        return None

    with ThreadPoolExecutor(workers) as pool:
        return [stem for stem in pool.map(get, stems) if stem]


def plot_box_to_fractions(bbox: list[float]) -> tuple[float, float, float, float] | None:
    """COCO pixel box (x, y, w, h) on the dataset image -> plot fractions (x0, y0, x1, y1)."""
    px0, py0, px1, py1 = PLOT_AREA
    x, y, w, h = bbox

    def clip(value: float) -> float:
        return min(max(value, 0.0), 1.0)

    x0, x1 = clip((x - px0) / (px1 - px0)), clip((x + w - px0) / (px1 - px0))
    y0, y1 = clip((y - py0) / (py1 - py0)), clip((y + h - py0) / (py1 - py0))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _convert_one(job: tuple[Path, Path, Path, list]) -> str:
    """Render one FITS and write its image and YOLO label; return a status word."""
    import numpy as np
    from astropy.io import fits
    from PIL import Image

    from backend import main as core
    from backend.burst_types import CLASSES, spectrogram_image

    fits_path, image_path, label_path, boxes = job
    try:
        with fits.open(fits_path) as hdul:
            data, freqs, _ = core._load_callisto_data(hdul)
    except (OSError, ValueError):
        return "unreadable"
    if not np.all(np.diff(np.asarray(freqs)) <= 0):
        return "not_descending"  # the dataset images assume high frequency on top
    Image.fromarray(spectrogram_image(data)).save(image_path)
    lines = []
    for name, bbox in boxes:
        box = plot_box_to_fractions(bbox)
        if box:
            x0, y0, x1, y1 = box
            lines.append(f"{CLASSES.index(name)} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} "
                         f"{x1 - x0:.6f} {y1 - y0:.6f}")
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return "ok"


def convert(records: list[dict], negatives: list[dict], assignment: dict[str, str],
            fits_dir: Path, negative_dir: Path, output: Path, workers: int = 6) -> Counter:
    """Write output/{images,labels}/{split}/ and output/data.yaml."""
    from concurrent.futures import ProcessPoolExecutor

    from backend.burst_types import CLASSES

    jobs = []
    samples = [(r["file"].rsplit(".", 1)[0], assignment[r["day"]], r["boxes"], fits_dir) for r in records]
    samples += [(n["file"], n["split"], [], negative_dir) for n in negatives]
    for stem, split, boxes, folder in samples:
        for kind in ("images", "labels"):
            (output / kind / split).mkdir(parents=True, exist_ok=True)
        jobs.append((folder / f"{stem}.fit.gz", output / "images" / split / f"{stem}.png",
                     output / "labels" / split / f"{stem}.txt", boxes))
    with ProcessPoolExecutor(workers) as pool:
        status = Counter(pool.map(_convert_one, jobs, chunksize=16))
    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(CLASSES))
    (output / "data.yaml").write_text(
        f"path: {output.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names}\n")
    return status


def repeat_factors(label_files: list[Path], threshold: float) -> dict[Path, float]:
    """Repeat factor per image: max over its classes of max(1, sqrt(t / f(c))).

    f(c) is the fraction of training images that contain class c. Images
    without boxes keep a factor of 1.
    """
    classes = {path: {line.split()[0] for line in path.read_text().splitlines() if line.strip()}
               for path in label_files}
    counts = Counter(c for found in classes.values() for c in found)
    factor = {c: max(1.0, (threshold / (n / len(label_files))) ** 0.5) for c, n in counts.items()}
    return {path: max((factor[c] for c in found), default=1.0) for path, found in classes.items()}


def _image_for(label: Path) -> Path:
    """.../labels/<rest>.txt -> .../images/<rest>.png (the layout Ultralytics expects)."""
    parts = list(label.parts)
    parts[len(parts) - 1 - parts[::-1].index("labels")] = "images"
    return Path(*parts).with_suffix(".png")


def write_repeated_list(yolo_root: Path, threshold: float = 0.1, seed: int = 0,
                        extra: tuple[Path, ...] = (), name: str = "repeat") -> tuple[Path, Counter]:
    """Write train_<name>.txt and data_<name>.yaml next to data.yaml.

    `extra` folders (with images/ and labels/) are added to the training set
    only. Fractional factors use stochastic rounding with a fixed seed, so the
    expected number of copies equals the factor and the list is reproducible.
    """
    rng = random.Random(seed)
    labels = sorted((yolo_root / "labels" / "train").glob("*.txt"))
    for folder in extra:
        labels += sorted((folder / "labels").glob("*.txt"))
    lines, copies = [], Counter()
    for label, r in repeat_factors(labels, threshold).items():
        n = int(r) + (rng.random() < r - int(r))
        lines += [_image_for(label).as_posix()] * n
        copies[n] += 1
    (yolo_root / f"train_{name}.txt").write_text("\n".join(lines) + "\n")
    data = (yolo_root / "data.yaml").read_text().replace("train: images/train", f"train: train_{name}.txt")
    target = yolo_root / f"data_{name}.yaml"
    target.write_text(data)
    return target, copies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    split = sub.add_parser("split", help="assign observation days to train/val/test")
    split.add_argument("coco_root", type=Path, help="folder with annotations/instances_*.json")
    split.add_argument("output", type=Path, help="JSON file to write {day: split}")
    split.add_argument("--seed", type=int, default=0)
    negatives = sub.add_parser("negatives", help="select and download burst-free FITS files")
    negatives.add_argument("coco_root", type=Path)
    negatives.add_argument("split_file", type=Path, help="output of the split command")
    negatives.add_argument("output", type=Path, help="JSON file to write the chosen files")
    negatives.add_argument("fits_dir", type=Path, help="folder to download the FITS into")
    negatives.add_argument("--count", type=int, default=875)
    negatives.add_argument("--seed", type=int, default=0)
    conv = sub.add_parser("convert", help="write the YOLO dataset")
    conv.add_argument("coco_root", type=Path)
    conv.add_argument("split_file", type=Path)
    conv.add_argument("negatives_file", type=Path)
    conv.add_argument("fits_dir", type=Path, help="FITS of the annotated images")
    conv.add_argument("negative_dir", type=Path, help="FITS of the negatives")
    conv.add_argument("output", type=Path)
    cat = sub.add_parser("catalog", help="list archive files with rare-type events from the burst lists")
    cat.add_argument("coco_root", type=Path)
    cat.add_argument("output", type=Path, help="JSON file to write the chosen files and their events")
    cat.add_argument("--first", default="2023-01", help="first month, YYYY-MM")
    cat.add_argument("--last", default="2024-12", help="last month, YYYY-MM")
    cat.add_argument("--download", type=Path, help="also download the FITS into this folder")
    pse = sub.add_parser("pseudo", help="box the catalog files with a trained detector")
    pse.add_argument("catalog_file", type=Path, help="output of the catalog command")
    pse.add_argument("images", type=Path, help="rendered images of the catalog files")
    pse.add_argument("model", type=Path, help="trained weights (best.pt)")
    pse.add_argument("detections", type=Path, help="JSON cache of the raw detections")
    pse.add_argument("--conf", type=float, nargs="+", default=[0.25, 0.4, 0.5])
    pse.add_argument("--no-min-duration", action="store_true")
    pse.add_argument("--types", nargs="+", default=["type2", "type4", "type5"])
    pse.add_argument("--fill", type=Path, help="JSON cache of class-aware detections used to add type III boxes")
    pse.add_argument("--output", type=Path, help="write images/ and labels/ for the first --conf here")
    rep = sub.add_parser("repeat", help="write a repeat-factor-sampled training list")
    rep.add_argument("yolo_root", type=Path, help="output folder of the convert command")
    rep.add_argument("--threshold", type=float, default=0.1,
                     help="classes in fewer than this fraction of images are oversampled")
    rep.add_argument("--extra", type=Path, nargs="*", default=[], help="extra training folders (images/, labels/)")
    rep.add_argument("--name", default="repeat")
    args = parser.parse_args()

    if args.command == "repeat":
        target, copies = write_repeated_list(args.yolo_root, args.threshold, extra=tuple(args.extra), name=args.name)
        print(target, "images by number of copies:", dict(sorted(copies.items())))
        return
    if args.command == "pseudo":
        files = json.loads(args.catalog_file.read_text())
        images = sorted(args.images.glob("*.png"))

        def cached(path: Path, agnostic: bool) -> dict:
            if not path.exists():
                path.write_text(json.dumps(predict_boxes(args.model, images, min(args.conf), agnostic)))
            return json.loads(path.read_text())

        detections = cached(args.detections, agnostic=True)
        fill = cached(args.fill, agnostic=False) if args.fill else None
        options = dict(min_duration=not args.no_min_duration, types=tuple(args.types), fill=fill)
        for conf in args.conf:
            labels = pseudo_labels(files, detections, conf, **options)
            boxes = Counter(kind for found in labels.values() for kind, _ in found)
            print(f"conf={conf}: files={len(labels)} boxes={dict(sorted(boxes.items()))}")
        if args.output:
            classes = ("type2", "type3", "type3s", "type4", "type5")  # backend.burst_types.CLASSES
            for kind in ("images", "labels"):
                (args.output / kind).mkdir(parents=True, exist_ok=True)
            for stem, found in pseudo_labels(files, detections, args.conf[0], **options).items():
                (args.output / "labels" / f"{stem}.txt").write_text("".join(
                    f"{classes.index(kind)} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}\n"
                    for kind, (x0, y0, x1, y1) in found))
                image = args.output / "images" / f"{stem}.png"
                if not image.exists():
                    image.hardlink_to(args.images / f"{stem}.png")
        return

    records = load_annotations(args.coco_root)
    if args.command == "split":
        assignment = split_days(records, seed=args.seed)
        args.output.write_text(json.dumps(dict(sorted(assignment.items())), indent=1))
        print(_summary(records, assignment))
    elif args.command == "negatives":
        assignment = json.loads(args.split_file.read_text())
        chosen = pick_negatives(records, assignment, args.count, seed=args.seed)
        args.output.write_text(json.dumps(chosen, indent=1))
        failed = download([c["file"] for c in chosen], args.fits_dir)
        print(f"negatives={len(chosen)} failed_downloads={len(failed)}",
              dict(Counter(c["split"] for c in chosen)))
    elif args.command == "catalog":
        first, last = (datetime.strptime(m, "%Y-%m") for m in (args.first, args.last))
        months = [(y, m) for y in range(first.year, last.year + 1) for m in range(1, 13)
                  if first <= datetime(y, m, 1) <= last]
        files = catalog_files(records, months)
        args.output.write_text(json.dumps(files, indent=1))
        print(f"files={len(files)}", dict(Counter(e["type"] for f in files for e in f["events"][:1])))
        if args.download:
            failed = download([f["file"] for f in files], args.download)
            print(f"failed_downloads={len(failed)}")
    elif args.command == "convert":
        status = convert(records, json.loads(args.negatives_file.read_text()),
                         json.loads(args.split_file.read_text()),
                         args.fits_dir, args.negative_dir, args.output)
        print(dict(status))


if __name__ == "__main__":
    main()
