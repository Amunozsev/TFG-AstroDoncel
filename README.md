# AstroDoncel

Portal web para visualizar y analizar espectrogramas solares de la red e-CALLISTO.

Trabajo de Fin de Grado — Universidad de Alcalá, 2026
Autor: Alfonso Muñoz Sevillano

AstroDoncel combina un frontend React con una API FastAPI y un worker científico. Permite explorar estaciones y ficheros FITS, procesar espectrogramas, comparar observaciones, consultar el catálogo de bursts y ejecutar análisis de día completo sin bloquear la API.

> Estado: prototipo funcional de TFG. Los cálculos Type II y algunos localizadores visuales son experimentales; deben validarse antes de usarse como resultado científico. Consulta [ROADMAP_COMPLETO_TFG.md](ROADMAP_COMPLETO_TFG.md) para la auditoría y el plan pendiente.

## Funciones disponibles

### Archivo y espectrogramas

- Lista viva de estaciones y ficheros desde el archivo ETHZ, con fallback local.
- Caché local de FITS y lectura opcional de un archivo NAS en modo solo lectura.
- Selección por estación, fecha, hora y focus code.
- Espectrograma Plotly, zoom de alta resolución y navegación entre ficheros.
- Comparación de hasta seis estaciones en paneles sincronizados u overlay.
- Descarga del FITS original y exportación del FITS procesado.
- Combinación temporal de bloques consecutivos mediante el worker.

### Procesamiento y contexto

- Lectura FITS con `astropy` y ejes UTC/MHz.
- Resta de background por canal.
- Mitigación RFI opcional: ocupación, componentes impulsivas e inpainting.
- Escala relativa y conversión instrumental `median_dB`.
- Contraste automático/manual y presets locales.
- Overlay GOES/XRS-B con caché.
- Regla de deriva en MHz/s y visor de cabeceras FITS.
- Curva de luz a una frecuencia seleccionada, con panel cerrable.
- Overview diario en seis bloques de cuatro horas con scroll independiente.

### Catálogo y detección

- Catálogo de bursts oficiales e-CALLISTO con filtros por fecha, estación y tipo.
- Estadísticas por estación y línea temporal.
- Inferencia CNN+MIL con el modelo ONNX incluido.
- Detección de fichero actual y tarea de detección de día completo.
- Cruce temporal entre candidatos y catálogo oficial.
- Endpoint experimental de band-splitting Type II.

### Mapa

- Estado operativo de estaciones.
- Coordenadas aprendidas de cabeceras FITS y registro persistente.
- Los fallbacks manuales se muestran como aproximados; no son una medida autoritativa.
- Terminador día/noche y punto subsolar como contexto visual aproximado.

## Arquitectura

```text
frontend/                    React 19 + Vite 8 + Plotly
  src/App.jsx                estado global, portal y herramientas
  src/Spectrogram.jsx        render y navegación científica
  src/StationsMap.jsx        mapa de estaciones
  src/BurstCatalog.jsx       catálogo oficial
  src/Statistics.jsx         estadísticas
  src/DailyOverview.jsx      producto diario del worker
  src/LightCurvePanel.jsx    curvas de luz

backend/
  main.py                    API principal, archivo y pipeline científico
  api_features.py            catálogo, exportaciones, curvas y tareas
  burst_detect.py            inferencia ONNX y postprocesado
  catalog.py                 parser e ingesta del catálogo
  db.py                      SQLAlchemy: SQLite/PostgreSQL
  security.py                validación de identificadores y rutas seguras
  type_ii.py                 cálculo experimental Type II
  worker.py                  trabajos persistentes pesados

migrations/                  esquema Alembic
tests/                       pruebas backend
frontend/src/*.test.jsx      regresiones de interfaz con Vitest
tools/                       exportación ONNX y limpieza de caché
nginx/                       proxy y frontend de producción
```

Flujo principal:

```text
Navegador → FastAPI → caché local / NAS / ETHZ
                │
                ├─ SQLite o PostgreSQL
                └─ cola SQL → worker → data/task_results
```

Los repositorios `e-Callisto_FITS_Analyzer`, `Burst_No_Burst` y `ecallistolib` de Sahan son material de referencia. No hay que descargarlos para instalar, ejecutar ni probar AstroDoncel. Si se conservan copias locales, deben estar bajo `Sahan/`; esa carpeta está ignorada por Git y no forma parte de la aplicación.

## Requisitos

- Python 3.12.
- Node.js 22 y npm.
- Windows, Linux o macOS para desarrollo local.
- Docker Compose solo para el despliegue completo; no es necesario para SQLite local.

Las dependencias están separadas por uso:

