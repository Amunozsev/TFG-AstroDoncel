# AstroDoncel

Portal web para visualizar y analizar espectrogramas solares de la red e-CALLISTO.

Trabajo de Fin de Grado — Universidad de Alcalá, 2026
Autor: Alfonso Muñoz Sevillano

AstroDoncel combina un frontend React con una API FastAPI y un worker científico. Permite explorar estaciones y ficheros FITS, procesar espectrogramas, comparar observaciones, consultar el catálogo de bursts y ejecutar análisis de día completo sin bloquear la API.

> Estado: prototipo funcional de TFG. Los cálculos Type II y algunos localizadores visuales son experimentales; deben validarse antes de usarse como resultado científico. Consulta [ROADMAP_COMPLETO_TFG.md](ROADMAP_COMPLETO_TFG.md) para la auditoría y el plan pendiente.

## Funciones disponibles

### Archivo y espectrogramas

- Inventario vivo y persistente de estaciones desde el archivo ETHZ: distingue activas e inactivas y descubre automáticamente estaciones nuevas.
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
- Overview espectral para un intervalo UTC exacto, desde/hasta fecha y hora, sobre las estaciones seleccionadas o todas las conocidas.
- El overview conserva todos los grupos de receptor/eje de frecuencia compatibles, informa los ficheros omitidos y permite cambiar la escala de color.

### Catálogo y detección

- Catálogo `deARCE detection (v3)` con filtros por fecha, estación y tipo, longitudes solares Min/Mid/Max y enlaces directos desde cada estación al bloque FITS del evento.
- Estadísticas por estación y línea temporal mensual con el día visible bajo cada barra.
- Xmatch diario interactivo: disponibilidad por estación, detecciones deARCE clicables y filtro entre todas las estaciones o solo positivas.
- Inferencia CNN+MIL con el modelo ONNX incluido.
- Detección de fichero actual y tarea de detección de día completo.
- Cruce temporal entre candidatos ML y catálogo, separado del Xmatch visual diario.
- Endpoint experimental de band-splitting Type II.

### Mapa

- Estado activo/inactivo calculado desde el día más reciente del archivo.
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
  src/Statistics.jsx         estadísticas y Xmatch interactivo
  src/DailyOverview.jsx      overview multiestación del worker
  src/LightCurvePanel.jsx    curvas de luz

backend/
  main.py                    API principal, archivo y pipeline científico
  api_features.py            catálogo, exportaciones, curvas y tareas
  burst_detect.py            inferencia ONNX y postprocesado
  catalog.py                 parser e ingesta de deARCE v3 / e-CALLISTO v2
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
.\.venv\Scripts\python.exe -m alembic upgrade head
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
| `STATION_REFRESH_MINUTES` | vigencia del escaneo de estaciones activas | `60` |
| `ARCHIVE_INDEX_REFRESH_MINUTES` | vigencia del índice de ficheros por día | `60` |
| `OVERVIEW_MAX_STATIONS` | máximo de estaciones por overview | `120` |
| `OVERVIEW_MAX_HOURS` | máximo de horas por overview | `72` |
| `XMATCH_NOMINAL_BLOCK_MINUTES` | duración heurística usada para dibujar disponibilidad | `15` |
| `VITE_API_BASE_URL` | URL API embebida al construir frontend | API local en dev; mismo origen en producción |

La API nunca acepta una ruta de disco enviada por el cliente. Estación, fecha y filename deben pasar `backend.security`.

### Descubrimiento automático de estaciones

`GET /api/stations` escanea el índice del archivo ETHZ, guarda cada estación observada en la tabla `stations` y devuelve la unión de estaciones activas y conocidas. `active` significa que la estación publicó al menos un FITS en el día más reciente con datos; una estación conocida que no publicó ese día aparece como inactiva. La caché se renueva según `STATION_REFRESH_MINUTES`, por lo que no hay que editar una lista al añadir una estación en el archivo.

`GET /api/stations/geo` usa la misma unión. Las coordenadas autoritativas se leen de `OBS_LAT`, `OBS_LON`, `OBS_LAC` y `OBS_LOC` en cabeceras FITS y se persisten en SQLite/PostgreSQL y `data/station_coords.json`. Una estación nueva sin coordenadas queda en `unmapped` mientras se descarga en background un FITS para aprenderlas; nunca se inventan coordenadas. Los valores manuales heredados solo sirven como fallback temporal para una estación ya descubierta, no para decidir qué estaciones existen.

El catálogo de bursts también registra estaciones observadas, de modo que una estación puede aparecer en listas mensuales y estadísticas aunque ese día esté inactiva. Para cambiar la frecuencia de refresco o los límites del overview basta con las variables anteriores; no hay constantes de producto repartidas por el frontend.

### Procedencia del catálogo de bursts

La vista Burst Reports usa por defecto `dearce_v3`, mostrado como **deARCE detection (v3)**. La fuente primaria es el fichero mensual `NCELESTINA_YYYY_MM.link` de AstroDoncel/UAH; contiene fecha, intervalo UTC, tipo, `Min.lon`, `Mid.lon`, `Max.lon` y estaciones. El código intenta HTTPS con verificación normal y, si el certificado del servidor no es válido, el mismo recurso HTTP público. Nunca desactiva la verificación TLS.

Como último fallback de disponibilidad usa `e-CALLISTO_YYYY_MM.txt` del archivo FHNW/ETHZ únicamente si la cabecera declara deARCE v3. Ese formato no publica las tres longitudes y la interfaz muestra `—`, no un valor estimado. También existe la fuente seleccionable `ecallisto_v2`, etiquetada **Official e-CALLISTO (v2)**. No se mezclan en una misma consulta las detecciones deARCE, candidatos ML y heurísticas visuales.

