# AstroDoncel - Solar Radio Spectrogram Portal

Bachelor's Thesis - Universidad de Alcala - 2026  
Author: Alfonso Munoz Sevillano

AstroDoncel is an interactive web application for visualising and analysing
solar radio spectrograms from the e-CALLISTO network. It combines a React
frontend with a FastAPI backend that downloads, parses and processes CALLISTO
FITS files.

The goal of the project is to make solar radio burst inspection easier:
stations can be selected from the network, files can be browsed by date and
time, spectrograms can be compared across stations, and processing tools such
as RFI filtering, GOES/XRS context, high-resolution zoom and drift measurements
are available from the browser.

## Features

### Station Discovery

- Loads the live e-CALLISTO station list from the ETHZ archive.
- Falls back to a static station list if the archive is unreachable.
- Provides a station search box in the sidebar.
- Supports selecting one or multiple stations.
- Includes a station map view with operative/offline status.
- Shows station coordinates on a globe or flat map.
- Learns station coordinates from FITS headers when available.
- Keeps approximate fallback coordinates for known stations.
- Displays monthly burst counts per station when ETHZ burst lists are available.
- Includes day/night terminator and subsolar point overlays on the map.

### Spectrogram Loading

- Select a station and observation date.
- Lists available FITS files grouped by hour.
- Marks locally cached files.
- Loads single-station spectrograms.
- Loads multiple stations concurrently.
- Synchronises multi-station comparisons to the same 15-minute time block.
- Can read FITS files from:
  - local `data/` cache,
  - optional NAS/external data directory,
  - ETHZ remote archive.
- Auto-downloads missing files from ETHZ and caches them locally.

### Processing

- Reads CALLISTO FITS data through `astropy`.
- Extracts frequency and time axes from FITS tables, WCS headers or fallback metadata.
- Converts relative FITS time axes to absolute UTC timestamps.
- Applies robust per-frequency background subtraction.
- Optional RFI mitigation pipeline inspired by Sahan's tools:
  - persistent narrowband RFI detection by channel occupancy,
  - impulsive RFI detection through connected components,
  - channel-median inpainting,
  - adjustable thresholds from the UI.
- Computes contrast using percentile clipping.
- Exposes RFI statistics to the frontend.

### Visualisation

- Plotly heatmap spectrogram rendering.
- Multiple scientific colour scales:
  - Observatory,
  - Hot,
  - Inferno,
  - Magma,
  - Plasma,
  - Viridis,
  - Cividis,
  - Turbo,
  - Jet,
  - RdYlBu,
  - Cubehelix,
  - Bone inverted.
- Manual contrast controls with `Z min` and `Z max`.
- Optional auto-contrast on high-resolution zoom.
- Multi-station display modes:
  - stacked synchronised panels,
  - translucent overlay.
- Per-layer visibility and opacity controls.
- High-resolution zoom requests for selected time/frequency regions.
- FITS header viewer modal.
- Keyboard navigation through files with left/right arrows.

### Solar Context

- Optional GOES/XRS overlay using SunPy/Fido.
- Selects preferred GOES satellites by observation epoch.
- Clips GOES data to the visible spectrogram time window.
- Caches downloaded GOES files in `data/goes_cache/`.
- Returns a graceful unavailable response if GOES data cannot be fetched.

### Analysis Tools

- Drift ruler:
  - click two points on the spectrogram,
  - measure time difference,
  - measure frequency difference,
  - calculate drift rate in MHz/s.
- Automatic burst detection endpoint:
  - uses the bundled CNN+MIL model,
  - returns file-level probability,
  - returns candidate event intervals,
  - degrades gracefully if a custom installation misses model files.

## Architecture

```text
Browser
  React + Vite
  Plotly.js
  App.jsx
  Spectrogram.jsx
  StationsMap.jsx
        |
        | HTTP / JSON
        v
FastAPI backend
  /api/stations
  /api/stations/geo
  /api/files
  /api/spectrogram
  /api/spectrogram/combine
  /api/spectrogram/zoom
  /api/goes
  /api/burst/detect
        |
        | FITS / NetCDF / text indices
        v
ETHZ e-CALLISTO archive + NOAA/SunPy data sources
```

