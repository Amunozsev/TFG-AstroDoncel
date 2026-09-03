# AstroDoncel Studio

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
- Crear resúmenes espectrales de intervalos y unir bloques consecutivos en un
  espectrograma continuo, que se dibuja bajo la observación actual.
- Exportar FITS procesados, CSV y manifiestos reproducibles.
- Ejecutar detección experimental de bursts mediante CNN+MIL con ONNX Runtime.
- Consultar **Burst Reports**, estadísticas y Xmatch desde la base actual del
  portal UAH; los catálogos mensuales permanecen como fuente alternativa.
- Visualizar la red de estaciones y su estado reciente en un mapa interactivo.
- Cambiar entre tema oscuro y claro; la elección queda guardada en el navegador.

La clasificación automática sirve para priorizar observaciones para revisión.
No es un sistema oficial de alertas ni sustituye la interpretación científica.
La procedencia, métricas y limitaciones del modelo están en
[`MODEL_CARD.md`](MODEL_CARD.md).

## Inicio rápido con Docker

Esta es la instalación recomendada para probar o alojar AstroDoncel Studio. Necesita
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
5. inicia PostgreSQL, API, worker, mantenimiento de caché y servidor web;
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

### Enlaces directos a una observación

La web puede abrir directamente un FITS concreto mediante tres parámetros:

```text
https://<host>/?station=GLASGOW&date=2026-08-25&filename=GLASGOW_20260825_123000.fit.gz
```

También admite los nombres heredados `estacion`, `fecha` y `archivo`. La
estación y la fecha deben coincidir con el nombre FITS; el backend vuelve a
validar los tres valores y nunca acepta una ruta local. El botón **Copy
observation link** genera el enlace de la observación cargada. Esta es la URL
que puede construir el portal AstroDoncel original al sustituir su enlace a
Plotly.

### Guía breve de herramientas

- **Drift ruler:** dos clics sobre el espectrograma miden `Δt`, `Δf` y la tasa
  de deriva en MHz/s.
- **Light curve:** traza la intensidad frente al tiempo en hasta ocho
  frecuencias. La curva aparece **bajo el espectrograma y comparte su eje
  temporal**, con los mismos márgenes, de modo que cada pico se lee sobre la
  misma escala UTC. Se puede exportar a CSV o cerrar sin perder la observación.
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

**Spectral overview y Combine se confunden con facilidad**, pero sirven para
cosas opuestas:

| | Combine current + next blocks | Spectral overview |
|---|---|---|
| Resolución | nativa, sin reducir | como máximo 120 columnas por fichero |
| Estaciones | una | varias a la vez |
| Intervalo | bloques consecutivos de un día | cualquier ventana UTC, hasta 72 h |
| Línea base | la misma del espectrograma normal | mediana por grupo de receptor |
| Salida | un mapa de calor continuo | un segmento por fichero, con huecos visibles |
| Para qué | **medir** un evento que cruza el corte entre bloques | **localizar** dónde ocurrió algo |

Combine toma el fichero seleccionado y hasta tres bloques siguientes del
**mismo receptor (`focus_code`)**, incluso con «All receivers» seleccionado.
El botón indica el número real de bloques: cuatro bloques de 15 minutos cubren
aproximadamente una hora. Si faltan bloques al final del día o hay un hueco,
la interfaz avisa y no cuenta ficheros de otros receptores como tiempo adicional.
El worker verifica los ejes de frecuencia y los tiempos reales de los FITS:
rechaza huecos importantes, solapamientos y cambios de configuración, explicando
el motivo. Los pequeños solapamientos de frontera se recortan sin desplazar
las horas originales; el resultado informa de las muestras omitidas.

En el selector, `≈45:00` significa que el inicio publicado está a un máximo de
dos segundos del cuarto de hora. La hora exacta del archivo aparece al mantener
el cursor encima. Los gráficos y las exportaciones conservan los tiempos FITS,
sin redondearlos. Los números junto a los horarios distinguen los receptores.

## Arquitectura

AstroDoncel Studio tiene un único repositorio y admite dos formas de ejecución:

| Entorno | Componentes | Uso recomendado |
|---|---|---|
| `Dockerfile` | React estático + FastAPI + worker en un contenedor; PostgreSQL gestionado aparte | Railway u otro host sencillo |
| `docker-compose.yml` | Nginx, API, worker, mantenimiento de caché, migraciones y PostgreSQL en servicios separados | Servidor propio, NAS o infraestructura institucional |

El backend descarga bajo demanda desde e-CALLISTO, mantiene una caché local y
guarda inventario, catálogo, tareas y metadatos en SQLAlchemy. PostgreSQL es la
opción de producción; SQLite funciona como alternativa local. El worker reclama
las tareas desde la base de datos, por lo que no dependen de la pestaña del
navegador.

