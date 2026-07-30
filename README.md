# AstroDoncel

Portal web para visualizar y analizar espectrogramas solares de la red e-CALLISTO.

Trabajo de Fin de Grado — Universidad de Alcalá, 2026
Autor: Alfonso Muñoz Sevillano

AstroDoncel combina un frontend React con una API FastAPI y un worker científico. Permite explorar estaciones y ficheros FITS, procesar espectrogramas, comparar observaciones, consultar el catálogo de bursts y ejecutar análisis de día completo sin bloquear la API.

> Estado: prototipo funcional de TFG. Los cálculos Type II y algunos localizadores visuales son experimentales; deben validarse antes de usarse como resultado científico. Consulta [ROADMAP_COMPLETO_TFG.md](ROADMAP_COMPLETO_TFG.md) para la auditoría y el plan pendiente.

## Inicio rápido recomendado

Para probar o desplegar AstroDoncel en otro PC o en un NAS, usa Docker. El stack incluye PostgreSQL, migraciones, API, worker y frontend; no hace falta instalar Python ni Node.js en el host.

Windows, con Docker Desktop ya abierto:

```powershell
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
powershell -ExecutionPolicy Bypass -File .\scripts\docker-up.ps1
```

Linux o NAS con Docker Engine y el plugin Compose:

```bash
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
sh scripts/docker-up.sh
```

Los scripts generan un `.env` con contraseña aleatoria, construyen las imágenes, ejecutan Alembic, esperan a que la API esté lista y muestran la URL final. Por defecto el portal queda en <http://localhost:8080>, la documentación de la API en <http://localhost:8080/docs> y el diagnóstico en <http://localhost:8080/ready>.

Si el profesor no tiene Git, puede descargar **Code → Download ZIP** desde GitHub, descomprimirlo y ejecutar el mismo script desde esa carpeta.

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

Elige una de estas dos formas de instalación:

| Uso | Requisitos del host | Base de datos | Recomendación |
|---|---|---|---|
| Profesor, demo estable o NAS | Docker Engine/Desktop con `docker compose` | PostgreSQL incluido | **Opción recomendada** |
| Desarrollo del código | Python 3.12, Node.js 22 y npm | SQLite local | Para modificar backend/frontend |

En Windows, Docker Desktop usa WSL 2 y necesita virtualización de hardware activada. La guía oficial de instalación está en [Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/). En Linux/NAS basta Docker Engine con el plugin Compose v2; compruébalo con `docker compose version`.

Las dependencias están separadas por uso:

| Archivo | Contenido |
|---|---|
| `requirements.txt` | API, procesamiento, GOES, ONNX, persistencia y migraciones |
| `requirements-dev.txt` | runtime más pytest, Ruff, TestClient y auditoría de dependencias |
| `requirements-ml.txt` | toolchain opcional de exportación/reentrenamiento con PyTorch CPU |

Los tres perfiles están fijados a versiones verificadas. `requirements-dev.txt` incluye el runtime mediante `-r requirements.txt`; `requirements-ml.txt` incluye el perfil de desarrollo. PyTorch no se importa ni se necesita para servir la API o ejecutar ONNX.

## Desarrollo local

Clona el repositorio y entra en él:

```powershell
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
```

### Windows

Crea el entorno e instala el perfil de desarrollo:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
New-Item -ItemType Directory -Force data | Out-Null
.\.venv\Scripts\python.exe -m alembic upgrade head
Push-Location frontend
npm ci
Pop-Location
```

### Linux/macOS

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
mkdir -p data
python -m alembic upgrade head
(cd frontend && npm ci)
```

### Arranque de desarrollo

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

