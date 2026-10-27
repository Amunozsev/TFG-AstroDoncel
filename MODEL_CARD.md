# Model card — AstroDoncel Studio burst-type detector

## Intended use

The bundled model detects solar radio bursts in one e-CALLISTO FITS file and classifies each one as type II, III, IIIs (III storm), IV or V. Each detection is a box with its type, a confidence score and its extent in UTC and MHz. It is an aid for expert review, not an authoritative event classification, an alerting system or a replacement for the official catalogue. Catalogue types and model detections are kept separate.

Types IV and V are flagged as experimental in every response: they had few training examples and their test confidence intervals are wide.

## Model identity

- Architecture: YOLO11s (Ultralytics 8.4.183), fine-tuned from COCO weights
- Model version: `v4_pseudo`
- Runtime: ONNX Runtime, CPU provider (opset 17, float32, fixed 1×3×416×1024 input)
- ONNX SHA-256: `5d3540affb74a233241793ce802d41d876e76ad6449dd6e6fe7f181538e0a4ff`
- Confidence threshold: `0.32` (maximum F1 on validation, fixed before testing)
- Non-maximum suppression: per class, IoU `0.7`

`backend/model/burst_types/config.json` stores these values. The API returns the model version, ONNX hash and threshold with each inference. Detections are returned to the browser and are not stored in the catalogue.

## Processing contract

Training and inference share `backend.burst_types.spectrogram_image`: the FITS matrix as the portal shows it by default (robust background subtraction, no RFI filter, 2–98 % intensity clip), in FITS channel order, resized to 1024×400 grey levels. The image is padded with 8 rows (value 114) above and below to 416×1024 and repeated on three channels. A box maps to time proportionally to the file samples and to frequency through the FITS channel it covers.

## Training data

- **Labelled data:** dataset of Wang et al. (2025, ApJS): 8,752 e-CALLISTO images (May 2020 – Nov 2022, 56 stations) with 10,833 boxes (III 8,210; IIIs 1,857; II 464; V 237; IV 65). Every image was re-rendered from its original FITS with the contract above and its boxes were converted from the plot area to the file.
- **Negatives:** 875 burst-free files from the dataset's own stations and receivers over the same period, at least 30 min away from any event of the monthly e-CALLISTO burst list.
- **Partition:** 70/15/15 by observation day, so that files of the same event never appear in two partitions; the draw whose class shares are closest to the target was kept.
- **Rare classes:** repeat factor sampling (threshold 0.1) and catalogue-guided pseudo-labels for II, IV and V from 2023–2024 files: the model proposes the box, the e-CALLISTO burst list gives the type. The final training set has 9,592 images.
- **Augmentation:** Ultralytics defaults without flips (they would reverse time or frequency).

## Test results

Single evaluation on the held-out test partition (1,299 files: 1,175 with bursts, 124 without), COCO matching, 95 % intervals from 1,000 bootstrap resamples of images:

| Class | Boxes | mAP50 [95 % CI] | mAP50-95 |
|---|---:|---|---:|
| II | 64 | 0.75 [0.63–0.86] | 0.42 |
| III | 1,068 | 0.87 [0.85–0.89] | 0.39 |
| IIIs | 298 | 0.76 [0.72–0.81] | 0.52 |
| IV (experimental) | 10 | 0.50 [0.20–0.78] | 0.20 |
| V (experimental) | 31 | 0.74 [0.60–0.86] | 0.48 |
| Mean of classes | — | 0.72 | 0.40 |
| Any burst (type ignored) | 1,471 | 0.85 [0.83–0.87] | 0.44 |

At the operating threshold: boxes in 6 of the 124 burst-free files (4.8 %); per station (≥20 test boxes, type ignored, IoU 0.5) recall 0.73–0.93 and precision 0.61–0.92. The main confusion is III ↔ IIIs.

On the same test files the previous binary CNN+MIL detector found 54 % of the files with bursts (82 % counting its candidates) with false alarms in 43–52 % of the burst-free files; this model finds 94.5 % with 4.8 % false alarms.

## Limitations

- Train, validation and test come from the same dataset and period (different days); performance on other years, stations or receivers can be lower. A qualitative check on 2025–2026 files placed boxes on real bursts but missed some faint type III bursts.
- Types IV and V have very few examples; their metrics are uncertain.
- The confidence is a detection score, not a calibrated physical probability.
- The monthly burst list used to pick negatives is not exhaustive, so a few negatives may contain faint uncatalogued bursts.
- Per-station performance varies with frequency coverage and RFI environment.

## Reproducibility

`tools/burst_dataset.py` builds the dataset (partition, negatives, conversion, repeat factor sampling, pseudo-labels), `tools/train_burst_types.py` trains the model and `tools/evaluate_burst_types.py` computes the test report. They run in a separate environment (`requirements-train.txt`).