Los FITS se resuelven en este orden: caché de `/data`, archivo local/NAS opcional
y, si no existe una copia, descarga bajo demanda del archivo público de
FHNW/ETHZ.

En el NAS, los **Burst Reports** se leen de la base MySQL/MariaDB mantenida por
el portal AstroDoncel UAH. La aplicación detecta una tabla o vista compatible,
normaliza sus columnas y sincroniza una copia propia en PostgreSQL cada hora.
Una caída temporal de esa base externa no derriba la API: los datos ya
sincronizados siguen disponibles. Para desarrollo y demostraciones sin acceso
a la UAH se conservan como fuentes explícitas los ficheros mensuales publicados
(`dearce_v3`, `ecallisto_v2` y `legacy_monthly`).

En **Xmatch**, los marcadores rojos son eventos de la fuente configurada. Cada
fila separa un receptor o `focus_code`; el marcador aparece en los receptores
que tienen un bloque asociado a ese instante y abre el FITS exacto de la fila
seleccionada. Las bandas grises de disponibilidad se infieren del listado
diario de ficheros de FHNW/ETHZ a partir de la hora del nombre y una duración
nominal de 15 minutos. Estas bandas son una heurística, no una medida leída del
interior del FITS.

```text
Navegador
   │
   ├── React + Plotly
   │        │
   │        └── API FastAPI ── PostgreSQL/SQLite
   │                 │
   │                 ├── archivo e-CALLISTO
   │                 ├── Burst Reports UAH (copia sincronizada)
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
| `BURST_CATALOG_SOURCE` | automático | `uah_mysql` en el NAS; `dearce_v3` sin MySQL configurado |
| `BURST_SOURCE_MYSQL_*` | sin valor | host, puerto, base, usuario, contraseña y tabla/vista de solo lectura |
| `BURST_SOURCE_REFRESH_MINUTES` | `60` | intervalo de sincronización de la base UAH |
| `FITS_CACHE_MAX_GB` | `20` | tamaño objetivo máximo de la caché descargada |
| `FITS_CACHE_MAX_AGE_DAYS` | `90` | antigüedad máxima de los FITS descargados |
| `FITS_CACHE_MIN_IDLE_MINUTES` | `60` | protege ficheros recién descargados o modificados frente al borrado |
| `FITS_CACHE_MIN_FREE_GB` | `5` | espacio libre que se intenta preservar en el volumen |
| `FITS_CACHE_PRUNE_APPLY` | `false` | `false` simula; `true` activa la limpieza programada |

`.env.example` contiene también los valores específicos de Docker Compose. No
subas `.env`, contraseñas, archivos FITS ni bases de datos al repositorio.

## Despliegue en Railway

El `Dockerfile` raíz está preparado para un despliegue monolítico: construye el
frontend y ejecuta migraciones, worker y API en un mismo servicio.

1. Crea un proyecto desde este repositorio de GitHub.
2. Añade un servicio PostgreSQL al proyecto.
3. En el servicio AstroDoncel Studio define:

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

## Despliegue en un NAS o servidor propio

El procedimiento parte del inicio rápido con Docker Compose. Antes de publicar
la instalación conviene completar esta lista.

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
4. Para usar la base actual de Burst Reports, añade a `.env` un usuario MySQL
   de solo lectura y configura:

   ```dotenv
   BURST_CATALOG_SOURCE=uah_mysql
   BURST_SOURCE_MYSQL_HOST=host.docker.internal
   BURST_SOURCE_MYSQL_PORT=3306
   BURST_SOURCE_MYSQL_DATABASE=srbs_callisto
   BURST_SOURCE_MYSQL_USER=<usuario_de_solo_lectura>
   BURST_SOURCE_MYSQL_PASSWORD='<contraseña>'
   BURST_SOURCE_MYSQL_TABLE=
   ```

   La tabla puede quedar vacía si solo existe una tabla o vista con las columnas
   compatibles. MySQL debe escuchar en una interfaz interna alcanzable desde la
   red Docker y el usuario debe admitir conexiones desde esa red; una cuenta
   restringida únicamente a `localhost` no será suficiente. No publiques MySQL
   en Internet ni uses una cuenta administradora en el repositorio.
5. Publica únicamente el servicio `web`. En producción, colócalo detrás del
   proxy inverso del NAS con HTTPS y limita el acceso a una red privada/VPN o
   añade autenticación en el proxy: la aplicación no incorpora cuentas de
   usuario.
6. Verifica `https://<host>/ready`, abre un espectrograma, ejecuta una detección,
   comprueba Burst Reports/Xmatch y lanza una tarea corta del worker.
7. Programa `scripts/backup.sh` o `scripts/backup.ps1`, copia `backups/` a otro
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

El stack ya está desplegado detrás del proxy HTTPS de un Synology. Aún deben
validarse en ese host la lectura real de MySQL con una cuenta limitada, los
límites de caché elegidos y un ensayo documentado de copia/restauración.

