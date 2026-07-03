# AstroDoncel — Solar Radio Spectrogram Portal (e-CALLISTO)

> **Bachelor's Thesis · Universidad de Alcalá · 2026**
> Author: Alfonso Muñoz Sevillano

Interactive web portal for visualisation and analysis of solar radio spectrograms from the [e-CALLISTO](http://www.e-callisto.org/) network. Select any network station, browse bursts for a given day hour by hour, and apply the RFI cleaning pipeline developed by Dr. Sahan S. Liyanage (University of Colombo).

---

## Features

| Feature | Details |
|---|---|
| **Live station list** | Fetches active stations from the ETHZ archive (soleil.i4ds.ch); falls back to a static list of 76 real stations when offline |
| **Burst navigation** | For each station + date, lists all available files (~15 min segments) with their start time, grouped by hour; the first one loads automatically |
| **Auto-download** | If a file is not in the local cache, it is downloaded from the ETHZ archive transparently |
| **RFI pipeline (Sahan)** | 2D median filter → hot-channel detection (MAD z-score) → interpolation repair → per-channel percentile clipping |
| **Background subtraction** | Robust baseline using the 25th percentile of each frequency channel (always active) |
| **Absolute time axis** | Real ISO 8601 UTC timestamps reconstructed from `DATE-OBS + TIME-OBS + CDELT1` in the FITS header |
| **Adjustable contrast** | `Z min / Z max` sliders with automatic computation from the 2–98 percentile range of processed data |
| **GOES/XRS overlay** | Overlays GOES X-ray flux (XRS-B channel, 0.1–0.8 nm) on a secondary logarithmic Y axis via `sunpy.net.Fido`, clipped to the visible time window |
| **Colormap selection** | 11 selectable colorscales (Observatory default, Hot, Viridis, Plasma, Inferno, Magma, Cividis, Turbo, Jet, RdYlBu, Cubehelix, Bone) |
| **Multi-station comparison** | Select several stations at once; spectrograms are fetched concurrently and time-synced to the same 15-minute block |
| **High-resolution zoom** | Box-selecting a region in the plot fetches a full-resolution patch for that time/frequency window instead of the decimated overview |

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    Browser                           │
│   React + Vite · Plotly.js (WebGL)                   │
│   App.jsx  ←→  Spectrogram.jsx                       │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP / JSON  (port 5173 → 8000)
┌────────────────────▼─────────────────────────────────┐
│                FastAPI (Python)                       │
│   /api/stations  /api/files  /api/spectrogram         │
│   /api/spectrogram/combine  /api/spectrogram/zoom     │
│   /api/goes      /health                              │
│                                                       │
│   astropy · numpy · scipy · sunpy                    │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP / FITS
        ┌────────────▼───────────────┐
        │  ETHZ Archive (HTTPS)      │
        │  soleil.i4ds.ch/...        │
        │  + NOAA NGDC (GOES/XRS)    │
        └────────────────────────────┘
```

---

## Getting started

### Prerequisites

- Python 3.12+ with `pip`
- Node.js 18+

### 1. Clone the repository

```bash
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
```

### 2. Backend (FastAPI)

```bash
# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The backend is available at `http://localhost:8000`.  
Interactive API documentation is at `http://localhost:8000/docs`.

> **Note on GOES/XRS:** The first time the GOES overlay is activated, `sunpy` downloads the NetCDF file from NOAA NGDC (~10–30 s). Subsequent requests use the local cache in `data/goes_cache/`.

### 3. Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

Open your browser at `http://localhost:5173`.

---

## API reference

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/health` | Server health check |
| `GET` | `/api/stations` | List of active e-CALLISTO stations |
| `GET` | `/api/files` | Available bursts for a given `station` + `date` |
| `GET` | `/api/spectrogram` | Processed spectrogram as JSON |
| `GET` | `/api/spectrogram/combine` | Processed spectrograms for multiple stations, time-synced and fetched concurrently |
| `GET` | `/api/spectrogram/zoom` | Full-resolution patch for a time/frequency bounding box |
| `GET` | `/api/goes` | GOES XRS-B flux for a given date |

### `/api/files`

```
GET /api/files?station=SPAIN-SIGUENZA&date=2024-05-08
```

```json
{
  "station": "SPAIN-SIGUENZA",
  "date": "2024-05-08",
  "source": "ethz",
  "files": [
    { "filename": "SPAIN-SIGUENZA_20240508_080000_01.fit.gz", "time": "08:00:00", "label": "08:00:00" },
    { "filename": "SPAIN-SIGUENZA_20240508_081500_01.fit.gz", "time": "08:15:00", "label": "★ 08:15:00" }
  ]
}
```

The `★` prefix marks files already downloaded to the local cache.

### `/api/spectrogram`

```
GET /api/spectrogram?station=SPAIN-SIGUENZA&date=2024-05-08
    &filename=SPAIN-SIGUENZA_20240508_080000_01.fit.gz
    &sahan_filter=false
```

Returns `time_axis` (ISO 8601 UTC), `freq_axis` (MHz), `z` (intensity in dB), `vmin/vmax`, and the full FITS header.

### `/api/spectrogram/combine`

```
GET /api/spectrogram/combine?date=2024-05-08&stations=SPAIN-SIGUENZA&stations=SPAIN-ALCALA
    &filename=SPAIN-SIGUENZA_20240508_080000_01.fit.gz
```

Fetches and processes each station concurrently, syncing secondary stations to the same 15-minute block as the primary. Returns a `layers` array (one `SpectrogramResponse` per station) plus `failed` for any station without a matching file.

### `/api/spectrogram/zoom`

```
GET /api/spectrogram/zoom?station=SPAIN-SIGUENZA&date=2024-05-08
    &filename=SPAIN-SIGUENZA_20240508_080000_01.fit.gz
    &t0=2024-05-08T08:05:00Z&t1=2024-05-08T08:10:00Z&f0=45&f1=80
```

Returns a full-resolution slice for the given time/frequency box, reprocessed (background subtraction, optional RFI filter) on the slice only. Used by the frontend when the user box-selects a region on the plot.

### `/api/goes`

```
GET /api/goes?date=2024-05-08
```

```json
{
  "date": "2024-05-08",
  "available": true,
  "satellite": 18,
  "times": ["2024-05-08T00:00:00.000Z", "..."],
  "xrsb": [1.2e-8, "..."]
}
```

---

## Project structure

```
TFG-AstroDoncel/
├── backend/
│   └── main.py               # FastAPI endpoints + scientific pipeline
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # Main logic and sidebar
│   │   ├── Spectrogram.jsx   # Plotly component (heatmap + GOES overlay)
│   │   └── App.css           # Dashboard styles
│   └── package.json
├── requirements.txt          # Python dependencies (install from repo root)
├── data/                     # Downloaded FITS files (not versioned)
│   └── goes_cache/           # GOES NetCDF file cache
└── README.md
```

---

## Processing pipeline

```
FITS file (e-CALLISTO)
        │
        ▼
_load_callisto_data()       ← Read HDU, extract freq/time axes from
                              BIN table, WCS header, or FREQMIN/FREQMAX
        │
        ▼
_subtract_background()      ← Baseline subtraction: 25th percentile per row
                              (robust against intense solar emission)
        │
        ▼  [if sahan_filter=true]
_clean_rfi()                ← 2D median filter (3×3)
                              Hot-channel detection (MAD z-score, threshold 6σ)
                              Repair by interpolation from neighbours
                              Outlier clipping (99.5th percentile per channel)
        │
        ▼
_percentile_clip_global()   ← Compute vmin (p2) and vmax (p98) for contrast
        │
        ▼
_times_to_utc()             ← ISO 8601 UTC from DATE-OBS + TIME-OBS + CDELT1
        │
        ▼
JSON → Plotly heatmap (selectable colorscale, default: observatory)
```

---

## Credits and references

- **RFI scientific engine:** ported and adapted from [e-CALLISTO FITS Analyzer v2.4.1](https://github.com/saandev/e-callisto_fits_analyzer) by Sahan S. Liyanage, Astronomical and Space Science Unit, University of Colombo, Sri Lanka.
- **e-CALLISTO network:** Christian Monstein, ETH Zürich / Institute for Astronomy, Eidgenössische Technische Hochschule.
- **GOES/XRS data:** NOAA National Centers for Environmental Information (NCEI), downloaded via [SunPy](https://sunpy.org/).
- **Stack:** [FastAPI](https://fastapi.tiangolo.com/) · [astropy](https://www.astropy.org/) · [SunPy](https://sunpy.org/) · [React](https://react.dev/) · [Vite](https://vitejs.dev/) · [Plotly.js](https://plotly.com/javascript/)

---

## Licence

Academic project. Code is freely reusable with attribution. FITS data belong to the e-CALLISTO network (CC BY 4.0).
