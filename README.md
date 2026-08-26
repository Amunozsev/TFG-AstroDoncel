# AstroDoncel

Portal web para explorar, procesar y comparar espectrogramas solares de la red
[e-CALLISTO](https://www.e-callisto.org/). Es el Trabajo Fin de Grado de
Alfonso Muñoz Sevillano en la Universidad de Alcalá.

**Demostración temporal:** <https://tfg-astrodoncel-production.up.railway.app/>

La instancia de Railway permite probar la aplicación sin instalar nada. Es una
demostración con límites de uso y almacenamiento, no el alojamiento definitivo
del proyecto.

## Qué permite hacer

- Descubrir automáticamente estaciones activas y observaciones publicadas en el
  archivo e-CALLISTO/FHNW-ETHZ.
- Abrir uno o varios bloques FITS, compararlos por paneles o superponerlos y
  ampliar una región con datos de mayor resolución.
- Aplicar mitigación RFI, corrección de fondo, escalas lineal/logarítmica,
  contraste y distintos mapas de color.
- Medir deriva frecuencia-tiempo, consultar cabeceras FITS, trazar curvas de luz
  y superponer el flujo GOES/XRS-B.
- Crear resúmenes espectrales de intervalos, combinar bloques consecutivos y
  exportar FITS procesados, CSV y manifiestos reproducibles.
- Ejecutar detección experimental de bursts mediante CNN+MIL con ONNX Runtime.
- Consultar **Burst Reports**, estadísticas y Xmatch con el catálogo
  **deARCE (v3)**.
- Visualizar la red de estaciones y su estado reciente en un mapa interactivo.
- Cambiar entre tema oscuro y claro; la elección queda guardada en el navegador.

La clasificación automática sirve para priorizar observaciones para revisión.
No es un sistema oficial de alertas ni sustituye la interpretación científica.
La procedencia, métricas y limitaciones del modelo están en
[`MODEL_CARD.md`](MODEL_CARD.md).

## Inicio rápido con Docker

Esta es la instalación recomendada para probar o alojar AstroDoncel. Necesita
[Git](https://git-scm.com/) y Docker con el complemento Compose.

```bash
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
```

En Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\docker-up.ps1
```

En Linux o macOS:

```bash
sh scripts/docker-up.sh
```

El script:

1. crea `.env` con una contraseña aleatoria si todavía no existe;
2. valida la configuración de Compose;
3. construye frontend y backend;
4. ejecuta las migraciones;
5. inicia PostgreSQL, API, worker y servidor web;
6. espera hasta que `/ready` confirme que el sistema está operativo.

Después se puede abrir:

- aplicación: <http://localhost:8080>
- documentación de la API: <http://localhost:8080/docs>
- estado de preparación: <http://localhost:8080/ready>

Comandos habituales:

```bash
docker compose ps
docker compose logs -f
docker compose down
```

`docker compose down` conserva los volúmenes. Solo se eliminan al añadir
deliberadamente `-v`.

## Uso básico

1. Abre **Spectrograms**.
2. Filtra y marca una o varias estaciones.
3. Selecciona la fecha y un bloque FITS de la estación principal.
4. Pulsa **Load spectrogram**.
5. Usa **Processing**, **Display**, **Layers**, **Light curve** y **Tools** para
   ajustar o ampliar el análisis.

Se pueden comparar **hasta seis estaciones a la vez**. La interfaz bloquea
nuevas selecciones al alcanzar ese límite, que coincide con la validación del
backend.

El inventario se refresca automáticamente. Combina las estaciones activas del
archivo con las vistas durante los últimos 90 días; ese plazo se puede cambiar
con `STATION_RETENTION_DAYS`. Una estación nueva aparece al publicarse en el
archivo y una retirada desaparece al vencer la retención si ya no vuelve a
observarse. Las coordenadas se aprenden de las cabeceras FITS; los valores
manuales solo son una aproximación temporal para el mapa.

Los trabajos costosos, como un resumen espectral largo o la combinación de
bloques, se envían a una cola persistente. La interfaz muestra sus estados
`queued`, `running`, `succeeded`, `failed` o `cancelled` y permite cancelar los
que todavía no han terminado.

### Guía breve de herramientas

- **Drift ruler:** dos clics sobre el espectrograma miden `Δt`, `Δf` y la tasa
  de deriva en MHz/s.
- **Detect current file (ML):** clasifica el FITS principal cargado con el
  modelo CNN+MIL experimental. Muestra siempre probabilidad, umbral y resultado;
  una clasificación positiva puede no producir un intervalo localizado y debe
  revisarse visualmente.
- **Spectral overview:** crea en el worker una vista reducida de un intervalo
  UTC más largo para las estaciones seleccionadas.
- **Combine current + next blocks:** parte del FITS seleccionado y une hasta
  tres bloques posteriores de la misma estación cuando sus ejes de frecuencia
  son compatibles. Al terminar muestra automáticamente un espectrograma
  continuo bajo la observación actual; no mezcla estaciones.
- **Download original FITS / Export processed FITS:** descargan respectivamente
  la observación intacta y una copia con el procesamiento elegido y sus ejes.
- **Export analysis manifest:** guarda en JSON los FITS seleccionados, unidades,
  ajustes y procedencia científica, sin rutas locales.

La misma ayuda aparece dentro de **Tools** y cada acción tiene una explicación
al mantener el puntero encima.

## Arquitectura

AstroDoncel tiene un único repositorio y admite dos formas de ejecución:

| Entorno | Componentes | Uso recomendado |
|---|---|---|
| `Dockerfile` | React estático + FastAPI + worker en un contenedor; PostgreSQL gestionado aparte | Railway u otro host sencillo |
| `docker-compose.yml` | Nginx, API, worker, migraciones y PostgreSQL en servicios separados | Servidor propio, NAS o UAH |

El backend descarga bajo demanda desde e-CALLISTO, mantiene una caché local y
guarda inventario, catálogo, tareas y metadatos en SQLAlchemy. PostgreSQL es la
opción de producción; SQLite funciona como alternativa local. El worker reclama
las tareas desde la base de datos, por lo que no dependen de la pestaña del
navegador.

Los FITS se resuelven en este orden: caché de `/data`, archivo local/NAS opcional
y, si no existe una copia, descarga bajo demanda del archivo público de
FHNW/ETHZ. Los **Burst Reports** no consultan directamente una base de datos
privada o preexistente: AstroDoncel obtiene los listados mensuales publicados
por el portal UAH, los normaliza como **deARCE (v3)** y mantiene su propia copia
en PostgreSQL —o en SQLite durante un desarrollo local— con refresco periódico.

```text
Navegador
   │
   ├── React + Plotly
   │        │
   │        └── API FastAPI ── PostgreSQL/SQLite
   │                 │
   │                 ├── archivo e-CALLISTO
   │                 ├── catálogo deARCE (v3)
   │                 └── NOAA/SunPy (GOES)
   │
   └── cola SQL ── worker ── /data (FITS, caché y artefactos)
```

El frontend usa el mismo origen en producción. Durante el desarrollo, Vite usa
`http://localhost:8000` por defecto.

## Desarrollo local

Requisitos:

- Python 3.12
- Node.js 22
- npm

### Backend

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Linux o macOS:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn backend.main:app --reload
```

Sin `DATABASE_URL`, el backend crea `data/astrodoncel.db` con SQLite. La API
queda en <http://localhost:8000>.

Para que funcionen los trabajos en cola, abre otra terminal y ejecuta:

```powershell
.\.venv\Scripts\python.exe -m backend.worker
```

En Linux/macOS cambia la ruta del intérprete por `.venv/bin/python`.

### Frontend

En otra terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite muestra la dirección local, normalmente <http://localhost:5173>.

Si la API está en otro origen, crea `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

## Perfiles de dependencias

| Archivo | Contenido |
|---|---|
| `requirements.txt` | runtime de la API, procesamiento científico, ONNX y persistencia |
| `requirements-dev.txt` | runtime más pruebas, Ruff y auditoría de dependencias |
| `requirements-ml.txt` | runtime más PyTorch CPU y ONNX para exportar un modelo autorizado |

La API de producción no importa PyTorch. El modelo se sirve con ONNX Runtime;
PyTorch solo es necesario para `tools/export_onnx.py`.

Instalación de un perfil:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Las versiones están fijadas para que una instalación nueva sea reproducible.
`mpl-animators` se declara expresamente porque lo necesita la ruta de importación
de `sunpy.timeseries` usada por el proyecto.

## Configuración

Copia `.env.example` a `.env` para configurar Docker manualmente. Las variables
principales son:

| Variable | Valor por defecto | Función |
|---|---|---|
| `DATABASE_URL` | SQLite local | conexión SQLAlchemy; producción usa PostgreSQL |
| `DATA_DIR_LOCAL` | `data/` | caché local de FITS y estado derivado |
| `TASK_RESULT_DIR` | `data/task_results` | artefactos de trabajos persistentes |
| `ECALLISTO_DATA_DIR` | ruta NAS histórica | archivo FITS local opcional y de solo lectura |
| `FRONTEND_ORIGINS` | orígenes Vite locales | lista CORS separada por comas |
| `BURST_MODEL_DIR` | modelo incluido | bundle ONNX del detector |
| `BURST_INTRA_OP_THREADS` | `1` | hilos CPU de ONNX Runtime |
| `STATION_REFRESH_MINUTES` | `60` | cadencia del inventario remoto |
| `STATION_RETENTION_DAYS` | `90` | tiempo que se conserva una estación conocida |
| `CATALOG_REFRESH_HOURS` | `12` | cadencia de actualización del catálogo |
| `CATALOG_FETCH_TIMEOUT_SECONDS` | `12` | espera máxima por cada origen mensual del catálogo |
| `MAX_ACTIVE_TASKS` | `100` | límite de trabajos activos |
| `TASK_STALE_MINUTES` | `15` | recuperación de trabajos interrumpidos |
| `TASK_RETENTION_DAYS` | `30` | retención de tareas terminadas |
| `OVERVIEW_MAX_STATIONS` | `120` | máximo de estaciones por resumen |
| `OVERVIEW_MAX_HOURS` | `72` | intervalo máximo de un resumen |
| `MAX_FITS_DOWNLOAD_BYTES` | `134217728` | tamaño máximo de una descarga FITS |

`.env.example` contiene también los valores específicos de Docker Compose. No
subas `.env`, contraseñas, archivos FITS ni bases de datos al repositorio.

## Despliegue en Railway

El `Dockerfile` raíz está preparado para un despliegue monolítico: construye el
frontend y ejecuta migraciones, worker y API en un mismo servicio.

1. Crea un proyecto desde este repositorio de GitHub.
2. Añade un servicio PostgreSQL al proyecto.
3. En el servicio AstroDoncel define:

   ```dotenv
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   DATA_DIR_LOCAL=/data
   TASK_RESULT_DIR=/data/task_results
   SERVE_FRONTEND=1
   RUN_TASK_WORKER=1
   BURST_INTRA_OP_THREADS=1
   ```

4. Añade un volumen persistente montado en `/data`.
5. Mantén una réplica mientras API y worker compartan el mismo servicio.
6. Configura `/ready` como healthcheck; `railway.toml` ya declara este valor.
7. Genera el dominio público desde **Networking**.
8. Activa **Wait for CI** para que Railway no publique una revisión que no haya
   superado GitHub Actions.

Railway proporciona `PORT` y el dominio `*.up.railway.app`. Un dominio propio se
puede conectar más adelante cuando exista acceso al DNS de la UAH. Para un
alojamiento permanente en la universidad se recomienda el stack Compose, una
ruta persistente para `/data`, PostgreSQL, HTTPS y copias de seguridad externas.

## Despliegue en un NAS o servidor UAH

Sí: el procedimiento parte del inicio rápido con Docker Compose, pero antes de
abrirlo a alumnos conviene completar esta lista.

1. Comprueba que el NAS dispone de Docker Engine, Compose v2, acceso saliente a
   FHNW/ETHZ, al portal UAH y a NOAA, y recursos suficientes. La construcción de
   la imagen es la prueba definitiva de que la CPU del NAS dispone de un wheel
   compatible de ONNX Runtime.
2. Clona el repositorio por SSH y ejecuta `scripts/docker-up.sh`. El script crea
   `.env`, genera la contraseña de PostgreSQL, construye las imágenes, aplica
   migraciones y espera a `/ready`.
3. Para usar directorios persistentes del NAS, cambia en `.env`:

   ```dotenv
   APP_DATA_SOURCE=/ruta/astrodoncel/data
   ECALLISTO_HOST_DIR=/ruta/opcional/ecallistodata
   WEB_PORT=8080
   ```

   El directorio de datos debe poder escribirlo el UID/GID `10001`; el archivo
   e-CALLISTO solo necesita permisos de lectura y se monta como `ro`.
4. Publica únicamente el servicio `web`. En producción, colócalo detrás del
   proxy inverso del NAS con HTTPS y limita el acceso a la red UAH/VPN o añade
   autenticación en el proxy: la aplicación no incorpora cuentas de usuario.
5. Verifica `https://<host>/ready`, abre un espectrograma, ejecuta una detección,
   comprueba Burst Reports/Xmatch y lanza una tarea corta antes del curso.
6. Programa `scripts/backup.sh` o `scripts/backup.ps1`, copia `backups/` a otro
   almacenamiento y ensaya una restauración. Vigila además espacio de `/data`,
   memoria del worker y logs rotados.

Para actualizar después:

```bash
git pull --ff-only
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8080/ready
```

Las migraciones se ejecutan antes de arrancar la API. Mantén una sola instancia
del servicio `worker` salvo que se valide expresamente el consumo de CPU y el
comportamiento de la cola en el NAS.

## Comprobaciones antes de publicar

Backend:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check backend tests migrations tools scripts/start_single_host.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip_audit -r requirements-dev.txt
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run test
npm run build
npm audit --audit-level=high
```

Infraestructura:

```bash
docker compose config --quiet
docker build -t astrodoncel-single .
```

GitHub Actions ejecuta estas comprobaciones y además prueba migraciones hacia
delante/atrás y arranca tanto el stack Compose como la imagen monolítica.

## Datos, seguridad y mantenimiento

- Los clientes nunca envían rutas locales arbitrarias. Estación, fecha y nombre
  FITS pasan por `backend.security` y se resuelven dentro de raíces permitidas.
- El archivo NAS se monta como solo lectura.
- Los contenedores ejecutan usuarios sin privilegios y aplican cabeceras HTTP de
  seguridad. Nginx añade limitación básica de peticiones en el stack Compose.
- El despliegue monolítico público no incluye autenticación de usuarios; debe
  tratarse como un portal de investigación de solo lectura.
- La disponibilidad depende también de e-CALLISTO, del catálogo UAH y de NOAA.
  Cuando una fuente opcional falla, el resto de la API continúa operativo y la
  interfaz indica el fallback o la ausencia de datos.
- `tools/prune_cache.py` ofrece una simulación por defecto y solo elimina FITS al
  pasar `--apply`.

Copias de seguridad del stack Compose:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1
```

```bash
sh scripts/backup.sh
```

Los backups se guardan en `backups/`, fuera de Git, con sumas SHA-256. Hay que
copiarlos después a almacenamiento externo y probar periódicamente su
restauración.

## Créditos y procedencia

- **Autor:** Alfonso Muñoz Sevillano, Universidad de Alcalá, 2026.
- **Red e-CALLISTO:** Christian Monstein, FHNW/ETHZ, observatorios participantes
  y equipos que operan y publican los instrumentos y datos.
- **Portal AstroDoncel original (UAH):** referencia del producto y fuente del
  catálogo **deARCE (v3)**.
- **Sahan S. Liyanage:** `e-Callisto_FITS_Analyzer` v2.8.0 y `Burst_No_Burst`,
  usados como implementaciones de referencia para partes del procesamiento,
  interacción y detección, adaptadas y verificadas en este proyecto.
- **Ecosistema abierto:** FastAPI, Astropy, SunPy, NumPy, SciPy, SQLAlchemy,
  ONNX Runtime, React, Vite y Plotly.

El registro detallado está en
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). El artículo del FITS Analyzer
está disponible en <https://doi.org/10.1093/rasti/rzag056>.

## Licencia

El repositorio todavía no declara una licencia raíz. Eso significa que no se
concede automáticamente permiso de reutilización o redistribución. Antes de una
publicación formal deben acordarse la licencia del proyecto y el permiso para
redistribuir los pesos ONNX; consulta `THIRD_PARTY_NOTICES.md` y `MODEL_CARD.md`.

## Contribuir

Consulta [`CONTRIBUTING.md`](CONTRIBUTING.md). Mantén los cambios pequeños,
acompañados de pruebas y con unidades y procedencia científica explícitas. Los
proyectos de referencia y la documentación interna no forman parte del código
público y no deben añadirse al repositorio.
