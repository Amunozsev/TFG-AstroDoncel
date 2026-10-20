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
"""

from __future__ import annotations

import argparse
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
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def burst_intervals(months: list[tuple[int, int]]) -> tuple[list[tuple[datetime, datetime]], set[str]]:
    """Return every listed burst interval (any station) and the days marked as missing data."""
    intervals, missing_days = [], set()
    for year, month in months:
        text = _fetch(f"{BURSTLIST_URL}/{year:04d}/e-CALLISTO_{year:04d}_{month:02d}.txt").decode("utf-8", "replace")
        for line in text.splitlines():
            match = re.match(r"(\d{8})\s+(\S+)", line)
            if not match:
                continue
            day, span = match.groups()
            if "#" in span:
                missing_days.add(day)
                continue
            # The lists contain typos such as "11_25"; a day with an unreadable
            # event is dropped as a negative source rather than guessed.
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
            intervals.append((t0, t1))
    return intervals, missing_days


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
    args = parser.parse_args()

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
    elif args.command == "convert":
        status = convert(records, json.loads(args.negatives_file.read_text()),
                         json.loads(args.split_file.read_text()),
                         args.fits_dir, args.negative_dir, args.output)
        print(dict(status))


if __name__ == "__main__":
    main()