En Linux/macOS sustituye `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

### Build local de producción

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
| `APP_DATA_SOURCE` | volumen Docker o bind mount para caché/artefactos | volumen `app_data` |
| `DATA_DIR_LOCAL` | FITS descargados, GOES y coordenadas aprendidas | `data/` del repositorio |
| `TASK_RESULT_DIR` | artefactos JSON gzip del worker | `data/task_results/` |
| `ECALLISTO_HOST_DIR` | ruta del host con archivo FITS opcional | `./data/archive` |
| `ECALLISTO_DATA_DIR` | archivo externo `YYYY/MM/DD/*.fit*` | ruta histórica NAS, opcional |
| `WEB_PORT` | puerto publicado por Nginx | `8080` |
| `FRONTEND_ORIGINS` | orígenes CORS separados por coma | localhost/127.0.0.1:5173 |
| `BURST_MODEL_DIR` | bundle ONNX alternativo | `backend/model/burst_detector/` |
| `BURST_INTRA_OP_THREADS` | hilos CPU de ONNX | `1` |
| `WORKER_MEMORY_LIMIT` | límite de memoria del worker Docker | `1g` |
| `WORKER_CPU_LIMIT` | límite de CPU del worker Docker | `2.0` |
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

El Compose crea cinco servicios:

| Servicio | Responsabilidad | Expuesto al host |
|---|---|---|
| `db` | PostgreSQL persistente | No |
| `migrate` | `alembic upgrade head`; termina antes de arrancar la app | No |
| `api` | FastAPI, un proceso | No |
| `worker` | tareas científicas pesadas | No |
| `web` | React + Nginx y proxy hacia la API | `WEB_PORT`, 8080 por defecto |

API y worker usan la misma imagen para evitar instalaciones divergentes. El archivo e-CALLISTO externo se monta en solo lectura; la API no recibe rutas locales del navegador. Los logs JSON rotan a tres ficheros de 10 MB por servicio.

### Primer arranque manual

Los scripts de inicio rápido son la vía más sencilla. La alternativa manual es:

```powershell
Copy-Item .env.example .env
```

Edita `.env` y sustituye `change-this-password` en **las dos apariciones**. Usa una contraseña alfanumérica larga o codifica para URL los caracteres especiales dentro de `DATABASE_URL`; el script automático evita este problema generando hexadecimal. Si existe un archivo local/NAS, configura `ECALLISTO_HOST_DIR`; si no, deja la carpeta vacía y AstroDoncel consultará ETHZ. Después:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

El primer build descarga las imágenes base e instala las dependencias, por lo que tarda más que los siguientes. No borres `.env`, el volumen `astrodoncel_postgres_data` ni `astrodoncel_app_data` durante una actualización.

### Instalación en un NAS

1. Instala Docker/Container Manager con Compose y habilita acceso SSH o usa la función de proyectos Compose del NAS.
2. Copia o clona el repositorio en una carpeta administrada, por ejemplo `/volume1/docker/astrodoncel`.
3. Ejecuta `sh scripts/docker-up.sh` una vez. El volumen Docker es la opción más portable.
4. Para guardar caché y artefactos en una carpeta visible del NAS, cambia `APP_DATA_SOURCE` por una ruta absoluta y dale permisos de escritura al UID/GID `10001`. El archivo de observaciones indicado por `ECALLISTO_HOST_DIR` solo necesita permiso de lectura.
5. Publica únicamente el puerto de `web`. Para acceso fuera de la red interna, coloca el proxy HTTPS del NAS delante del portal y añade su URL a `FRONTEND_ORIGINS`.

Ejemplo de `.env` para un Synology; adapta los volúmenes reales:

```dotenv
APP_DATA_SOURCE=/volume1/docker/astrodoncel/data
ECALLISTO_HOST_DIR=/volume1/web/ecallistodata
WEB_PORT=8080
FRONTEND_ORIGINS=https://astrodoncel.universidad.example
```

En Linux/NAS, prepara el bind mount mutable antes del arranque:

```bash
sudo mkdir -p /volume1/docker/astrodoncel/data
sudo chown -R 10001:10001 /volume1/docker/astrodoncel/data
```

No cambies permisos del archivo científico si ya es compartido por otros servicios; basta que Docker pueda leerlo.

### Operación habitual

```bash
# Estado y salud
docker compose ps
curl http://127.0.0.1:8080/ready

# Logs recientes
docker compose logs --tail 200 api worker

# Reinicio sin borrar datos
docker compose restart api worker web

# Actualización del código y de las imágenes
git pull
docker compose up --build -d

# Parada; conserva base de datos y caché
docker compose down
```

No uses `docker compose down -v` salvo que quieras eliminar de forma irreversible los volúmenes del proyecto.

### Backup y recuperación

El backup incluye un `pg_dump` consistente y, salvo que se pida solo base de datos, la caché/artefactos de `/data`. También genera hashes SHA-256:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1
# o solo PostgreSQL
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1 -DatabaseOnly
```

```bash
sh scripts/backup.sh
# o solo PostgreSQL
sh scripts/backup.sh --database-only
```

Los resultados quedan en `backups/YYYYMMDD-HHMMSS/`, una carpeta ignorada por Git que debe copiarse a otro volumen o sistema de backup. Para una recuperación, detén `api`, `worker` y `web`; restaura `postgres.dump` con `pg_restore` y extrae `app-data.tar.gz` únicamente sobre un volumen de aplicación vacío o una copia aislada. Haz primero una prueba de restauración en otro proyecto/host: una copia no se considera backup verificado hasta que se ha restaurado.

### Comprobación del despliegue

Después de instalar:

- `docker compose ps` debe mostrar `db`, `api`, `worker` y `web` activos y saludables; `migrate` debe aparecer finalizado con código 0.
- `/health` confirma que el proceso API responde.
- `/ready` devuelve `status: ok` y `database: ok`; el modelo ONNX aparece por separado.
- `/docs` debe cargar OpenAPI a través de Nginx.
- Crea una tarea corta desde la interfaz y confirma que el worker actualiza su progreso.
- Reinicia el stack y confirma que catálogo, tareas y coordenadas siguen presentes.

El CI construye y levanta el Compose sobre Linux para detectar errores de imagen, migración, proxy y salud. El rendimiento, permisos y rutas deben comprobarse además en el NAS concreto porque dependen de su CPU, arquitectura, memoria y almacenamiento.

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
.\.venv\Scripts\python.exe -m pip_audit -r requirements-dev.txt
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
