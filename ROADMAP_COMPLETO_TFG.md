# ROADMAP COMPLETO — TFG AstroDoncel

**Auditoría técnica y plan de trabajo**
Fecha del análisis: 2026-07-11
Ámbito revisado: repositorio completo (backend, frontend, configuración, despliegue), web original `astrodoncel.uah.es/dashboard`, `Sahan/e-Callisto_FITS_Analyzer-master` (v2.7.0), `Sahan/Burst_No_Burst-master`, `Sahan/ecallistolib-main`, carpeta `Anteproyecto/` y `PROMPT_FABLE5.md`.

> **Convención de este documento**: cada afirmación se etiqueta como **[HECHO]** (verificado en código/web), **[PROBLEMA]** (defecto confirmado), **[HIPÓTESIS]** (probable, no verificado) o **[RECOMENDACIÓN]**.

## Estado de ejecución del roadmap — 2026-07-12

El roadmap se ha llevado a código en una primera implementación integral. Estado verificado:

- **F0 completada**: `file_path` devuelve 410, identificadores y contexto estación/fecha/fichero están validados en `backend/security.py`; GZip y serialización NumPy están activos; el CNN se exportó a `model.onnx` (1,18 MB), el runtime usa ONNX Runtime y PyTorch quedó en `requirements-dev.txt`. La paridad medida fue `<3e-14` por ventana y el proceso ONNX ocupó 91,9 MB RSS tras cargar el modelo.
- **F1 implementada en repositorio**: `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.web`, `docker-compose.yml`, Nginx con rate limit/cabeceras/caché, `.env.example` y `railway.toml`. **Pendiente externo**: ejecutar el piloto en el NAS requiere acceso, permisos y conocer su arquitectura/puertos; no puede validarse desde este checkout.
- **F2 implementada**: esquema SQLAlchemy PostgreSQL/SQLite y migración Alembic; ingesta del catálogo oficial (se corrigió además la URL histórica, que carecía de `/data`); páginas Burst Reports y Statistics; endpoints timeline/xmatch; 36 tests, Ruff, ESLint, build y CI. El monolito heredado conserva el pipeline científico, pero seguridad, persistencia, catálogo, tareas y cálculos Tipo II ya están modularizados; mover las ~2.000 líneas restantes sin cambiar comportamiento queda como refactor posterior de bajo valor funcional.
- **F3 implementada**: worker persistente con estados, progreso, reintentos y bloqueo de cola; detección de día; overview de seis paneles con baseline mediano diario y downsample que preserva picos; light curves; focus code; descarga FITS; export FITS procesado; presets; `median_dB`; combine-time; About y mejoras WCAG/responsive.
- **F4 parcialmente implementada**: xmatch ML↔catálogo oficial, transferencia del tipo oficial a detecciones coincidentes y endpoint experimental de band-splitting Tipo II. **No se presenta como completado** el clasificador neuronal multiclase II–V ni el reentrenamiento: requieren un dataset etiquetado, validación científica y nuevos pesos, no solo cambios de software. Tampoco se activan alertas operativas ni el piloto NAS sin autorización externa.

