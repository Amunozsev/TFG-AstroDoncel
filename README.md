# AstroDoncel — Portal de Espectrogramas Solares e-CALLISTO

> **Trabajo de Fin de Grado · Universidad de Alcalá · 2026**
> Autor: Alfonso Muñoz Sevillano

Portal web interactivo para la visualización y análisis de espectrogramas de radio solar procedentes de la red [e-CALLISTO](http://www.e-callisto.org/). Permite seleccionar cualquier estación de la red, navegar por los *bursts* de un día concreto hora a hora y aplicar el pipeline de limpieza RFI del Dr. Sahan S. Liyanage (Universidad de Colombo).

---

## Características

| Función | Detalle |
|---|---|
| **Listado de estaciones en tiempo real** | Extrae las estaciones activas del archivo ETHZ (soleil.i4ds.ch) y, si no hay conexión, usa una lista estática de 76 estaciones reales |
| **Navegación por bursts** | Para cada estación + día, lista todos los archivos disponibles (segmentos de ~15 min) con su hora de inicio; el primero se carga automáticamente |
| **Descarga automática** | Si el archivo no está en caché local, lo descarga del archivo ETHZ sin intervención del usuario |
| **Pipeline RFI (Sahan)** | Filtro mediana 2D → detección de canales calientes (z-score MAD) → reparación por interpolación → recorte de outliers por percentil |
| **Sustracción de fondo** | Baseline robusto por percentil 25 de cada canal de frecuencia (activo siempre) |
| **Eje temporal absoluto** | Timestamps ISO 8601 UTC reales, reconstruidos desde `DATE-OBS + TIME-OBS + CDELT1` del header FITS |
| **Contraste ajustable** | Sliders de `Z min / Z max` con cálculo automático por percentil 2–98 sobre datos procesados |
| **Overlay GOES/XRS** | Superpone el flujo de rayos X de GOES (canal XRS-B, 0.1–0.8 nm) en eje Y secundario logarítmico, vía `sunpy.net.Fido` |
| **Colormap científico** | Escala `hot` de matplotlib (negro → rojo → amarillo → blanco), estándar en publicaciones e-CALLISTO |

---

## Arquitectura

```
┌──────────────────────────────────────────────────────┐
│                    Navegador                         │
│   React + Vite · Plotly.js (WebGL)                   │
│   App.jsx  ←→  Spectrogram.jsx                       │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP / JSON  (puerto 5173 → 8000)
┌────────────────────▼─────────────────────────────────┐
│                FastAPI (Python)                       │
│   /api/stations  /api/files  /api/spectrogram         │
│   /api/goes      /health                              │
│                                                       │
│   astropy · numpy · scipy · sunpy                    │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP / FITS
        ┌────────────▼───────────────┐
        │  Archivo ETHZ (HTTPS)      │
        │  soleil.i4ds.ch/...        │
        │  + NOAA NGDC (GOES/XRS)    │
        └────────────────────────────┘
```

---

## Puesta en marcha

### Requisitos previos

- Python 3.11+ con `pip`
- Node.js 18+

### 1. Clonar el repositorio

```bash
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
```

### 2. Backend (FastAPI)

```bash
# Crear y activar entorno virtual
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Arrancar el servidor
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

El backend queda disponible en `http://localhost:8000`.
La documentación interactiva de la API está en `http://localhost:8000/docs`.

> **Nota sobre GOES/XRS:** La primera vez que se activa el overlay GOES, `sunpy` descarga el archivo NetCDF desde NOAA NGDC (~10-30 s). Las descargas posteriores usan caché local en `data/goes_cache/`.

### 3. Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

Abre el navegador en `http://localhost:5173`.

---

## API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Estado del servidor |
| `GET` | `/api/stations` | Lista de estaciones e-CALLISTO activas |
| `GET` | `/api/files` | Bursts disponibles para `station` + `date` |
| `GET` | `/api/spectrogram` | Espectrograma procesado en JSON |
| `GET` | `/api/goes` | Flujo GOES XRS-B para una fecha |

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

El prefijo `★` indica archivos ya descargados en caché local.

### `/api/spectrogram`

```
GET /api/spectrogram?station=SPAIN-SIGUENZA&date=2024-05-08
    &filename=SPAIN-SIGUENZA_20240508_080000_01.fit.gz
    &sahan_filter=false
```

Devuelve `time_axis` (ISO 8601 UTC), `freq_axis` (MHz), `z` (intensidad dB), `vmin/vmax` y el header FITS completo.

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

## Estructura del proyecto

```
TFG-AstroDoncel/
├── backend/
│   ├── main.py               # API FastAPI + pipeline científico
│   └── requirements.txt      # Dependencias Python
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # Lógica principal y sidebar
│   │   ├── Spectrogram.jsx   # Componente Plotly (heatmap + GOES)
│   │   └── App.css           # Estilos del dashboard
│   └── package.json
├── data/                     # Archivos FITS descargados (no versionado)
│   └── goes_cache/           # Cache de archivos NetCDF GOES
└── README.md
```

---

## Pipeline de procesamiento

```
Archivo FITS (e-CALLISTO)
        │
        ▼
_load_callisto_data()       ← Lectura HDU, extracción de ejes freq/time por
                              tabla BIN, WCS header o FREQMIN/FREQMAX
        │
        ▼
_subtract_background()      ← Sustracción de baseline: percentil 25 por fila
                              (robusto ante emisión solar intensa)
        │
        ▼  [si sahan_filter=true]
_clean_rfi()                ← Filtro mediana 2D (3×3)
                              Detección canales calientes (z-score MAD, umbral 6σ)
                              Reparación por interpolación con vecinos
                              Recorte de outliers (percentil 99.5 por canal)
        │
        ▼
_percentile_clip_global()   ← Cálculo de vmin (p2) y vmax (p98) para contraste
        │
        ▼
_times_to_utc()             ← ISO 8601 UTC desde DATE-OBS + TIME-OBS + CDELT1
        │
        ▼
JSON → Plotly heatmap (colorscale: hot)
```

---

## Créditos y referencias

- **Motor científico RFI:** portado y adaptado de [e-CALLISTO FITS Analyzer v2.4.1](https://github.com/saandev/e-callisto_fits_analyzer) de Sahan S. Liyanage, Astronomical and Space Science Unit, Universidad de Colombo, Sri Lanka.
- **Red e-CALLISTO:** Christian Monstein, ETH Zürich / Institute for Astronomy, Eidgenössische Technische Hochschule.
- **Datos GOES/XRS:** NOAA National Centers for Environmental Information (NCEI), descargados vía [SunPy](https://sunpy.org/).
- **Stack:** [FastAPI](https://fastapi.tiangolo.com/) · [astropy](https://www.astropy.org/) · [SunPy](https://sunpy.org/) · [React](https://react.dev/) · [Vite](https://vitejs.dev/) · [Plotly.js](https://plotly.com/javascript/)

---

## Licencia

Proyecto académico. El código es de libre uso con atribución. Los datos FITS pertenecen a la red e-CALLISTO (CC BY 4.0).
