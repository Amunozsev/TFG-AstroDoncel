# TFG AstroDoncel — Radioespectrometría Solar

Prototipo de visualización interactiva de espectrogramas solares a partir de ficheros FITS de la red e-Callisto.

**Stack:** Python (astropy, numpy) · React + Vite · Plotly.js

---

## Puesta en marcha desde cero

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd TFG\ AstroDoncel
```

### 2. Backend (Python)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Datos FITS

Coloca los ficheros `.fit` o `.fit.gz` de e-Callisto en la carpeta `/data` (no se sube al repo por su tamaño).

Ejecuta el script para generar el JSON que consume el frontend:

```bash
cd backend
python test_read.py
```

Esto crea `frontend/public/datos_prueba.json` automáticamente.

### 4. Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

Abre el navegador en `http://localhost:5173`.

---

## Estructura del proyecto

```
/backend          Script Python de lectura y preprocesamiento FITS
/frontend         Aplicación React + Vite
  /public         JSON generado (no se versiona)
  /src            Componentes React
/data             Ficheros FITS (no se versiona)
requirements.txt  Dependencias Python
```