La clave `official_v2` puede seguir existiendo en bases locales creadas por versiones antiguas; se conserva para no destruir historial, pero ya no es la fuente por defecto ni se presenta como procedencia de los datos deARCE v3.

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

- `GET /api/stations`: nombres, estado activo/inactivo y primer/último avistamiento.
- `GET /api/stations/geo`: mapa, procedencia de coordenadas FITS, estaciones sin mapear y recuentos.
- `GET /api/files?station=&date=`
- `GET /api/spectrogram?station=&date=&filename=`
- `GET /api/spectrogram/combine`
- `GET /api/spectrogram/zoom`
- `GET /api/files/download`
- `GET /api/spectrogram/export`
- `GET /api/lightcurve`
- `GET /api/goes`

### Catálogo y análisis

- `GET /api/bursts?start=&end=&station=&type=&source=`: Burst Reports; `end` es exclusivo.
- `GET /api/stats/stations?start=&end=&source=`
- `GET /api/stats/timeline?start=&end=&source=`
- `GET /api/xmatch/timeline?date=&source=`: disponibilidad y eventos por estación para el Xmatch interactivo.
- `GET /api/xmatch?start=&end=&tolerance_minutes=`: cruce de candidatos ML contra catálogo.
- `GET /api/burst/detect`
- `POST /api/analysis/type-ii-band-split`

### Tareas

`POST /api/tasks` acepta:

- `burst_detect_day`
- `spectral_overview`
- `combine_time`

Consulta progreso con `GET /api/tasks/{id}`, cancela con `POST /api/tasks/{id}/cancel` y abre el resultado comprimido con `GET /api/tasks/{id}/artifact`. La cola deduplica clics repetidos, limita trabajos activos, recupera tareas abandonadas y elimina resultados terminales tras la retención configurada.

### Qué hace «Scan selected station · full day»

Analiza todos los bloques FITS disponibles para la estación primaria y la fecha UTC seleccionadas. El worker combina el inventario local y el índice ETHZ, descarga los bloques que falten y ejecuta en cada uno el detector CNN+MIL ONNX. Si el postprocesado del modelo no localiza un evento, un transitorio visual especialmente fuerte puede mostrarse como señal heurística experimental; ambos métodos aparecen diferenciados en el resultado.

La vista inicial **Recommended** incluye detecciones CNN+MIL que superan el umbral del bundle y cualquier señal que coincida temporalmente y por estación con el catálogo oficial. Los filtros separan CNN+MIL, coincidencias deARCE y señales visuales experimentales. Estas últimas quedan excluidas por defecto, muestran una advertencia sobre RFI/ruido persistente y no se guardan automáticamente en `burst_events`.

El resumen indica bloques descubiertos, procesados y omitidos, candidatos CNN+MIL, señales experimentales y coincidencias oficiales. Los resultados se agrupan por bloque FITS y permiten abrir directamente el espectrograma de su momento. Repetir el análisis no duplica eventos ML: solo marca como guardados en esa ejecución los registros realmente insertados. Una coincidencia deARCE/e-CALLISTO se conserva como referencia; no convierte el tipo oficial en una clasificación producida por el modelo. Los registros heurísticos creados por versiones anteriores se conservan hasta ejecutar una limpieza explícita y revisada.

Ejemplo de overview multiestación entre dos instantes UTC:

```json
{
  "type": "spectral_overview",
  "station": "SPAIN-SIGUENZA",
  "date": "2026-07-28",
  "options": {
    "stations": ["SPAIN-SIGUENZA", "GERMANY-DLR"],
    "start_at": "2026-07-28T08:15:00Z",
    "end_at": "2026-07-28T12:45:00Z"
  }
}
```

El worker consulta todas las fechas atravesadas por el intervalo, recorta las muestras a `[start_at, end_at)`, agrupa por estación y eje de frecuencia compatible, calcula una mediana de background por grupo y reduce el eje temporal conservando máximos cortos. El artefacto distingue datos medidos, ficheros omitidos y estaciones sin observaciones.

### Qué hace «Combine next blocks»

Desde el bloque FITS seleccionado, toma ese bloque y hasta los tres siguientes de la lista de **la misma estación**. El backend admite de 2 a 16 filenames, verifica con `backend.security` que todos pertenecen a esa estación y fecha, y exige ejes de frecuencia iguales con tolerancia de `1e-3 MHz`. Después concatena las matrices en el eje temporal, aplica la resta de background al conjunto continuo y guarda un artefacto JSON gzip con UTC, MHz, intensidad relativa y contraste.

No combina estaciones, receptores incompatibles ni días distintos. Si cambia el eje de frecuencia, la tarea falla de forma explícita con el filename incompatible. Es útil para ver un burst que cruza el límite entre bloques consecutivos; no crea información nueva ni reinterpola frecuencias.

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
- Las bandas grises de Xmatch son intervalos heurísticos derivados de la hora del filename y una duración nominal configurable; las líneas rojas sí proceden del catálogo indicado.
- El cálculo Type II devuelve una advertencia experimental y no incluye todavía incertidumbres completas.

## Limitaciones conocidas

- Primera consulta lenta si debe descargar FITS o GOES.
- El catálogo y las listas de ficheros dependen de servicios ETHZ externos.
- La fuente AstroDoncel/UAH publica actualmente un certificado HTTPS no válido; la ingesta prueba HTTPS sin relajar TLS y luego el mismo recurso HTTP, con fallback mensual FHNW/ETHZ.
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