| Archivo | Contenido |
|---|---|
| `requirements.txt` | API, procesamiento, GOES, ONNX y persistencia |
| `requirements-dev.txt` | runtime más pytest, Ruff, TestClient y Alembic |
| `requirements-ml.txt` | toolchain opcional de exportación/reentrenamiento con PyTorch CPU |

PyTorch no se importa ni se necesita para servir la API o ejecutar ONNX.

## Instalación local en Windows

Clona el repositorio y entra en él:

```powershell
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
```

Crea el entorno, el directorio de datos e instala el perfil de desarrollo:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
New-Item -ItemType Directory -Force data | Out-Null
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Instala el frontend de forma reproducible:

```powershell
cd frontend
npm ci
cd ..
```

### Arranque

Abre tres terminales desde la raíz del repositorio.

Terminal 1 — API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2 — worker:

```powershell
.\.venv\Scripts\python.exe -m backend.worker
```

Terminal 3 — frontend:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

Abre:

- Portal: <http://127.0.0.1:5173>
- API: <http://127.0.0.1:8000>
- OpenAPI: <http://127.0.0.1:8000/docs>
- Salud: <http://127.0.0.1:8000/health>
- Disponibilidad detallada: <http://127.0.0.1:8000/ready>

El worker es necesario para `Detect full day`, `Build daily overview` y `Combine next blocks`. El resto de la API puede funcionar sin él.

### Preview del build de producción

```powershell
cd frontend
$env:VITE_API_BASE_URL='http://127.0.0.1:8000'
npm run build
npm run preview -- --host 127.0.0.1 --port 5173
```

## Configuración

El desarrollo local funciona sin `.env`: usa SQLite en `data/astrodoncel.db`, caché en `data/` y los puertos anteriores.

`.env.example` está orientado a Docker Compose. No lo cargues directamente en un arranque local con Uvicorn sin cambiar `DATABASE_URL`, porque el host PostgreSQL `db` solo existe dentro de Compose.

| Variable | Uso | Valor local por defecto |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy; PostgreSQL en producción | `sqlite:///./data/astrodoncel.db` |
| `DATA_DIR_LOCAL` | FITS descargados, GOES y coordenadas aprendidas | `data/` del repositorio |
| `TASK_RESULT_DIR` | artefactos JSON gzip del worker | `data/task_results/` |
| `ECALLISTO_DATA_DIR` | archivo externo `YYYY/MM/DD/*.fit*` | ruta histórica NAS, opcional |
| `FRONTEND_ORIGINS` | orígenes CORS separados por coma | localhost/127.0.0.1:5173 |
| `BURST_MODEL_DIR` | bundle ONNX alternativo | `backend/model/burst_detector/` |
| `BURST_INTRA_OP_THREADS` | hilos CPU de ONNX | `1` |
| `MAX_ACTIVE_TASKS` | límite global de tareas activas | `100` |
| `TASK_STALE_MINUTES` | latido máximo antes de recuperar una tarea | `15` |
| `TASK_RETENTION_DAYS` | retención de tareas/artefactos terminados | `30` |
| `MAX_FITS_DOWNLOAD_BYTES` | límite por descarga remota | `134217728` (128 MiB) |
| `CATALOG_REFRESH_HOURS` | vigencia de cada mes del catálogo | `12` |
| `VITE_API_BASE_URL` | URL API embebida al construir frontend | API local en dev; mismo origen en producción |

La API nunca acepta una ruta de disco enviada por el cliente. Estación, fecha y filename deben pasar `backend.security`.

## Base de datos y migraciones

SQLite es el fallback de desarrollo. El stack Docker usa PostgreSQL.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Las migraciones son explícitas y se prueban en upgrade/downgrade. Antes de aplicarlas sobre una base persistente, realiza una copia de seguridad. Si ya arrancaste una versión antigua que creó las tablas mediante `create_all` pero no tiene `alembic_version`, no ejecutes el upgrade inicial a ciegas: respalda la base y usa `alembic stamp head` solo después de comprobar que su esquema coincide.

## Docker Compose

Requiere Docker con Compose:

```powershell
Copy-Item .env.example .env
```

Edita `.env`, cambia la contraseña en `POSTGRES_PASSWORD` y `DATABASE_URL`, y configura `ECALLISTO_HOST_DIR` si existe un archivo NAS. Después:

```powershell
docker compose up --build -d
```

Servicios:

- `db`: PostgreSQL.
- `api`: FastAPI de un solo proceso.
- `worker`: análisis pesados.
- `web`: Nginx + build React, publicado en <http://localhost:8080>.

