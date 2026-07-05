# AstroDoncel - Solar Radio Spectrogram Portal

Bachelor's Thesis - Universidad de Alcala - 2026  
Author: Alfonso Munoz Sevillano

AstroDoncel is an interactive web portal for visualising and analysing solar
radio spectrograms from the e-CALLISTO network. The project is split into:

- `frontend/`: React + Vite + Plotly, intended for Vercel.
- `backend/`: FastAPI + scientific Python stack, intended for Railway.

There is no login layer. The frontend is public and calls the backend API
directly.

## Main Features

- Live e-CALLISTO station list from the ETHZ archive, with local fallback.
- Station world map with operative/offline status and day-night overlay.
- FITS auto-download and local cache in `data/`.
- Single-station and multi-station spectrogram loading.
- Time-synchronised multi-layer comparison.
- RFI mitigation pipeline ported from Sahan's tools.
- High-resolution zoom patch endpoint.
- GOES/XRS overlay through SunPy/Fido.
- FITS header viewer.
- Drift ruler for measuring time, frequency and drift rate.
- Optional ML burst detection endpoint when `torch` and the model bundle are available.

## Project Structure

```text
TFG-AstroDoncel/
  backend/
    main.py              FastAPI API and scientific pipeline
    burst_detect.py      Optional CNN+MIL burst detector
  frontend/
    src/
      App.jsx            Main React UI
      Spectrogram.jsx    Plotly spectrogram view
      StationsMap.jsx    Station map view
      api.js             Frontend API base URL helper
    package.json         Vercel/Node dependencies and scripts
  data/                  Local FITS and cache files, not for deployment
  requirements.txt       Railway/Python backend dependencies
  railway.json           Railway backend start command
```

## Local Development

### 1. Backend

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Backend URL:

```text
http://localhost:8000
```

API docs:

```text
http://localhost:8000/docs
```

### 2. Frontend

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

By default, the frontend calls `http://localhost:8000`. For any other backend,
set `VITE_API_BASE_URL`.

## Environment Variables

### Backend - Railway

```text
FRONTEND_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:5173
ECALLISTO_DATA_DIR=/var/services/web/ecallistodata
BURST_MODEL_DIR=/app/Sahan/Burst_No_Burst-master/deploy/deploy_v1
```

Required:

- `FRONTEND_ORIGINS`: comma-separated list of frontend origins allowed by CORS.

Optional:

- `ECALLISTO_DATA_DIR`: external NAS/data directory. If omitted, the backend uses local cache and ETHZ downloads.
- `BURST_MODEL_DIR`: path to the optional ML burst detector model bundle.

### Frontend - Vercel

```text
VITE_API_BASE_URL=https://your-railway-backend.up.railway.app
```

This value is public because Vite exposes `VITE_*` variables in the browser
bundle. Do not put secrets in `VITE_*` variables.

## Deployment Overview

Recommended split:

- Railway hosts the FastAPI backend.
- Vercel hosts the static Vite frontend.
- GitHub stores the repository and triggers deployments.

This is a good setup for this project because the backend needs long-running
Python scientific dependencies, while the frontend is a static React app that
Vercel serves very efficiently.

## Deploy Backend to Railway

1. Push the repository to GitHub.

2. Go to Railway and create a new project.

3. Choose `Deploy from GitHub repo`.

4. Select this repository.

5. Railway should use the root of the repository as the backend service.

6. Confirm these deployment settings:

```text
Build source: repository root
Start command: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
Healthcheck path: /health
```

The included `railway.json` already defines the start command and healthcheck.

7. Add the backend environment variable:

```text
FRONTEND_ORIGINS=http://localhost:5173
```

Later, after Vercel gives you the final frontend URL, change it to:

```text
FRONTEND_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:5173
```

8. In Railway, open the backend service settings and generate a public domain.

9. Test the backend:

```text
https://your-railway-backend.up.railway.app/health
```

Expected response:

```json
{"status":"ok","version":"0.2.0"}
```

## Deploy Frontend to Vercel

1. Go to Vercel and create a new project.

2. Import the same GitHub repository.

3. Set the Vercel root directory to:

```text
frontend
```

4. Confirm build settings:

```text
Framework preset: Vite
Install command: npm install
Build command: npm run build
Output directory: dist
```

5. Add the frontend environment variable:

```text
VITE_API_BASE_URL=https://your-railway-backend.up.railway.app
```

6. Deploy.

7. Copy the final Vercel URL.

8. Go back to Railway and update:

```text
FRONTEND_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:5173
```

9. Redeploy Railway after changing the variable.

10. Open the Vercel app and verify:

- Station list loads.
- Map loads.
- Spectrogram load works.
- Browser console has no CORS errors.

## What Uses `requirements.txt`?

`requirements.txt` is for the Railway backend only.

Railway sees a Python backend, installs the packages from `requirements.txt`,
then runs:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Vercel does not use `requirements.txt`. Vercel deploys the React frontend from
`frontend/` and uses:

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.js`

## API Reference

| Method | Route | Description |
|---|---|---|
| `GET` | `/health` | Backend health check |
| `GET` | `/api/stations` | List e-CALLISTO stations |
| `GET` | `/api/stations/geo` | Station coordinates and operative state |
| `GET` | `/api/files` | Available FITS files for station/date |
| `GET` | `/api/spectrogram` | Process one spectrogram |
| `GET` | `/api/spectrogram/combine` | Process multiple time-synced stations |
| `GET` | `/api/spectrogram/zoom` | High-resolution zoom patch |
| `GET` | `/api/goes` | GOES/XRS overlay data |
| `GET` | `/api/burst/detect` | Optional ML burst detection |

## Useful Checks

Backend:

```powershell
.\.venv\Scripts\python.exe -m compileall backend
```

Frontend:

```powershell
cd frontend
npm run lint
npm run build
```

## Notes

- Do not deploy the local `data/` cache unless you intentionally need sample files.
- The first GOES request for a date can take several seconds because SunPy downloads data.
- The ML detector is optional. If `torch` or the model bundle is missing, the endpoint responds with `available: false` instead of crashing the backend.
- If Vercel cannot reach Railway, check `VITE_API_BASE_URL`.
- If the browser shows CORS errors, check `FRONTEND_ORIGINS` in Railway and redeploy.

## Sources Used for Deployment Guidance

- Vercel Vite deployment docs: https://vercel.com/docs/frameworks/frontend/vite
- Vercel monorepo docs: https://vercel.com/docs/monorepos
- Vercel environment variables docs: https://vercel.com/docs/environment-variables
- Vite env variable docs: https://vite.dev/guide/env-and-mode
- Railway FastAPI deployment guide: https://docs.railway.com/guides/fastapi
- Railway config-as-code reference: https://docs.railway.com/config-as-code/reference
