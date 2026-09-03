# Third-party notices and provenance register

This file records the provenance that is currently known. It is not a substitute for the licence text of each dependency.

| Component/data | Use in AstroDoncel Studio | Provenance/licence status |
|---|---|---|
| e-CALLISTO / ETHZ/FHNW archive | FITS observations and monthly burst-list fallback | External scientific data service: <https://www.e-callisto.org/Data/data.html>. Cite e-CALLISTO and verify the archive's current data-use terms for publication/redistribution. |
| Universidad de Alcalá — original AstroDoncel portal | Product reference, current Burst Reports database and published monthly fallback catalogues | External portal/data source: <https://astrodoncel.uah.es/dashboard/>. Database access is read-only and deployment-specific. Preserve every catalogue source as distinct from ML/heuristic output. |
| Sahan S. Liyanage — `e-Callisto_FITS_Analyzer` v2.8.0 | Reference processing, comparison, measurement, provenance and interaction patterns | MIT reference implementation: <https://github.com/SaanDev/e-Callisto_FITS_Analyzer>. Cite the published article <https://doi.org/10.1093/rasti/rzag056>. AstroDoncel contains adaptations, not the desktop application. |
| Sahan S. Liyanage — `Burst_No_Burst` | CNN+MIL architecture, preprocessing and supplied weights | Origin described in `MODEL_CARD.md`. The source `model.pt` is not published. Redistribution permission for the runtime ONNX weights and the dataset licence are still pending written confirmation. |
| Sahan S. Liyanage — `ecallistolib` | Reference notebooks/library | Not required at runtime and not vendored into the application. Upstream: <https://github.com/SaanDev/ecallistolib>. |
| SunPy and Astropy ecosystem | FITS, time series and GOES access | Installed Python dependencies; retain their licence notices in any binary distribution. |
| Plotly.js / react-plotly.js | Interactive scientific plots and map | Installed npm dependencies; retain their licence notices in any bundled redistribution. |
| FastAPI, NumPy, SciPy, SQLAlchemy, ONNX Runtime, React and Vite | Application runtime/tooling | Installed dependencies governed by their respective upstream licences. |

## Project licence still required

The repository does not yet contain a root `LICENSE`. The author and Universidad de Alcalá must choose/approve it; this implementation deliberately does not invent that legal decision. Formal public distribution should wait until the project licence, exact upstream commits and model-weight permission are resolved.