La checklist original se conserva debajo como trazabilidad de la auditoría inicial; este bloque es la fuente de verdad sobre la implementación realizada.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Arquitectura y flujo de datos actuales](#2-arquitectura-y-flujo-de-datos-actuales)
3. [Comparación con la web original](#3-comparación-con-la-web-original-astrodonceluahes)
4. [Comparación con e-Callisto FITS Analyzer v2.7.0](#4-comparación-con-e-callisto-fits-analyzer-v270)
5. [Otros recursos de la carpeta Sahan](#5-otros-recursos-de-la-carpeta-sahan)
6. [Cumplimiento de los objetivos del anteproyecto](#6-cumplimiento-de-los-objetivos-del-anteproyecto)
7. [Problemas encontrados y su impacto](#7-problemas-encontrados-y-su-impacto)
8. [Funciones que faltan por migrar](#8-funciones-que-faltan-por-migrar)
9. [Arquitectura propuesta para procesos pesados e inferencia IA](#9-arquitectura-propuesta-para-procesos-pesados-e-inferencia-ia)
10. [Mejoras de rendimiento, seguridad, mantenibilidad, testing y despliegue](#10-mejoras-transversales)
11. [Roadmap por fases](#11-roadmap-por-fases)
12. [Clasificación: imprescindible / recomendado / futuro](#12-clasificación-de-tareas)
13. [Orden de implementación recomendado y checklist final](#13-orden-de-implementación-y-checklist)
14. [Registro de limpieza de archivos](#14-registro-de-limpieza-de-archivos)
15. [Anexo: tareas heredadas de PROMPT_FABLE5.md](#15-anexo-tareas-heredadas-de-prompt_fable5md)

---

## 1. Resumen ejecutivo

**[HECHO]** El proyecto es un portal web de espectrogramas solares e-CALLISTO con backend FastAPI (`backend/main.py`, ~2030 líneas + `backend/burst_detect.py`, ~626 líneas) y frontend React 19 + Vite 8 + Plotly.js (`frontend/src/App.jsx`, `Spectrogram.jsx`, `StationsMap.jsx`). Funcionalmente está avanzado: lista viva de estaciones desde ETHZ, descarga y caché de FITS, pipeline científico (resta de fondo robusta + RFI v2 con parámetros ajustables), comparación multi-estación en paneles sincronizados u overlay translúcido, zoom de alta resolución, overlay GOES/XRS, regla de deriva, visor de cabeceras FITS, mapa mundial de estaciones con estado operativo/terminador solar, y detección automática de bursts con un modelo CNN+MIL empaquetado (3,5 MB).

**Los cinco hallazgos más importantes:**

1. **[PROBLEMA — crítico] Vulnerabilidad de path traversal / lectura arbitraria de ficheros.** El parámetro `file_path` de `/api/spectrogram` acepta cualquier ruta absoluta del servidor, y el parámetro `filename` se concatena sin sanitizar con `os.path.join` en varios endpoints. Detalle en §7.1.
2. **[HECHO + RECOMENDACIÓN — la clave del problema de Railway]** El modelo pesa solo **3,5 MB**; lo que consume memoria es **PyTorch** (cientos de MB de RSS al importar) más sunpy/pandas. Exportar el modelo a **ONNX** y hacer inferencia con `onnxruntime` (~40–60 MB de RSS) elimina torch por completo y muy probablemente hace viable la inferencia incluso en el plan actual. Es además lo que el anteproyecto ya preveía («el modelo final se exportará en formatos ligeros como TensorFlow Lite u ONNX»). Detalle en §9.
3. **[HECHO] Objetivos del anteproyecto sin cubrir:** no hay base de datos PostgreSQL, no hay clasificación por tipos (II–V; solo burst/no-burst binario), no hay despliegue en el NAS con Docker Compose + Nginx, y no hay tests ni CI. Detalle en §6.
4. **[HECHO] La web original tiene tres funciones de alto valor aún no migradas:** el **catálogo navegable de burst reports** (lista oficial v2 + detección propia deArce v3, con tipo de burst y estaciones), la página de **estadísticas** (ranking diario de estaciones) y el **explorador/descarga del archivo de datos**. Detalle en §3.
5. **[HECHO] Deuda estructural:** `backend/main.py` es un monolito de 2030 líneas sin módulos, no hay compresión gzip de respuestas (payloads de varios MB por espectrograma), y la configuración de despliegue es inconsistente (existe `render.yaml` para Render pero el despliegue real está en Railway, sin fichero de configuración en el repo).

**Estado global:** el portal cumple ya el núcleo funcional del TFG (adquisición + procesado + visualización interactiva) con calidad visiblemente superior a la web original en visualización. Para entregar el TFG con solvencia faltan: cerrar la seguridad, resolver la inferencia IA fuera del servidor web (o aligerarla con ONNX), implementar la base de datos y el catálogo de bursts, preparar el despliegue reproducible orientado a NAS, y un mínimo de tests. Todo ello está desglosado y priorizado en §11–§13.

---

## 2. Arquitectura y flujo de datos actuales

### 2.1 Componentes **[HECHO]**

```text
Navegador (React 19 + Vite 8 + Plotly.js 3.5, JS puro sin TS)
  App.jsx          → estado global, sidebar (estaciones/fecha/ficheros), pestañas de herramientas
  Spectrogram.jsx  → render Plotly (paneles apilados / overlay alfa), zoom hi-res, regla, GOES, cajas ML
  StationsMap.jsx  → mapa mundial (scattergeo), terminador día/noche, subsolar, burst counts
  api.js           → apiFetch con VITE_API_BASE_URL (fallback http://localhost:8000)
        │  HTTP/JSON (sin gzip, sin auth)
        ▼
FastAPI (backend/main.py, monolito)
  /health
  /api/stations          → escaneo del índice HTTP de ETHZ (últimos 7 días) con caché 300 s + fallback estático (76 estaciones)
  /api/stations/geo      → coords (registro aprendido de cabeceras FITS + fallback manual), estado operativo, burst counts mensuales
  /api/files             → merge de caché local + índice ETHZ, hora extraída del nombre
  /api/spectrogram       → pipeline: FITS → ejes → decimación temporal (block-mean) → resta fondo p25 → [RFI v2] → clip p2–p98 → JSON
  /api/spectrogram/combine → N estaciones en ThreadPool(4), sync por bloque de 15 min (máx. 6)
  /api/spectrogram/zoom  → recorte crudo desde LRU cache (8 ficheros) → pipeline sobre el recorte
  /api/goes              → sunpy/Fido → NetCDF caché en data/goes_cache → serie XRS-B del día
  /api/burst/detect      → backend/burst_detect.py: preprocesado propio del modelo → ventanas 128×128 → CNN → MIL → eventos
                           (+ localizador visual de fallback para falsos negativos del modelo)
        │
        ▼
Fuentes: ETHZ soleil.i4ds.ch (FITS + burst lists mensuales) · NOAA vía SunPy · NAS opcional (ECALLISTO_DATA_DIR,
         default /var/services/web/ecallistodata — la ruta del Web Station del Synology de la Casa del Doncel)
Almacenamiento: data/ (caché local de FITS, ~113 MB actualmente, no versionado) · data/station_coords.json ·
         data/goes_cache/ · backend/model/burst_detector/ (bundle ML versionado en git)
```

### 2.2 Observaciones de diseño

- **[HECHO]** La resolución de ficheros sigue el orden local → NAS → descarga ETHZ con caché persistente; es el diseño correcto para el objetivo final (portal corriendo junto al espejo de datos del NAS).
- **[HECHO]** Los trabajos pesados se ejecutan en el mismo proceso web mediante `ThreadPoolExecutor`s dedicados (`_COMBINE_EXECUTOR`, `_BURST_EXECUTOR` de 1 worker, `_GOES_EXECUTOR`, `_COORD_EXECUTOR`). Evita bloquear el event loop, pero **la CPU y la memoria compiten con el servicio de la API** (ver §9).
- **[HECHO]** El estado es todo in-process (cachés en diccionarios con locks). Con un solo worker uvicorn funciona; con varios workers o réplicas cada proceso duplicaría cachés y descargas. No hay base de datos.
- **[HECHO]** No hay ninguna carpeta de tests, ni CI (no hay `.github/workflows`), ni Dockerfile/docker-compose, ni linter Python configurado. El frontend sí tiene ESLint.
- **[HECHO]** `render.yaml` define un servicio web en Render (plan free) con `FRONTEND_ORIGINS=http://localhost:5173`. No hay configuración de Railway en el repo; **[HIPÓTESIS]** el despliegue en Railway se hizo desde la UI. No hay tampoco configuración de despliegue del frontend (ni Vercel/Netlify/estático).

---

## 3. Comparación con la web original (astrodoncel.uah.es)

**[HECHO]** La web original es PHP + jQuery/Bootstrap servida desde el NAS Synology (los quicklooks se sirven de `https://astrodoncel.uah.es/ecallistodata/YYYY/MM/DD/<fichero>.fit_low.png`, la misma jerarquía que el `ECALLISTO_DATA_DIR` por defecto del backend). Páginas: Home (búsqueda), Data, Burst Reports, Xmatch, Statistics, Stations, About.

| Función de la web original | Estado en la nueva web | Veredicto |
|---|---|---|
| **Home — búsqueda estación+fecha → grid de quicklooks PNG** por fichero de 15 min, con filtro por **focus code** (01/02…), rango horario From/To y filtro GOES | Espectrogramas interactivos Plotly por fichero (muy superior en calidad), lista de ficheros agrupada por horas | Migrado y mejorado, **pero faltan**: agrupación/filtro por focus code (hoy `_01` y `_02` aparecen mezclados como ficheros independientes) y una vista rápida "grid del día" |
| **Home — opción "ALL STATIONS"** para una fecha | No existe búsqueda multi-estación por fecha sin seleccionar estaciones | Pendiente (valor medio; el catálogo de bursts de §8.2 lo cubre en gran parte) |
| **Home — "Spectral overview"** (espectro del día completo) | No existe | **Pendiente — alto valor** (además Sahan lo implementa: §4) |
| **Home — "Light curves"** | No existe | **Pendiente — alto valor** (Sahan lo implementa) |
| **Home — filtro GOES**: genera server-side un PNG con overlay GOES por rango horario (script Python en venv del NAS, `dashboard/venvs/goesplot/bin/goes.php`) | Overlay GOES interactivo sobre el espectrograma (superior) | Migrado y mejorado |
| **Data** — explorador del archivo espejo 1999–2026 con descarga de FITS | No hay forma de descargar el FITS crudo desde la UI (el backend lo descarga y cachea, pero no lo expone) | **Pendiente**: al menos un botón "Download FITS" del fichero cargado |
| **Burst Reports** — catálogo filtrable por fuente (**Official e-Callisto v2** / **deArce detection v3**), año/mes/día, orden por fecha o geolongitud; columnas: fecha, intervalo, **tipo (II, III, IIIG, IIIGG, V, U, J, CTM, RBR + intensidad /1-3)**, estaciones, longitudes min/mid/max | Solo existe el conteo mensual de bursts por estación en el mapa (`/api/stations/geo`), que ya parsea las listas mensuales de ETHZ (`_burst_counts_for_month`, main.py:1221) | **NO migrado — la mayor carencia funcional** frente a la web original. Además la nueva web puede superarla: clic en una fila → abrir el espectrograma de esa estación/hora |
| **Xmatch** — búsqueda por fecha (presumiblemente cruce burst↔flare GOES) | No existe | **[HECHO]** la página original no devolvió resultados en las pruebas (formulario responde vacío). **[HIPÓTESIS]** rota o sin datos. Oportunidad de implementarla bien en la nueva web (cruce automático detecciones ML ↔ eventos GOES) |
| **Statistics** — imagen diaria de ranking de estaciones (`img/ranking_YYYYMMDD.png`) | No existe | **Pendiente**: página de estadísticas generada de las burst lists (ya parseadas en el backend) |
| **Stations** — mapa estático verde/rojo | Mapa interactivo con terminador, punto subsolar, coords reales aprendidas de FITS, burst counts | Migrado y claramente mejorado |
| **About** | No existe | Pendiente trivial (una página con créditos/proyectos SBPLY, útil para la memoria) |
| Lista de estaciones del desplegable original incluye p. ej. SPAIN-ALCALA, SPAIN-SDR, Arecibo-observatory, KRIM, INDIA-Nashik, THAILAND-Pathumthani, SOUTHAFRICA-SANSA, MRT3, NZ-WAIRAKEI, POLAND-Grotniki | La lista viva de ETHZ las recoge cuando reportan; el fallback estático (76 nombres, main.py:61) no las contiene | Menor: revisar el fallback estático con la lista del portal original |

---

## 4. Comparación con e-Callisto FITS Analyzer v2.7.0

**[HECHO]** `Sahan/e-Callisto_FITS_Analyzer-master` es una aplicación de escritorio PySide6 (v2.7.0). Su backend (`src/Backend/*.py`) es la referencia científica del proyecto. Clasificación de sus capacidades respecto a nuestra web:

### 4.1 Ya portado (verificado en `backend/main.py` / frontend)

- Lectura FITS robusta con fallbacks de ejes (`_load_callisto_data`, port de `fits_io.py`).
- Resta de fondo robusta por canal (percentil 25) (`_subtract_background`, port de `noise_reduction.py`).
- RFI v2 con ocupación + componentes conexas + inpainting por mediana de canal (port del pipeline **superior** de `Burst_No_Burst/src/preprocess/rfi.py`, no del RFI antiguo del Analyzer) con parámetros ajustables desde la UI.
- Comparación multi-estación en paneles apilados sincronizados (equivalente web de `multi_station_comparison.py`).
- Overlay GOES XRS-B con selección de satélite por época (`goes_overlay.py`).
- Regla de deriva de dos clics: Δt, Δf, MHz/s (`measurements.calculate_two_point_measurement`).
- Visor de cabeceras FITS; set de colormaps científicos equivalente; contraste manual Zmin/Zmax.

### 4.2 Migrable a la web (adaptación directa, ordenado por valor científico/esfuerzo)

| # | Función | Módulo de referencia | Notas de adaptación web |
|---|---|---|---|
| M1 | **Light curves** (intensidad vs tiempo a frecuencia(s) elegidas, clic o input, multi-curva) | Analyzer (Analysis → Plot Light Curves) | Nuevo endpoint `GET /api/lightcurve?station&date&filename&freq_mhz` (extraer fila(s) del FITS ya cacheado) + trazas scatter sobre el espectrograma. Esfuerzo bajo, valor alto |
| M2 | **Spectral overview del día completo** (6 paneles de 4 h, baseline mediano de día, downsample preservando picos) | `spectral_overview.py` (`build_spectral_overview`, `_peak_preserving_downsample`) | Es una tarea pesada (descarga ~96 ficheros/día) → debe ir por el worker/cola de §9 con estado de progreso. Cachear el resultado |
| M3 | **Presets de contraste** («Raw FITS Percentile 5–98%», presets guardables) | `presets.py`, README §3 | Frontend + localStorage; trivial |
| M4 | **Export**: PNG de publicación (título/ejes configurables) y FITS procesado | `project_report.py` / File → Export As | Plotly `toImage` para PNG; endpoint `GET /api/spectrogram/export?format=fits` que escriba el array procesado con astropy |
| M5 | **Filtro/agrupación por focus code** | Downloader (focus-code overview tabs) | Parsear el sufijo `_NN` del nombre (ya se extrae la hora en `_time_from_filename`, main.py:526); agrupar la lista de ficheros por código |
| M6 | **Combine Time / Combine Frequency** (unir segmentos consecutivos o bandas) | Analyzer §15; también `ecallistolib.combine` | Útil para ver >15 min seguidos. Time-combine primero (más simple). Pesado → worker |
| M7 | **Maximum intensities + best fit (backbone Tipo II, drift, shock)** | `measurements.py`, `burst_processor.py` | Valor científico alto pero UI compleja (lasso + outliers). Candidato a "futuro" |
| M8 | **Type II band-splitting** (campo magnético, Mach de Alfvén; Newkirk folds) | `type_ii_band_splitting.py` (`calculate_type_ii_parameters`, `calculate_b_vs_r_profile`) | El propio Sahan lo marca como experimental. Futuro |
| M9 | **Overlays de contexto adicionales: GOES SEP protones, Dst (Kioto), Kp (GFZ)** | `sep_proton.py`, `dst_index.py`, `kp_index.py` | Endpoints análogos a `/api/goes`. Futuro/recomendado |
| M10 | **median_dB** (escala digits→dB `2500/255/25.4`) como modo de unidades | README §31, batch processing | Bajo esfuerzo, mejora la interpretabilidad del colorbar (hoy la etiqueta "dB" del hover no es estrictamente correcta: son dígitos con fondo restado) |

### 4.3 No aplicable a la web del TFG (ejecutar externamente si se necesita)

**[RECOMENDACIÓN]** Todo el workspace de imagen solar multi-misión (SDO/AIA, SOHO/LASCO, STEREO, SUVI, HMI, J-maps, CME height-time), el downloader de Learmonth, los proyectos `.efaproj`/`.ecsolar`, informes PDF de proyecto y el visor Helioviewer quedan fuera del alcance razonable del TFG web; para esos análisis se usa la app de escritorio de Sahan. Documentarlo así en la memoria (decisión de alcance, no carencia).

---

## 5. Otros recursos de la carpeta Sahan

- **`Burst_No_Burst-master`** **[HECHO]**: origen del detector ya portado. Contiene además: CLI de calibración de umbral (`src/cli/calibrate_threshold.py`), minería de hard negatives, entrenamiento multi-seed, y `docs/PARAMETER_REFERENCE.md`. Métricas del bundle desplegado (en `backend/model/burst_detector/deploy_profile.json`): PR-AUC 0.757, ROC-AUC 0.781, F1 0.731 sobre 99 muestras, ~1.02 falsas alarmas/hora. **[RECOMENDACIÓN]** citar estas métricas en la memoria y en la UI (tooltip "fiabilidad del detector"); usar sus CLIs para reentrenar/recalibrar si se amplía el dataset con ficheros de Sigüenza/Peralejos.
- **`ecallistolib-main`** **[HECHO]**: librería MIT con `combine_time()`/`combine_frequency()` optimizados, crop, descarga y CLI. **[RECOMENDACIÓN]** referencia ideal para implementar M6 (combinación temporal/frecuencial) sin reinventar el algoritmo de huecos/solapes; también su `background_subtract_frequency()` (resta de fondo en el eje tiempo) como opción de procesado adicional.
- **[HECHO]** `Sahan/` está correctamente excluido de git (`.gitignore`), como material de referencia.

---

## 6. Cumplimiento de los objetivos del anteproyecto

Fuente: `Anteproyecto/alfonso.munozsevilla_G581_anteproyecto.pdf` (objetivos §2, metodología §3, arquitectura propuesta §5).

| Objetivo/compromiso del anteproyecto | Estado | Evidencia |
|---|---|---|
| Herramientas web para **adquisición, procesado y visualización** de datos e-Callisto en astrodoncel.uah.es | ✅ Núcleo cumplido | Endpoints + UI descritos en §2 |
| Análisis del portal actual y propuestas de diseño | ✅ Parcial → **este documento lo completa** | §3 |
| Python 3.12 + FastAPI + Astropy + NumPy/SciPy | ✅ Cumplido | `requirements.txt`, `.python-version` |
| React + Vite + Plotly.js (WebGL) | ✅ Cumplido (React 19; heatmap SVG, no `heatmapgl` — ver §7.9) | `frontend/package.json` |
| Tailwind CSS + Zustand | ⚠️ Desviación: CSS artesanal (`App.css`, 1007 líneas) y estado con hooks | Justificable en la memoria (menos dependencias); documentar la desviación |
| **PostgreSQL** (JSONB para cabeceras FITS, consultas temporales de eventos) | ❌ **No implementado** | No hay BD alguna |
| **Clasificación automática de SRBs tipos II–V** (CNN) | ⚠️ Parcial: detección **binaria** burst/no-burst (CNN+MIL) con localización de eventos | `backend/burst_detect.py`; sin clasificación por tipo |
| **Exportación del modelo a TensorFlow Lite u ONNX** para inferencia viable en NAS | ❌ No hecho — **es precisamente la causa del problema de memoria en Railway** | `requirements.txt` fija `torch==2.7.0+cpu` |
| **Despliegue en NAS** (Casa del Doncel) con **Docker Compose + Nginx** (TLS, proxy, caché) | ❌ No hecho (Railway/Render provisional; sin Dockerfile) | §2.2 |
| pyCallisto para resta de fondo/concatenación | ⚠️ Desviación: sustituido por ports de Sahan (RFI y fondo superiores) | Justificable; citarlo |
| Gestión de base de datos como nuevo servicio del portal | ❌ Pendiente (ligado a PostgreSQL) | — |
| Git + GitHub, trunk-based, Conventional Commits | ⚠️ Git+GitHub sí; los mensajes no siguen Conventional Commits de forma consistente | `git log` |
| Pruebas de rendimiento y robustez (T4) | ❌ No hay tests ni benchmarks | — |
| Memoria del TFG documentando diseño y uso de IA (T5) | ⏳ Pendiente (fase natural final) | — |

**Síntesis**: el frente T2/T3 (backend+frontend) está muy avanzado y en varios puntos por encima de lo prometido; los incumplimientos se concentran en **persistencia (PostgreSQL)**, **clasificación por tipos**, **formato ligero de inferencia** y **despliegue NAS contenedorizado** — los cuatro están recogidos como imprescindibles o recomendados en el roadmap (§11).

---

## 7. Problemas encontrados y su impacto

### 7.1 Seguridad — **[PROBLEMA, crítico]** lectura/escritura fuera del directorio de datos

- `GET /api/spectrogram?file_path=...` (main.py:1466 → `_build_spectrogram` main.py:1117) acepta **cualquier ruta absoluta** del servidor y la abre con astropy. Permite sondear la existencia de ficheros arbitrarios y leer cualquier FITS del sistema; los mensajes de error (`Error processing FITS '<ruta>'...`) filtran información.
- `filename` se une con `os.path.join(DATA_DIR_LOCAL, filename)` sin normalizar en `/api/spectrogram` (main.py:1122), `/api/spectrogram/zoom` (main.py:1669) y `/api/burst/detect` (main.py:1821). Un `filename` con `..\..\` escapa de `data/`; en el flujo de descarga (`_download_from_ethz`, main.py:598) además se **escribe** en la ruta resultante.
- **Impacto**: en Railway el contenedor limita el daño; en el **NAS de producción** (objetivo final, con el archivo científico completo en disco) sería grave.
- **Corrección** (F0): eliminar `file_path` del endpoint público (o restringirlo a `ECALLISTO_DATA_DIR`), y validar `filename` con una whitelist (`re.fullmatch(r'[A-Za-z0-9_-]+_\d{8}_\d{6}(_\d{2})?\.fits?(\.gz)?', filename)`) + comprobar `os.path.commonpath` tras resolver.
- Relacionado **[HECHO, riesgo aceptado]**: `torch.load(..., weights_only=False)` en burst_detect.py:277 deserializa pickle del bundle local. Aceptable por ser un artefacto propio versionado; documentarlo y, al migrar a ONNX, desaparece.

### 7.2 Memoria/IA en Railway — **[PROBLEMA, crítico para el despliegue]**

- **[HECHO]** `model.pt` = 3,5 MB; la CNN es compacta (4 bloques conv, base 16). **[HECHO]** `requirements.txt` instala `torch==2.7.0+cpu`. **[HIPÓTESIS fundada]** el OOM en Railway procede de: RSS de torch al primer `import` (~200–400 MB) + sunpy/pandas + picos del pipeline (caché LRU de 8 FITS crudos ≈ 45–90 MB; ventanas + activaciones de inferencia; serialización JSON). Un plan de 512 MB no lo soporta.
- **Corrección**: §9 (ONNX + separación del proceso pesado).

### 7.3 Rendimiento de la API — **[PROBLEMA, alto]**

- **Sin `GZipMiddleware`**: la respuesta de `/api/spectrogram` con `max_time_bins=1500` y ~200 canales son ~300k floats en JSON (varios MB). Gzip la reduciría ~4–8×. Una línea de FastAPI.
- **Serialización lenta**: `z=[[round(float(v), 4) for v in row] for row in data_out.tolist()]` (main.py:1191) itera ~300k+ elementos en Python puro **por petición**. Alternativas: `np.round(data,4).tolist()` (vectorizado) o mejor `orjson`/respuesta binaria (float32 + base64 o arrow) — ganancia estimada de cientos de ms por request.
- **GOES**: cachea los NetCDF pero **repite** parse+DataFrame+filtrado en cada petición del mismo día; cachear el JSON resultante por fecha.
- `/api/files` hace una petición HTTP a ETHZ **sin caché** en cada llamada (y el frontend la dispara en cada cambio de estación/fecha); añadir caché TTL corta como la de estaciones.
- **Frontend**: la navegación con flechas ←/→ (App.jsx:265) dispara una carga completa por cada pulsación, sin debounce ni cancelación (el fetch de capas no usa AbortController, solo el zoom lo hace).

### 7.4 Robustez — **[PROBLEMA, medio]**

- `datetime.now()` local en vez de UTC en el escaneo de estaciones y burst lists (main.py:1299, 1361): en hosting con TZ ≠ UTC puede pedir el mes/día equivocado en los bordes.
- `_scan_recent_ethz_stations` empieza en `days_back=1`: **nunca considera el día de hoy**, aunque ETHZ ya tenga datos → el estado "operative" y la lista pueden ir un día por detrás.
- `apiFetch` sin timeout: un backend colgado deja spinners infinitos.
- El límite de 8 paneles del zoom (`for i in 0..8` en Spectrogram.jsx:308) y `_MAX_COMBINE_STATIONS=6` están descoordinados pero compatibles; documentar.
- Sin manejo de "archivo ETHZ caído" en la UI más allá del mensaje de error crudo del backend.

### 7.5 Arquitectura de código — **[PROBLEMA, medio]**

- `backend/main.py` (2030 líneas) mezcla: catálogo de estaciones, geo, I/O FITS, pipeline científico, cachés, burst lists, GOES y todos los endpoints. Dificulta tests y la memoria del TFG. Reestructurar a paquete (`backend/{stations,fits_io,pipeline,rfi,goes,bursts,api}/`) **sin cambiar lógica**.
- Duplicación del bloque "resolver fichero → slice → procesar → serializar" entre `/api/spectrogram` y `/zoom`.
- El registro de coordenadas y sus locks/executors son ~200 líneas de infraestructura que una tabla de BD haría triviales (enlaza con el objetivo PostgreSQL).

### 7.6 Sin persistencia — **[PROBLEMA, alto respecto al anteproyecto]**

Sin PostgreSQL no hay: catálogo de bursts consultable, histórico de detecciones ML, índice de cabeceras FITS (JSONB), ni consultas temporales de eventos. Es además el soporte natural de la página Burst Reports (§8.2) y de Statistics.

### 7.7 Testing/CI — **[PROBLEMA, alto para un TFG de Ingeniería]**

Cero tests. El pipeline científico es puro y perfectamente testeable (fixtures FITS pequeños ya hay 398 en `data/`, aunque no versionados). Sin CI no hay red de seguridad para refactorizar.

### 7.8 Despliegue — **[PROBLEMA, medio]**

- `render.yaml` (Render) vs despliegue real en Railway **[HECHO/declarado]**: configuración contradictoria; el `FRONTEND_ORIGINS` del yaml apunta a localhost (CORS roto en producción si se usara).
- No hay Dockerfile ni compose pese a ser compromiso del anteproyecto y necesidad del NAS.
- No está definido dónde/cómo se sirve el frontend en producción.

### 7.9 UX/varios — **[PROBLEMA, bajo]**

- Sin favicon/branding "AstroDoncel" (la marca de la UI es "e-CALLISTO Spain"; alinear con el nombre del portal real).
- El heatmap usa SVG `heatmap`; con 1500×200 va bien, pero el anteproyecto preveía WebGL. Nota: `heatmapgl` fue retirado en Plotly.js 3.x **[HECHO]**, así que documentar la decisión (o evaluar `plotly.js` con `image` trace para patches grandes).
- Textos 100 % en inglés; decidir política de idioma (portal UAH → posiblemente bilingüe) — decisión de producto, no defecto.
- Etiqueta "dB" del hover cuando la escala son dígitos con fondo restado (ver M10).
- Accesibilidad básica: controles sin `aria-label`, contraste de textos secundarios bajo.

---

## 8. Funciones que faltan por migrar

Consolidación de §3 + §4 (detalle de prioridad/criterios en §11):

1. **Catálogo Burst Reports** (web original) — página con filtros fuente/fecha/tipo/estación + enlace directo "abrir espectrograma". Fuente de datos: burst lists mensuales de ETHZ (parser ya existente `_burst_counts_for_month` a generalizar) + (fase 2) detecciones deArce v3 si los tutores dan acceso al feed del NAS.
2. **Spectral overview de día completo** (web original + Sahan M2).
3. **Light curves** (web original + Sahan M1).
4. **Estadísticas** (web original) — ranking de estaciones por detecciones (día/mes), derivable de las mismas burst lists.
5. **Descarga del FITS crudo** y export PNG/FITS procesado (web original "Data" + Sahan M4).
6. **Filtro por focus code** (web original + Sahan M5).
7. **Presets de contraste** (Sahan M3) y **median_dB** (M10).
8. **Combine time/frequency** (Sahan M6, con `ecallistolib` como referencia).
9. **Xmatch burst↔GOES** (web original, ahí aparentemente rota — oportunidad de superar al original).
10. Avanzado/futuro: maximum intensities + shock fit (M7), band-splitting (M8), SEP/Dst/Kp (M9).

---

## 9. Arquitectura propuesta para procesos pesados e inferencia IA

### 9.1 Principio

**[RECOMENDACIÓN]** Nada pesado en el navegador; el servidor web (API) solo orquesta. Tres niveles de carga:

- **Ligero (síncrono en la API)**: espectrograma individual, zoom, light curve de un fichero cacheado. Latencia < 2 s.
- **Pesado (asíncrono, worker)**: inferencia ML por lotes, spectral overview de día completo (~96 descargas), combine, prefetch, xmatch. Patrón *task queue* con estados.
- **Contexto externo (asíncrono con caché fuerte)**: GOES/SEP/Dst/Kp.

### 9.2 Paso 0 — la optimización que cambia el problema: **ONNX**

**[RECOMENDACIÓN, máxima prioridad técnica]**
1. Exportar `WindowCNN` a ONNX una única vez en local (`torch.onnx.export` con eje dinámico en batch). El head MIL (noisy-or sobre sigmoides) son ~5 líneas de numpy — no necesita ni estar en el grafo.
2. Sustituir en producción `torch` por `onnxruntime` (CPU). Efectos: imagen de despliegue cientos de MB más pequeña, RSS de inferencia estimado < 100 MB total, arranque más rápido, y cumplimiento literal del anteproyecto.
3. Guardar el `.onnx` junto al bundle con su sha256 en `deploy_profile.json`; mantener `model.pt` como fuente para reentrenos.
4. Validación: comparar `file_score` torch vs onnx sobre 10–20 FITS de `data/` (tolerancia < 1e-4) y conservar el informe como evidencia para la memoria.
5. Opcional: cuantización dinámica int8 de onnxruntime (modelo ya minúsculo; solo si hiciera falta en el NAS).

Con esto, **[HIPÓTESIS a validar]** la inferencia probablemente vuelve a caber en Railway; aun así, mantener la separación web/worker por diseño (abajo).

### 9.3 Comparativa de opciones de despliegue del cómputo

| Opción | Pros | Contras | Veredicto |
|---|---|---|---|
| **A. NAS (Casa del Doncel)** — destino del anteproyecto | Los datos ya viven ahí (cero transferencia); sin coste; Synology soporta Docker (Container Manager); alineado con tutores y T4 | Requiere acceso/coordinación; CPU modesta (suficiente con ONNX); exposición a internet ya resuelta (astrodoncel.uah.es) | **Objetivo final del TFG** — todo el trabajo de contenedores (F1) apunta aquí |
| B. PC propio temporal (túnel cloudflared/Tailscale) | Cero coste, GPU/CPU sobrada, inmediato | No producción: disponibilidad, IP doméstica, seguridad | Solo para demos/desarrollo mientras llega el acceso al NAS |
| **C. Servicio de inferencia independiente con API** | Aísla memoria/CPU del portal; escalable; el portal sobrevive si el worker cae (degradación elegante, ya implementada con `available:false`) | Un despliegue más que mantener | **Patrón recomendado** — independiente de dónde corra (NAS, VPS o el propio Railway como 2.º servicio) |
| D. Otro proveedor (VPS Hetzner/OVH ~4–6 €/mes, 2–4 GB; Fly.io; Render Starter) | Resuelve por fuerza bruta la RAM; control total | Coste; no alineado con el NAS del anteproyecto | Plan B si el NAS se retrasa |
| **E. Optimizar el modelo (ONNX)** | Ataca la causa raíz; beneficia a *todas* las opciones anteriores; compromiso explícito del anteproyecto | Ninguno relevante (modelo pequeño, export directo) | **Hacer siempre, primero** |

**Recomendación combinada: E → C → A.** (ONNX ya; estructurar la inferencia como servicio/worker separado; desplegar el conjunto en el NAS con Docker Compose.)

### 9.4 Diseño del servicio de tareas (dimensionado a TFG)

**[RECOMENDACIÓN]** Dos niveles, elegir según tiempo disponible:

**Nivel 1 — pragmático (suficiente para el TFG):** un segundo proceso `worker` en el mismo compose, cola en **SQLite/PostgreSQL** (tabla `tasks`: id, type, params_json, status `queued|running|done|failed`, progress, result_json, error, created/started/finished, requester_ip). API: `POST /api/tasks` (crea y devuelve id; idempotencia por hash de params), `GET /api/tasks/{id}` (polling del frontend cada 2 s). El worker es un bucle `SELECT ... WHERE status='queued' ORDER BY created LIMIT 1` con `FOR UPDATE SKIP LOCKED` (PG). Sin dependencias nuevas.

**Nivel 2 — estándar industrial (si sobra tiempo / para la memoria):** Redis + **arq** o RQ (más ligeros que Celery), mismos contratos de API.

Transversal a ambos:
- **Caché de resultados**: clave = (tipo, estación, fecha, params); TTL largo para datos históricos (inmutables), corto para el día en curso. Los overviews renderizados se materializan a disco (PNG/JSON) como hace la web original con sus quicklooks.
- **Límites**: máx. N tareas encoladas por IP, tamaño máximo de fecha-rango, `_MAX_COMBINE_STATIONS` ya existente.
- **Reintentos**: 2 reintentos con backoff exponencial solo para fallos de red (descarga ETHZ/NOAA); nunca para errores de datos.
- **Timeouts** por tipo de tarea (p. ej. detect: 120 s; overview: 15 min).
- **Seguridad**: worker sin puertos expuestos; API pública solo lectura + creación de tareas limitada; validación estricta de params (Pydantic ya presente).
- **Observabilidad**: logging estructurado (JSON) con task_id; contador de tareas por estado en `/health` ampliado; opcional `prometheus-fastapi-instrumentator`.

### 9.5 Arquitectura objetivo (NAS)

```text
                    Internet
                       │
              Nginx (contenedor) ── TLS, caché estáticos, rate limit básico
               │                │
   frontend (build estático)   /api → uvicorn FastAPI  ── API "ligera" (sin torch)
                                        │        │
                                 PostgreSQL   tabla tasks / catálogo bursts /
                                 (contenedor)  cabeceras FITS JSONB / coords estaciones
                                        │
                                 worker (contenedor, onnxruntime + astropy + sunpy)
                                        │
                          /volume1/web/ecallistodata (bind mount, solo lectura para API,
                          lectura/escritura de caché para worker)
```

Docker Compose único (`docker-compose.yml` + `docker-compose.dev.yml`), idéntico en local y NAS — exactamente lo comprometido en el anteproyecto §5.4.

---

## 10. Mejoras transversales

### Rendimiento
1. `GZipMiddleware` (1 línea) — F0.
2. Serialización vectorizada/orjson — F0.
3. Caché TTL para `/api/files` y para el JSON de GOES por fecha — F2.
4. Debounce/cancelación en la navegación por teclado y AbortController en el fetch de capas — F2.
5. Materializar quicklooks/overviews a disco (patrón de la web original) — F3.

### Seguridad
6. Corregir path traversal + retirar `file_path` público (§7.1) — **F0, bloqueante**.
7. Whitelist regex de `filename` y `station` (se interpolan en URLs/regex hacia ETHZ) — F0.
8. Nginx: rate limiting, tamaño máximo de request, cabeceras de seguridad — F1.
9. Revisión CORS producción (dominios reales; evitar `*` con credenciales) — F1.
10. Mensajes de error sin rutas internas (handler global que registre el detalle y devuelva genérico) — F1.

### Mantenibilidad
11. Trocear `backend/main.py` en paquete modular sin cambiar lógica — F2.
12. Ruff + formateo, pre-commit; tipado gradual (el código ya usa anotaciones) — F2.
13. `CLAUDE.md`/`CONTRIBUTING.md` con comandos de desarrollo — F2.
14. Unificar la doble fuente de coordenadas (registro + `_STATIONS_GEO`) en BD — F2/F3.

### Testing
15. pytest con fixtures FITS pequeños versionados (2–3 ficheros recortados, no los 113 MB de `data/`): ejes (`_load_callisto_data` con variantes de cabecera), RFI (canal sintético contaminado → enmascarado), decimación, `_time_from_filename`, parser de burst lists, path-traversal rechazado — F2.
16. Test de contrato de API con `TestClient` (golden JSON pequeño) — F2.
17. Test de paridad torch↔ONNX (§9.2.4) — F0/F2.
18. GitHub Actions: lint + tests backend, `npm run build` + eslint frontend — F2.

### Despliegue
19. Dockerfiles (api, worker) + compose + Nginx; eliminar la ambigüedad Render/Railway dejando **una** ruta documentada (compose para NAS + guía Railway provisional) — F1.
20. Servir el frontend como estático desde Nginx (o `StaticFiles` de FastAPI en el interín) — F1.
21. Variables de entorno documentadas en `.env.example` — F1.
22. Backup/limpieza de `data/`: política de retención de caché (p. ej. LRU por tamaño máximo configurable) — F3.

---

## 11. Roadmap por fases

Formato de cada tarea: **Objetivo · Justificación · Prioridad · Dificultad · Dependencias · Archivos · Riesgos · Criterios de aceptación (CA) · Validación**.

---

### FASE 0 — Correcciones críticas (1 semana) — *imprescindible*

**T0.1 Cerrar path traversal y `file_path`**
- Objetivo: ningún parámetro de la API permite salir de `data/`/`ECALLISTO_DATA_DIR`.
- Justificación: §7.1; bloqueante para desplegar en el NAS.
- Prioridad: crítica · Dificultad: baja · Dependencias: ninguna.
- Archivos: `backend/main.py` (endpoints `/api/spectrogram`, `/zoom`, `/burst/detect`, `_download_from_ethz`, `_build_spectrogram`).
- Riesgos: romper el flujo legítimo de `filename` con sufijos raros → cubrir con tests de la whitelist contra los 398 nombres reales de `data/`.
- CA: peticiones con `file_path` → 422/410; `filename=../x` → 422; los nombres reales existentes siguen funcionando.
- Validación: tests unitarios + prueba manual con curl.

**T0.2 GZip + serialización vectorizada**
- Objetivo: respuesta de espectrograma < 1 MB comprimida y < 300 ms de serialización.
- Prioridad: alta · Dificultad: baja · Dependencias: ninguna.
- Archivos: `backend/main.py` (middleware app:33; `_build_spectrogram` main.py:1185-1197 y zoom main.py:1754-1773).
- Riesgos: `orjson` cambia formato de floats → mantener `round`/`np.round` a 4 decimales.
- CA: cabecera `content-encoding: gzip` presente; el frontend renderiza idéntico.
- Validación: comparación byte-size antes/después; test de contrato.

**T0.3 Exportar el detector a ONNX y retirar torch del runtime**
- Objetivo: inferencia con `onnxruntime`, `torch` fuera de `requirements.txt` (queda como dependencia de desarrollo/entrenamiento).
- Justificación: §7.2 y §9.2; desbloquea Railway y el NAS; compromiso del anteproyecto.
- Prioridad: crítica · Dificultad: media · Dependencias: ninguna.
- Archivos: nuevo `backend/model/burst_detector/model.onnx`; `backend/burst_detect.py` (sustituir `_load_bundle`/`_score_windows`; MIL noisy-or en numpy); `requirements.txt`; script one-shot `tools/export_onnx.py`.
- Riesgos: divergencia numérica (BatchNorm) → test de paridad (§9.2.4); pooling "attention" no usado por el bundle actual (usa noisy_or **[HECHO]** default) pero contemplarlo.
- CA: `/api/burst/detect` devuelve mismos scores ±1e-4 en el set de validación local; RSS del proceso tras 5 inferencias < 400 MB.
- Validación: script de paridad + medición de memoria (`psutil`) antes/después, guardada para la memoria del TFG.

**T0.4 Decidir y sanear la config de despliegue provisional**
- Objetivo: una única ruta de despliegue documentada y coherente (Railway con variables correctas, o Render — no ambas a medias).
- Prioridad: alta · Dificultad: baja · Dependencias: T0.3 (la nueva imagen ya sin torch).
- Archivos: `render.yaml` (borrar o corregir), README §despliegue, `FRONTEND_ORIGINS` de producción.
- CA: el portal desplegado funciona end-to-end incluida la detección ML.
- Validación: smoke test en la URL pública.

---

### FASE 1 — Despliegue reproducible orientado a NAS (1–2 semanas) — *imprescindible*

**T1.1 Dockerfiles + docker-compose (api, worker, nginx, [postgres])**
- Objetivo: `docker compose up` levanta el sistema completo en local, idéntico al NAS (§9.5).
- Prioridad: alta · Dificultad: media · Dependencias: T0.3.
- Archivos: nuevos `Dockerfile.api`, `Dockerfile.worker`, `docker-compose.yml`, `nginx/nginx.conf`, `.env.example`.
- Riesgos: arquitectura del NAS (x86 vs ARM del Synology) — verificar modelo antes de fijar imágenes base; **[HIPÓTESIS]** es x86 (Web Station + venvs Python actuales).
- CA: build < 10 min; imagen api < 1 GB (sin torch debería quedar ~400–600 MB por astropy/scipy/sunpy).
- Validación: compose local + checklist de humo (los 9 endpoints).

**T1.2 Servir frontend en producción + Nginx con TLS/caché/limits**
- Prioridad: alta · Dificultad: baja-media · Dependencias: T1.1.
- Archivos: `nginx/nginx.conf`, `frontend/vite.config.js` (base path si procede), `frontend/src/api.js`.
- CA: portal accesible en un solo origen (sin CORS en producción); assets con cache-control.
- Validación: Lighthouse básico + prueba de recarga.

**T1.3 Despliegue piloto en el NAS**
- Objetivo: el compose corriendo en la Casa del Doncel con `ECALLISTO_DATA_DIR` sobre el archivo real (T4 del anteproyecto).
- Prioridad: alta · Dificultad: media (coordinación con tutores) · Dependencias: T1.1, T1.2, acceso al NAS.
- Riesgos: permisos del share, puertos ocupados por el portal PHP actual → desplegar bajo subruta/subdominio de pruebas sin tocar el portal viejo.
- CA: espectrograma de SPAIN-SIGUENZA servido leyendo directamente del disco del NAS (sin descarga de ETHZ).
- Validación: sesión de pruebas con tutores; medición de latencias.

---

### FASE 2 — Persistencia, catálogo y calidad (2–3 semanas) — *imprescindible*

**T2.1 PostgreSQL + modelo de datos**
- Objetivo: BD con tablas `stations` (nombre, lat/lon, fuente coord), `fits_files` (estación, fecha, hora, focus code, ruta/origen, header JSONB), `burst_events` (fuente v2/v3/ML, fecha, t0/t1, tipo, intensidad, estaciones[], score), `tasks` (§9.4), `goes_days` (JSON cacheado).
- Justificación: objetivo explícito del anteproyecto; soporte de T2.2–T2.4; sustituye `station_coords.json` y cachés ad hoc.
- Prioridad: alta · Dificultad: media · Dependencias: T1.1 (contenedor PG).
- Archivos: nuevos `backend/db.py`, migraciones (alembic o SQL simple); refactor de `_COORD_REGISTRY*`, `_BURST_CACHE`.
- Riesgos: sobredimensionar el ORM → usar SQLAlchemy Core o asyncpg directo, esquema mínimo.
- CA: arranque sin BD sigue funcionando en modo degradado (los endpoints actuales no dependen de ella); con BD, coords y burst counts persisten entre reinicios.
- Validación: tests de integración con PG en CI (servicio en Actions).

**T2.2 Ingesta de burst lists + página "Burst Reports"**
- Objetivo: paridad con la web original y superarla: tabla filtrable (fuente, fecha, tipo, estación) + clic → abre el espectrograma de esa estación/intervalo en el portal.
- Prioridad: alta · Dificultad: media · Dependencias: T2.1.
- Archivos: worker de ingesta (generalizar `_burst_counts_for_month` main.py:1221 para guardar eventos completos, no solo counts); nuevo endpoint `/api/bursts?from&to&type&station&source`; nuevo componente `BurstCatalog.jsx` + vista en `App.jsx`.
- Riesgos: formato de las listas de ETHZ varía por épocas → parser tolerante + tests con muestras reales de varios años.
- CA: para 2026-07-09 la tabla reproduce las filas visibles hoy en la web original (§3), y el clic carga el espectrograma correcto.
- Validación: comparación manual contra la web original en 3 fechas; tests del parser.

**T2.3 Página "Statistics"**
- Objetivo: ranking de estaciones (día/mes) y serie temporal de nº de bursts, calculados de `burst_events`.
- Prioridad: media · Dificultad: baja · Dependencias: T2.2.
- Archivos: endpoint `/api/stats/...`; componente nuevo; enlaces desde el mapa.
- CA: cifras coherentes con los burst counts que ya muestra el mapa.
- Validación: cruce con `ranking_YYYYMMDD.png` de la web original para una fecha.

**T2.4 Refactor modular del backend + tests + CI**
- Objetivo: `backend/` como paquete (api/, core/, services/); pytest (≥ 20 tests de los puntos §10.15-16); GitHub Actions.
- Prioridad: alta (calidad TFG) · Dificultad: media · Dependencias: mejor tras T2.1 para no refactorizar dos veces.
- Riesgos: regresiones → hacerlo con los tests de contrato ya en verde antes de mover código.
- CA: CI verde; cobertura del pipeline científico > 70 %; `main.py` < 300 líneas (solo wiring).
- Validación: CI + smoke manual.

**T2.5 Robustez menor**: UTC en vez de hora local, incluir "hoy" en el escaneo ETHZ, timeout+AbortController en `apiFetch`, caché TTL en `/api/files`, debounce en navegación por teclado.
- Prioridad: media · Dificultad: baja · Archivos: main.py:1299/1361, api.js, App.jsx:264.
- CA: lista de estaciones refleja datos del mismo día cuando existen.

---

### FASE 3 — Funciones científicas pendientes (2–3 semanas) — *recomendado (elegir según tiempo)*

**T3.1 Servicio de tareas (nivel 1 de §9.4) + worker**
- Prioridad: alta dentro de F3 (habilita T3.2/T3.5) · Dificultad: media · Dependencias: T2.1.
- CA: `POST /api/tasks {type:"burst_detect_day", station, date}` recorre el día y persiste eventos ML en `burst_events`; frontend muestra progreso.
- Validación: día completo de ALASKA-COHOE procesado sin degradar la latencia de la API (medir p95 durante la tarea).

**T3.2 Spectral overview del día completo** (M2; port de `spectral_overview.py`: 6 paneles × 4 h, baseline mediano de día, downsample preservando picos) — vía tarea + caché materializada.
- CA: overview de SPAIN-SIGUENZA 2026-07-09 visualmente comparable al de la web original/Analyzer; segunda petición < 1 s (caché).

**T3.3 Light curves** (M1): endpoint + trazas superpuestas, clic en el espectrograma para elegir frecuencia.
- CA: curva a 45 MHz de un burst conocido muestra el pico en el instante del evento.

**T3.4 Focus code + descarga FITS + export PNG/FITS + presets de contraste** (M3/M4/M5, web original "Data").
- CA: lista agrupada por focus code; botón descarga el `.fit.gz` exacto; export FITS reabre en el Analyzer de Sahan sin errores.

**T3.5 Combine time** (M6, referencia `ecallistolib.combine`): ver 1–4 h seguidas de una estación — vía tarea.
- CA: dos bloques consecutivos de 15 min se muestran continuos sin costura visible.

**T3.6 UI**: página About/créditos, branding AstroDoncel, i18n si se decide, accesibilidad básica, median_dB (M10).

---

### FASE 4 — Evoluciones futuras (post-entrega o si sobra tiempo)

- **T4.1 Clasificación por tipos II–V**: extender el detector (cabeza multiclase sobre los embeddings de `WindowCNN`, o clasificador ligero sobre eventos usando drift medido + morfología). Dataset: cruzar eventos ML con los tipos de las burst lists (T2.2 lo deja etiquetado "gratis"). Cierra el objetivo más ambicioso del anteproyecto.
- **T4.2 Xmatch automático** detecciones ↔ flares GOES (la página rota del portal original, hecha bien).
- **T4.3 SEP/Dst/Kp** (M9), **band-splitting** (M8), **maximum intensities + shock fit** (M7).
- **T4.4 Reentrenar/recalibrar el modelo** con datos de Sigüenza/Peralejos usando los CLIs de Burst_No_Burst; umbral por estación.
- **T4.5 Modo "monitor"**: tarea programada que procesa el último bloque de las estaciones españolas y publica alertas (candidato a demo estrella).
- **T4.6 WebGL/`image` trace o tiles para zoom profundo; PWA/offline básico.**

---

## 12. Clasificación de tareas

**Imprescindible para entregar el TFG** (sin esto la entrega cojea en seguridad, objetivos del anteproyecto o calidad mínima de ingeniería):
- F0 completa (T0.1–T0.4)
- T1.1, T1.2 (contenedores + frontend servido) — T1.3 depende de terceros: si el acceso al NAS no llega, documentar el plan y demostrar el compose en local/VPS
- T2.1, T2.2, T2.4 (BD, catálogo de bursts, tests+CI+refactor)
- Memoria del TFG (T5 del anteproyecto; este documento es insumo directo)

**Recomendado** (diferencia un TFG correcto de uno notable):
- T2.3, T2.5, T3.1, T3.2, T3.3, T3.4

**Futuro / opcional**:
- T3.5, T3.6 parcial, toda la F4

---

## 13. Orden de implementación y checklist

Orden recomendado (las dependencias ya están encadenadas así):

```text
T0.1 → T0.2 → T0.3 → T0.4          (semana 1)
T1.1 → T1.2 → [T1.3 cuando haya acceso NAS]   (semanas 2-3)
T2.1 → T2.2 → T2.4 → T2.3 → T2.5   (semanas 3-5)
T3.1 → T3.2 → T3.3 → T3.4 → (T3.5, T3.6)      (semanas 6-8)
F4 tras la entrega
```

### Checklist final

**Fase 0**
- [ ] `file_path` retirado/restringido y `filename` validado con whitelist (T0.1)
- [ ] Tests que prueban el rechazo de rutas maliciosas (T0.1)
- [ ] GZipMiddleware activo y serialización vectorizada (T0.2)
- [ ] `model.onnx` exportado, paridad torch↔onnx documentada, torch fuera de requirements (T0.3)
- [ ] Medición RSS antes/después guardada para la memoria (T0.3)
- [ ] Una sola configuración de despliegue provisional coherente; `render.yaml` corregido o eliminado (T0.4)

**Fase 1**
- [ ] `docker compose up` funcional en local (api + worker + nginx [+ pg]) (T1.1)
- [ ] Frontend servido en producción desde el mismo origen (T1.2)
- [ ] `.env.example` y README de despliegue (T1.1/T1.2)
- [ ] Piloto en NAS o, en su defecto, demo en VPS + plan NAS documentado (T1.3)

**Fase 2**
- [ ] Esquema PG creado; coords y burst counts persistentes (T2.1)
- [ ] Página Burst Reports con filtros y clic→espectrograma (T2.2)
- [ ] Página Statistics (T2.3)
- [ ] Backend modular, ≥20 tests, CI verde (T2.4)
- [ ] UTC, escaneo de hoy, timeouts, debounce (T2.5)

**Fase 3**
- [ ] Cola de tareas con estados y límites (T3.1)
- [ ] Spectral overview de día completo cacheado (T3.2)
- [ ] Light curves (T3.3)
- [ ] Focus code + descarga/exports + presets (T3.4)

**Memoria**
- [ ] Desviaciones documentadas: Tailwind/Zustand→CSS/hooks, pyCallisto→ports de Sahan, heatmapgl retirado en Plotly 3, binario vs multiclase (con T4.1 como línea futura)
- [ ] Métricas del modelo (PR-AUC 0.757, F1 0.731) y análisis del fallback visual citados
- [ ] Comparativas antes/después (memoria RSS, tamaño de respuesta, latencias) como resultados experimentales

---

## 14. Registro de limpieza de archivos

Criterio aplicado: solo se han eliminado archivos **inequívocamente** obsoletos, verificando antes que no están referenciados.

**Eliminados en esta auditoría:**

| Archivo | Motivo | Verificación |
|---|---|---|
| `frontend/src/assets/react.svg` | Logo de la plantilla por defecto de Vite; residuo del scaffolding | `grep` sobre todo `frontend/` (excl. node_modules): 0 referencias |
| `frontend/src/assets/vite.svg` | Ídem | Ídem |
| `PROMPT_FABLE5.md` | Documento de trabajo ya ejecutado en su mayoría; **toda la información aún vigente está incorporada en este documento** (ver §15) | Diff de contenido §15 |

**Propuestas de limpieza (NO ejecutadas — decisión del autor):**

- `frontend/src/assets/hero.png` **[HECHO: sin referencias en el código]** — podría estar reservado para la memoria o una futura portada; borrar solo si se confirma que no se usará.
- `frontend/dist/` — artefacto de build local (4,7 MB, ya ignorado por git); regenerable con `npm run build`.
- `render.yaml` — mantener solo si se decide Render como despliegue provisional; si se sigue en Railway, eliminarlo en T0.4 para evitar la ambigüedad documentada en §7.8.
- `data/` (113 MB, 398 FITS) — caché de ejecución no versionada; aplicar la política de retención de §10.22 en lugar de borrado manual.
- `Anteproyecto/Herramientas_Anteproyecto.docx` y `AnteproyectoCallistoNAS_v0_*.{docx,pdf}` — borradores del anteproyecto ya superados por `alfonso.munozsevilla_G581_anteproyecto.pdf`; valor histórico para la memoria → se recomienda conservar.

---

## 15. Anexo: tareas heredadas de PROMPT_FABLE5.md

`PROMPT_FABLE5.md` (eliminado, ver §14) definía las tandas A (bugs), B (UI) y C (features). Estado verificado en el código actual:

**Completado (no requiere acción):**
- A1 RFI v2 por ocupación + componentes conexas + inpainting, con stats en la UI ✅ (main.py:863-995; pestaña Processing)
- A2 Dos modos de comparación (paneles sincronizados por defecto + overlay con colorscale alfa) y selector ✅ (Spectrogram.jsx:459-569)
- A3 Zoom robusto: binding manual de eventos plotly (bug de react-plotly documentado en Spectrogram.jsx:358), AbortController, dedup por vista acumulada, contraste conservado con toggle "auto-contrast on zoom", indicador hi-res y botón Overview, zoom multi-panel ✅
- A4 Sin estación preseleccionada; estado vacío elegante ✅ (App.jsx:29)
- B1 Pestañas superiores (Processing/Display/Solar context/Layers/Tools) ✅
- B2 Búsqueda de estaciones, horas colapsables, ★ cacheados, tooltip nombre completo, navegación ←/→, selector de estación primaria, contador de ficheros ✅
- C1 Detección ML con endpoint `/api/burst/detect` + resaltado en la UI ✅ (+ fallback visual añadido después)
- C2 Regla de deriva ✅ · C3 Parámetros RFI ajustables ✅ · C8 parcial: visor de cabecera FITS ✅

**Pendiente — reubicado en este roadmap:**
- C4 Light curves → **T3.3**
- C5 Overview de día completo → **T3.2**
- C6 Band-splitting Tipo II → **T4.3**
- C7 Overlays SEP/Dst/Kp → **T4.3**
- C8 resto: export PNG de publicación + FITS procesado → **T3.4**
- C9 Presets de contraste ("Raw FITS Percentile 5–98%", guardables) → **T3.4**

**Restricciones del prompt que siguen vigentes como normas del proyecto:**
- No editar nada dentro de `Sahan/` (material de referencia; solo portar).
- El backend debe arrancar aunque falten dependencias pesadas (imports perezosos, degradación elegante) — patrón ya seguido por `/api/goes` y `/api/burst/detect`; mantenerlo en todo lo nuevo (onnxruntime incluido).
- Añadir dependencias nuevas a `requirements.txt` y documentar cada función nueva en el README.