The frontend is responsible for interaction, layout and plotting. The backend
is responsible for I/O, FITS parsing, numerical processing and external data
fetching.

## Project Structure

```text
TFG-AstroDoncel/
  backend/
    main.py              FastAPI app, API endpoints and scientific pipeline
    burst_detect.py      CNN+MIL burst detector
    model/
      burst_detector/    Deployment bundle for ML inference
  frontend/
    public/
    src/
      App.jsx            Main application state and controls
      Spectrogram.jsx    Plotly spectrogram rendering and zoom logic
      StationsMap.jsx    Station map view
      api.js             API base URL helper
      App.css            Main styles
      index.css          Global styles
    package.json         Frontend dependencies and scripts
  data/
    goes_cache/          Local GOES cache
    station_coords.json  Learned station coordinates, if generated
  requirements.txt       Backend Python dependencies
```

`data/` is used as a local runtime cache. It should not be treated as source
code.

## Requirements

### Backend

- Python 3.12+
- `pip`
- Dependencies from `requirements.txt`

### Frontend

- Node.js 18+
- npm

## Local Installation

Clone the repository:

```powershell
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
```

Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

Install backend dependencies:

```powershell
pip install -r requirements.txt
```

Start the backend:

```powershell
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at:

```text
http://localhost:8000
```

The API documentation will be available at:

```text
http://localhost:8000/docs
```

In another terminal, install and start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

The frontend will be available at:

```text
http://localhost:5173
```

## Configuration

### Frontend API URL

The frontend reads the backend URL from:

```text
VITE_API_BASE_URL
```

If it is not set, it falls back to:

```text
http://localhost:8000
```

For local development, no extra configuration is needed if the backend runs on
port `8000`.

### Backend CORS

The backend reads allowed frontend origins from:

```text
FRONTEND_ORIGINS
```

Example:

```text
FRONTEND_ORIGINS=http://localhost:5173
```

Multiple origins can be separated by commas.

If `FRONTEND_ORIGINS` is not set, the backend allows:

```text
http://localhost:5173
http://127.0.0.1:5173
```

### Optional Data Paths

```text
ECALLISTO_DATA_DIR
```

Optional external directory for e-CALLISTO data organised as:

```text
YYYY/MM/DD/*.fit*
```

If this is not configured, the backend uses `data/` and the ETHZ archive.

```text
BURST_MODEL_DIR
```

Optional override path to the CNN+MIL burst detector model bundle. By default,
the backend uses `backend/model/burst_detector/`.

## How the Processing Pipeline Works

1. The user selects station(s), date and optionally a FITS file.
2. The frontend calls the backend API.
3. The backend searches for the FITS file:
   - first in `data/`,
   - then in `ECALLISTO_DATA_DIR` if configured,
   - then in the ETHZ archive.
4. If needed, the backend downloads the FITS file into `data/`.
5. The backend opens the FITS file with `astropy`.
6. Raw data, frequency axis, time axis and header metadata are extracted.
7. The time axis is converted to UTC timestamps.
8. Background subtraction is applied per frequency channel.
9. If enabled, RFI mitigation is applied.
10. Data are clipped and serialised to JSON.
11. The frontend renders the result with Plotly.

## API Reference

### `GET /health`

Health check endpoint.

Example response:

```json
{"status":"ok","version":"0.2.0"}
```

### `GET /api/stations`

Returns the station list.

Query parameters: none.

Response fields:

- `stations`
- `source`

### `GET /api/stations/geo`

Returns station coordinates, operative status and monthly burst counts.

Query parameters: none.

Response fields:

- `stations`
- `source`
- `operative_count`
- `total_count`
- `reference_date`
- `burst_month`
- `burst_total`
- `unmapped`
- `fits_coord_count`

### `GET /api/files`

Lists available FITS files for a station and date.

Query parameters:

- `station`
- `date` in `YYYY-MM-DD`

Example:

```text
/api/files?station=SPAIN-SIGUENZA&date=2024-05-08
```

### `GET /api/spectrogram`

Processes one station and returns one spectrogram layer.

Query parameters:

- `station`
- `date`
- `filename` optional
- `sahan_filter` optional boolean
- `max_time_bins` optional integer
- `rfi_z_thresh`
- `rfi_occupancy`
- `rfi_min_component`
- `rfi_impulsive`

### `GET /api/spectrogram/combine`

Processes several stations concurrently and aligns secondary stations to the
primary station time block.

Query parameters:

- `stations` repeated parameter
- `date`
- `filename` optional primary station file
- `sahan_filter`
- `max_time_bins`
- RFI parameters

Example:

```text
/api/spectrogram/combine?date=2024-05-08&stations=SPAIN-SIGUENZA&stations=HUMAIN
```

### `GET /api/spectrogram/zoom`

Returns a high-resolution patch for a selected time/frequency region.

Query parameters:

- `station`
- `date`
- `filename`
- `t0`
- `t1`
- `f0`
- `f1`
- RFI parameters

### `GET /api/goes`

Returns GOES/XRS flux for a date.

Query parameters:

- `date`

### `GET /api/burst/detect`

Runs CNN+MIL burst detection on one FITS file.

Query parameters:

- `station`
- `date`
- `filename`

If the model dependencies or bundle files are missing in a custom installation,
the endpoint returns an unavailable response rather than failing backend startup.

Inference uses the bundled ONNX model through ONNX Runtime. PyTorch is only a
development dependency for re-exporting or retraining the model.

### Catalogue, statistics and analysis

- `GET /api/bursts?start=YYYY-MM-DD&end=YYYY-MM-DD` ingests and queries official burst reports.
- `GET /api/stats/stations` and `GET /api/stats/timeline` return network activity statistics.
- `GET /api/xmatch` cross-matches stored ML candidates with official radio-burst reports.
- `GET /api/lightcurve` extracts light curves at up to eight selected frequencies.
- `GET /api/files/download` downloads the original FITS file.
- `GET /api/spectrogram/export` exports the processed matrix as FITS.
- `POST /api/analysis/type-ii-band-split` exposes the experimental Type-II calculation.

### Background tasks

`POST /api/tasks` accepts `burst_detect_day`, `spectral_overview` and
`combine_time`. `GET /api/tasks/{id}` reports queued/running/succeeded/failed
state and progress. Heavy jobs are run by the dedicated worker, never by the
browser or the API request process.

```powershell
python -m backend.worker
```

## Reproducible deployment

Copy `.env.example` to `.env`, replace all placeholder passwords and set
`ECALLISTO_HOST_DIR` to the NAS archive directory. Then run:

```text
docker compose up --build -d
```

The stack contains PostgreSQL, a single-worker FastAPI service, a dedicated
scientific worker and an Nginx-served React frontend. Open
`http://localhost:8080`. Nginx applies request limits, security headers and
immutable caching for hashed assets. `railway.toml` remains the documented
provisional API-only deployment path; the NAS Compose stack is the target
production architecture.

The API can run without PostgreSQL using its SQLite development fallback. Use
`alembic upgrade head` when managing the persistent schema explicitly.

## Testing and quality

```powershell
pip install -r requirements-dev.txt
ruff check backend tests tools
pytest
cd frontend
npm run lint
npm run build
```

GitHub Actions runs the same backend and frontend checks. The current suite
covers identifier/path security, the official catalogue parser, scientific
helpers, RFI behaviour, API contracts and Type-II calculations.

## Useful Commands

Backend syntax/import check:

```powershell
.\.venv\Scripts\python.exe -m compileall backend
```

Check backend dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install --dry-run -r requirements.txt
```

Frontend lint:

```powershell
cd frontend
npm run lint
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Preview frontend production build locally:

```powershell
cd frontend
npm run preview
```

## Notes and Limitations

- The first request for a file may be slower if the backend needs to download it.
- The first GOES request for a date may be slower because SunPy fetches external data.
- Local cache files are runtime artefacts, not source code.
- The automatic burst detector uses CPU inference and can be slower on small machines.
- Some station coordinates are approximate until learned from real FITS headers.
- Multi-station comparisons depend on matching 15-minute time blocks across stations.

## Credits and References

- e-CALLISTO network and ETHZ archive.
- RFI and burst-detection ideas adapted from tools by Sahan S. Liyanage.
- GOES/XRS data access through SunPy/Fido.
- Built with FastAPI, astropy, numpy, scipy, SunPy, React, Vite and Plotly.js.
