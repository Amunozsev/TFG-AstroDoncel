# Model card — AstroDoncel burst detector

## Intended use

The bundled model screens e-CALLISTO spectrograms for binary burst/no-burst candidates. Its output is an experimental aid for expert review, not an authoritative event classification, an alerting system, or a replacement for the official catalogue.

AstroDoncel never infers a solar-burst type from this network. A temporally matched official type is stored only as catalogue cross-match metadata.

## Bundle identity

- Bundle: `deploy_20260218T113917Z`
- Model version: `20260218T113917Z`
- Runtime: ONNX Runtime, CPU provider
- ONNX SHA-256: `ab40e7a529e617f64b5d9b3332519a7ffc82707dac19361e0ba3a2563fb38ecf`
- Source checkpoint SHA-256 recorded upstream: `54e071b9cf9a0013409c81d5866462b73158a98ed505bca2e0f23086a6685bb8`
- Decision threshold: `0.60`
- Exploratory candidate threshold: `0.40`

The API returns the effective threshold, candidate threshold, model version, ONNX hash, inference method and localization method with each inference.

## Processing contract

The versioned `runtime_config.json` defines the contract: non-negative `log1p`, running 0.2-quantile background with a 121-sample window, robust normalization per frequency, RFI mitigation, clipping to `[-6, 12]`, non-overlapping 128×128 windows and top-8 mean MIL pooling. Event postprocessing uses a smoothing kernel of 5 and at least 3 event windows.

The `visual_fallback` / `visual_candidate` localizer is a separate heuristic. Persisted events from it use `source=heuristic_visual`; CNN-window events use `source=ml_cnn`.

## Metrics supplied with the upstream bundle

The deployment profile reports 99 evaluation samples at threshold 0.60:

| Metric | Reported value |
|---|---:|
| PR-AUC | 0.7575 |
| ROC-AUC | 0.7808 |
| Precision | 0.7037 |
| Recall | 0.7600 |
| F1 | 0.7308 |
| False alerts/hour | 1.0218 |

These values are upstream-reported metadata, not independently reproduced by this repository. The bundle does not identify the dataset, stations, date range, class balance or train/validation/test partition well enough to audit leakage or generalization. Event recall at IoU 0.1 is not reported.

## Limitations and required validation

- Performance can change by station, receiver/focus code, epoch, frequency coverage and RFI environment.
- The network is binary; it does not distinguish Types II, III, IV or V.
- The probability is a model score and must not be interpreted as a calibrated physical probability without a calibration study.
- The visual localizer is heuristic and has no independent validation set documented here.
- Before academic claims or operational deployment, create a versioned representative dataset, freeze train/validation/test partitions, reproduce the metrics and report confidence intervals and per-station results.

## Provenance and licence status

The architecture and original deployment bundle were supplied from Sahan S. Liyanage's `Burst_No_Burst` work and adapted for ONNX serving in AstroDoncel. The source checkpoint `model.pt` is deliberately excluded from the public tree; the optional export tool requires an authorised local copy. Exact upstream commit, dataset licence and permission to redistribute the runtime `model.onnx` are not encoded in the supplied bundle and remain to be confirmed in writing. Before making a public release, obtain that permission or distribute the model separately under its applicable terms.
