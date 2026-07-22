# Third-party notices and provenance register

This file records the provenance that is currently known. It is not a substitute for the licence text of each dependency.

| Component/data | Use in AstroDoncel | Provenance/licence status |
|---|---|---|
| e-CALLISTO / ETHZ archive | FITS observations and official monthly burst lists | External scientific data service. Cite e-CALLISTO and verify the archive's current data-use terms for publication/redistribution. |
| Sahan S. Liyanage — `e-Callisto_FITS_Analyzer` | Reference processing and interaction patterns | Reference implementation. Exact upstream URL/commit and licence must be recorded before formal release. |
| Sahan S. Liyanage — `Burst_No_Burst` | CNN+MIL architecture, preprocessing and supplied weights | Origin described in `MODEL_CARD.md`. Weight redistribution permission and dataset licence are still pending written confirmation. |
| Sahan S. Liyanage — `ecallistolib` | Reference notebooks/library | Not required at runtime and not vendored into the application. Exact upstream URL/commit and licence remain to be recorded. |
| SunPy and Astropy ecosystem | FITS, time series and GOES access | Installed Python dependencies; retain their licence notices in any binary distribution. |
| Plotly.js / react-plotly.js | Interactive scientific plots and map | Installed npm dependencies; retain their licence notices in any bundled redistribution. |
| FastAPI, NumPy, SciPy, SQLAlchemy, ONNX Runtime, React and Vite | Application runtime/tooling | Installed dependencies governed by their respective upstream licences. |

## Project licence still required

The repository does not yet contain a root `LICENSE`. The author and Universidad de Alcalá must choose/approve it; this implementation deliberately does not invent that legal decision. Formal public distribution should wait until the project licence, exact upstream commits and model-weight permission are resolved.