El archivo externo se monta en solo lectura. `data/` y PostgreSQL deben incluirse en la estrategia de backup. El Compose aún debe validarse en el NAS objetivo; véase el roadmap.

## API resumida

### Archivo y visualización

- `GET /api/stations`
- `GET /api/stations/geo`
- `GET /api/files?station=&date=`
- `GET /api/spectrogram?station=&date=&filename=`
- `GET /api/spectrogram/combine`
- `GET /api/spectrogram/zoom`
- `GET /api/files/download`
- `GET /api/spectrogram/export`
- `GET /api/lightcurve`
- `GET /api/goes`

### Catálogo y análisis

- `GET /api/bursts`
- `GET /api/stats/stations`
- `GET /api/stats/timeline`
- `GET /api/xmatch`
- `GET /api/burst/detect`
- `POST /api/analysis/type-ii-band-split`

### Tareas

`POST /api/tasks` acepta:

- `burst_detect_day`
- `spectral_overview`
- `combine_time`

Consulta progreso con `GET /api/tasks/{id}`, cancela con `POST /api/tasks/{id}/cancel` y abre el resultado comprimido con `GET /api/tasks/{id}/artifact`. La cola deduplica clics repetidos, limita trabajos activos, recupera tareas abandonadas y elimina resultados terminales tras la retención configurada.

Los contratos completos y parámetros están en `/docs`.

## Calidad y pruebas

Backend:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
```

Frontend:

```powershell
cd frontend
npm run lint
npm run test
npm run build
npm audit
```

Instalación declarativa sin modificar el entorno:

```powershell
.\.venv\Scripts\python.exe -m pip install --dry-run -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --dry-run -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --dry-run -r requirements-ml.txt
```

GitHub Actions ejecuta Ruff, pytest, ESLint y el build en cada push y pull request.

## Toolchain ML opcional

Solo para exportar o investigar el modelo:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt
.\.venv\Scripts\python.exe tools/export_onnx.py --help
```

No se debe reentrenar ni cambiar umbrales sin un dataset versionado, separación train/validation/test y métricas reproducibles. La identidad, métricas declaradas, límites y huecos de procedencia del bundle actual están en [MODEL_CARD.md](MODEL_CARD.md).

## Datos y limpieza

`data/` es almacenamiento de ejecución y no se versiona. Puede contener:

- FITS descargados.
- `astrodoncel.db`.
- `station_coords.json` aprendido de cabeceras.
- caché GOES.
- artefactos de tareas.

La limpieza de FITS es dry-run por defecto:

```powershell
.\.venv\Scripts\python.exe tools/prune_cache.py --data-dir data --max-gb 20 --max-age-days 90
```

Añade `--apply` únicamente después de revisar la lista. El script no borra SQLite, GOES ni artefactos de tareas.

## Interpretación científica

- Frecuencia: MHz.
- Tiempo: UTC.
- Deriva: MHz/s.
- La intensidad `relative digits` es instrumental y no una densidad de flujo calibrada.
- `median_dB` es una conversión instrumental, no calibración absoluta.
- Background y RFI son transformaciones algorítmicas cuyos parámetros deben acompañar a cualquier producto exportado.
- El detector CNN+MIL ofrece candidatos probabilísticos; no sustituye validación experta.
- El localizador visual de fallback es heurístico.
- El cálculo Type II devuelve una advertencia experimental y no incluye todavía incertidumbres completas.

## Limitaciones conocidas

- Primera consulta lenta si debe descargar FITS o GOES.
- El catálogo y las listas de ficheros dependen de servicios ETHZ externos.
- La cancelación es cooperativa: una operación científica individual no se interrumpe hasta alcanzar el siguiente punto de control.
- Hay pruebas frontend de los paneles críticos, pero aún falta un E2E de navegador en CI y mayor cobertura de respuestas fuera de orden.
- El bundle parcial de Plotly reduce mucho la carga, aunque su chunk principal sigue superando 1 MB sin comprimir.
- La validación completa Docker/NAS y PostgreSQL queda pendiente en el host objetivo.
- Falta elegir la licencia raíz y confirmar por escrito la redistribución de los pesos; véanse [MODEL_CARD.md](MODEL_CARD.md) y [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Créditos

- Red e-CALLISTO y archivo ETHZ.
- Universidad de Alcalá y proyecto AstroDoncel.
- Herramientas y algoritmos de referencia de Sahan S. Liyanage, adaptados con cambios propios.
- SunPy/Fido para acceso a GOES.
- FastAPI, Astropy, NumPy, SciPy, SQLAlchemy, ONNX Runtime, React, Vite y Plotly.

El registro de atribución y asuntos legales pendientes está en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