### Consideraciones operativas

AstroDoncel descarga los FITS **bajo demanda**: la primera vez que alguien abre
un bloque se baja del archivo de FHNW/ETHZ y queda en la caché de `/data`; a
partir de ahí se reutiliza sin volver a descargarlo. Si se dispone de una copia
del archivo e-CALLISTO, se puede montar en `ECALLISTO_HOST_DIR`: se lee como
solo lectura y tiene prioridad sobre la descarga remota.

La caché FITS no sustituye por completo la conexión a internet:

- **Burst Reports** y Statistics conservan en la base propia los meses ya
  sincronizados. La fuente MySQL se revisa cada `BURST_SOURCE_REFRESH_MINUTES`;
  las fuentes mensuales usan `CATALOG_REFRESH_HOURS`.
- Las filas por `focus_code` y las bandas grises de **Xmatch** se construyen
  desde el índice diario vivo de FHNW/ETHZ; sin acceso a ese índice pueden
  faltar aunque el catálogo esté guardado.
- La superposición **GOES** depende de NOAA/SunPy y puede no estar disponible
  sin conexión.
- *Spectral overview* y *Combine* comparten un único worker y se ejecutan en
  cola. El resto del portal sigue disponible mientras terminan.

El servicio `cache-maintenance` comprueba periódicamente tamaño, antigüedad y
espacio libre de `/data`. Solo ve la caché descargada: el archivo e-CALLISTO se
monta exclusivamente en API/worker y siempre como solo lectura. La primera
ejecución debe permanecer con `FITS_CACHE_PRUNE_APPLY=false`; revisa:

```bash
docker compose logs cache-maintenance
```

Cuando los límites sean correctos, cambia la variable a `true` y recrea el
servicio. `tools/prune_cache.py` ofrece además una simulación manual. El borrado
exige que la carpeta contenga la marca creada por la aplicación y vuelve a
comprobar que cada fichero no haya cambiado desde que se planificó.

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

Las pruebas se agrupan en cinco archivos backend: API/seguridad, catálogo/bases
de datos, worker/combinación, procesamiento/exportación y limpieza de caché.
El frontend tiene dos: `App.navigation.test.jsx` para navegación, enlaces y
selección de bloques, y `panels.test.jsx` para paneles y resultados. La prueba
del worker con FITS del archivo público solo se activa expresamente con
`ASTRODONCEL_LIVE_COMBINE=1`; la de MariaDB requiere una base de pruebas indicada
en `ASTRODONCEL_TEST_MYSQL_URL`.

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
- `cache-maintenance` y `tools/prune_cache.py` solo actúan sobre FITS de la caché
  marcada. El modo programado no borra mientras `FITS_CACHE_PRUNE_APPLY=false`.

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

## Solución de problemas

| Síntoma | Causa habitual | Qué hacer |
|---|---|---|
| Una tarea se queda siempre en `queued` | el worker no está en marcha | en Compose, `docker compose ps` debe mostrar el servicio `worker`; en desarrollo local hay que lanzarlo aparte con `python -m backend.worker` |
| `/ready` no responde tras arrancar | migraciones o PostgreSQL aún iniciando | `docker compose logs -f migrate api` |
| Una estación no muestra ficheros ese día | no hay observaciones publicadas o el archivo remoto no responde | prueba otra fecha y revisa los logs de la API |
| **Burst Reports** está vacío en el NAS | MySQL no es alcanzable desde la red Docker, rechaza el usuario, la tabla no es compatible o la fuente no está configurada | revisa `docker compose logs api`, comprueba escucha y permisos internos con la cuenta de solo lectura y fija `BURST_SOURCE_MYSQL_TABLE` si hay varias candidatas |
| La caché sigue creciendo | la limpieza está en simulación o sus límites aún no se alcanzan | revisa `docker compose logs cache-maintenance`; valida el plan y después activa `FITS_CACHE_PRUNE_APPLY=true` |
| *Combine* falla con «Incompatible frequency axis» | los bloques no comparten la misma configuración de receptor | selecciona otro bloque o limita la combinación al mismo `focus_code` |

## Créditos y procedencia

- **Autor:** Alfonso Muñoz Sevillano, Universidad de Alcalá, 2026.
- **Red e-CALLISTO:** Christian Monstein, FHNW/ETHZ, observatorios participantes
  y equipos que operan y publican los instrumentos y datos.
- **Portal AstroDoncel original (UAH):** referencia del producto y fuente de la
  base actual de Burst Reports; sus catálogos mensuales se conservan como
  alternativa explícita.
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

El funcionamiento operativo está resumido en
[`MANUAL_MANTENIMIENTO.md`](MANUAL_MANTENIMIENTO.md) y el texto académico de
partida en [`MEMORIA_BORRADOR.md`](MEMORIA_BORRADOR.md).
