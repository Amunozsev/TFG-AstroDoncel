# Prompt para Claude Fable 5 — Mejoras del portal AstroDoncel (TFG e-CALLISTO)

Eres un ingeniero senior full-stack (Python/FastAPI + React/Plotly) trabajando en mi TFG:
un portal web de espectrogramas de radio solar de la red **e-CALLISTO**. Vas a corregir bugs,
reorganizar la UI y portar funciones desde el código de referencia de Sahan que ya está en el repo.

## Estructura del repositorio

```
TFG-AstroDoncel/
├── backend/main.py                 # FastAPI: todos los endpoints + pipeline científico
├── frontend/src/
│   ├── App.jsx                     # Estado global + barra lateral
│   ├── Spectrogram.jsx             # Plotly (heatmap por capas + GOES + zoom)
│   └── App.css                     # Estilos
├── Sahan/                          # CÓDIGO DE REFERENCIA — NO se edita, solo se porta desde aquí
│   ├── e-Callisto_FITS_Analyzer-master/   # App de escritorio PySide6 (de aquí porté el RFI actual)
│   │   └── src/Backend/{rfi_filters,noise_reduction,measurements,type_ii_band_splitting,
│   │                     goes_overlay,spectral_overview,multi_station_comparison}.py
│   └── Burst_No_Burst-master/      # Detector de bursts ML (CNN+MIL) + RFI mejorado
│       ├── src/preprocess/{rfi,background,standardize,pipeline}.py   # RFI SUPERIOR
│       ├── src/infer/deploy.py     # inferencia del clasificador
│       └── deploy/deploy_v1/model.pt + threshold.json               # modelo entrenado
```

**Stack actual:** FastAPI (astropy, numpy, scipy, sunpy) en :8000; React + Vite + Plotly.js (WebGL) en :5173.
El pipeline en `_build_spectrogram()` (backend/main.py) hace: cargar FITS → restar fondo (percentil 25 por
canal) → [RFI opcional] → clip percentil global (p2–p98) → JSON → heatmap Plotly.

---

## PARTE A — BUGS A CORREGIR (prioridad alta)

### A1. El filtro RFI de Sahan no limpia bien
**Causa raíz:** en `backend/main.py`, `_clean_rfi()` / `_mask_hot_channels()` se portaron de la versión
ANTIGUA del FITS Analyzer. Ese algoritmo puntúa cada canal como `|mediana_fila| + MAD` y aplica un z-score
robusto — pero como se ejecuta DESPUÉS de la resta de fondo, la mediana de cada fila ≈ 0 y apenas enmascara
nada. Además el `median_filter` calcula un `residual` que nunca se usa.

**Qué hacer:** portar el pipeline de RFI **muy superior** de `Sahan/Burst_No_Burst-master/src/preprocess/rfi.py`:
- `detect_persistent_narrowband_rfi()` — detecta RFI de banda estrecha persistente por **ocupación**
  (fracción de muestras temporales con |z| > umbral en cada canal). Mucho más fiable que el score actual.
- `detect_impulsive_rfi()` — detecta RFI impulsivo con `scipy.ndimage.label` (componentes conexas) y
  descarta componentes diminutas (`min_component_size`).
- `inpaint_with_channel_median()` — repara las zonas enmascaradas con la mediana del canal (no solo
  interpolación de vecinos).
- `mitigate_rfi()` combina las tres máscaras y devuelve `(cleaned, mask, stats)`.

Integra `mitigate_rfi` como el nuevo motor RFI del backend (sustituye o convive como "RFI v2"). Devuelve en
la respuesta las estadísticas (`persistent_channels`, `masked_fraction`, `occupancy_mean`) para mostrarlas
en la UI. Mantén compatibilidad de la firma de `SpectrogramResponse`.

### A2. El overlay translúcido de varias estaciones se ve mal
**Causa raíz:** en `Spectrogram.jsx` se apilan varios `heatmap` de Plotly con `opacity`. Un heatmap rellena
TODO el rectángulo, así que el fondo oscuro (intensidades bajas) de la capa de arriba tapa la de abajo y todo
se emborrona. Además cada estación tiene **rangos de frecuencia distintos**, por lo que superponerlas píxel a
píxel no tiene sentido físico.

**Qué hacer — implementa DOS modos de comparación y un selector:**
1. **Modo "Paneles apilados sincronizados"** (recomendado como predeterminado, es como lo hace Sahan en
   `multi_station_comparison.py`): un subplot por estación, apilados verticalmente, **compartiendo el eje X
   de tiempo (UT)**. Cada panel con su propio eje de frecuencia y su colorbar. Es la forma científicamente
   correcta de comparar estaciones.
2. **Modo "Superposición translúcida"** (arréglalo para cuando el usuario lo pida explícitamente): para que
   el blending funcione, la escala de color de las capas superiores debe volverse **transparente en las
   intensidades bajas** (alpha creciente con el valor), de modo que solo los bursts brillantes se
   sobreimpongan. Genera para las capas ≥2 un colorscale con canal alfa gradual (rgba con alpha 0 cerca de
   vmin → alpha alto cerca de vmax) en vez de aplicar `opacity` global al trace.

Añade en la UI un toggle "Paneles / Superposición".

### A3. El zoom no aumenta la resolución de forma fiable
**Causa raíz:** el overview decima a `max_time_bins=1500` por bloque-media; el zoom llama a
`/api/spectrogram/zoom` que recorta datos crudos, pero `handleRelayout` en `Spectrogram.jsx` se dispara con
cualquier evento de relayout, el dedup por bounds exactos es frágil y el `debounce` de 350 ms puede perder
eventos. La frecuencia nunca se decima y el `vmin/vmax` se recalcula solo sobre el recorte (cambia el
contraste al hacer zoom, lo cual confunde).

**Qué hacer:**
- Robustecer `handleRelayout`: ignorar relayouts que no cambian el rango (solo redibujado), tratar zoom solo
  en X, solo en Y y en ambos, y cancelar peticiones en vuelo (AbortController) cuando llega un zoom nuevo.
- Que el zoom conserve el `vmin/vmax` del overview por defecto (con opción de "reajustar contraste a la
  región"), para que el usuario no vea saltos de contraste.
- Subir `_MAX_ZOOM_COLS` o hacerlo proporcional al ancho real del contenedor; asegurar que el patch de
  alta resolución realmente tiene más columnas que el overview en la ventana pedida (si no, no merece la pena).
- Indicador claro de "alta resolución activa" y botón "Overview" (ya existe, verificar que resetea bien).
- Que el zoom funcione también en modo multi-estación / paneles.

### A4. Estado inicial: no preseleccionar ninguna estación
En `App.jsx` los estados arrancan con `'SPAIN-SIGUENZA'`. Cambiar para que **al iniciar no haya ninguna
estación seleccionada** (`station = null`, `selectedStations = []`). La UI debe manejar el estado vacío con
elegancia: botón "Load" deshabilitado, mensaje "Selecciona una o más estaciones y una fecha", y la lista de
bursts vacía hasta que se elija una estación primaria.

---

## PARTE B — REORGANIZACIÓN DE LA UI (prioridad media)

La barra lateral está sobrecargada. Reorganiza con **pestañas superiores** (tabs) para agrupar herramientas,
manteniendo en la barra lateral solo lo esencial (estación, fecha, cargar). Propuesta de pestañas:

- **Observación**: selector de estaciones (mejorado, ver B2), fecha, lista de bursts por horas.
- **Procesado**: filtro RFI (con parámetros ajustables, ver C-parámetros), resta de fondo, presets de contraste.
- **Visualización**: colormap, Z min/Z max, modo de comparación (paneles/superposición), escala log/dB.
- **Contexto solar**: GOES/XRS (ya existe) + los nuevos overlays (SEP, Dst, Kp) si los implementas.
- **Capas**: control de visibilidad/opacidad por estación (ya existe).

### B2. Mejorar el selector de bursts por horas y estación
La lista de bursts (`App.jsx`) hoy solo aparece para la estación primaria en modo de una estación, agrupada
por hora. Mejoras:
- Barra de búsqueda/filtro de estaciones (la lista puede tener 70+ estaciones).
- Selector de bursts más claro: agrupación por hora colapsable, marca visual de los ficheros ya cacheados
  (`★`), tooltip con el nombre completo, y navegación anterior/siguiente burst con flechas del teclado.
- Cuando hay varias estaciones seleccionadas, permitir elegir cuál es la "primaria" que fija el bloque de
  15 min al que se sincronizan las demás.
- Mostrar cuántos ficheros hay disponibles por estación/día.

---

## PARTE C — NUEVAS FUNCIONES A PORTAR DESDE SAHAN (prioriza por impacto para un TFG)

Revisa el código de Sahan y propón/implementa. Ordenadas por valor científico:

1. **Detección automática de bursts (ML)** — `Sahan/Burst_No_Burst-master`. Hay un clasificador CNN+MIL
   entrenado (`deploy/deploy_v1/model.pt` + `threshold.json`, inferencia en `src/infer/deploy.py`). Crea un
   endpoint `/api/burst/detect` que, dado un espectrograma, devuelva probabilidad de burst y (si es posible)
   las ventanas temporales candidatas, y resáltalo en la UI. Es el mayor diferenciador para el TFG.
   *(Requiere torch; hazlo opcional/lazy para no romper el arranque si no está instalado.)*

2. **Regla / medida de deriva (drift)** — `Sahan/.../Backend/measurements.py`. Permitir hacer clic en dos
   puntos del espectrograma para medir duración (Δt), cambio de frecuencia (Δf) y **pendiente de deriva
   (dMHz/s)** — clave para clasificar bursts Tipo II/III.

3. **Parámetros de RFI ajustables en la UI** — replica `dialogs/rfi_control_dialog.py`: sliders/inputs para
   `z_thresh`, `occupancy_thresh`, `min_component_size` (RFI v2) y kernels, con Preview/Apply/Reset y contador
   de canales enmascarados.

4. **Curvas de luz** — intensidad vs tiempo a una frecuencia elegida (clic o input), superpuesta al
   espectrograma. Referencia en el Analyzer (light curves).

5. **Overview de día completo** — `Sahan/.../Backend/spectral_overview.py`: generar el espectro del día UTC
   completo de una estación en 6 paneles de 4 h con baseline mediano de día.

6. **Band-splitting Tipo II** — `Sahan/.../Backend/type_ii_band_splitting.py`: estimación de campo magnético
   a partir del desdoblamiento de banda. (Avanzado; opcional.)

7. **Overlays de contexto solar adicionales** — GOES SEP protones, Dst (Kyoto), Kp (GFZ): backends en
   `sep_proton.py`, `dst_index.py`, `kp_index.py`.

8. **Export**: exportar la figura actual (PNG de publicación) y el FITS procesado; visor de cabecera FITS
   (ya se devuelve `fits_header`, falta un panel para mostrarlo).

9. **Presets de contraste**: "Raw FITS Percentile (5–98%)" y presets guardables (del Analyzer).

Para cada función nueva que implementes: endpoint en `backend/main.py`, UI en la pestaña que corresponda, y
una nota en el README.

---

## Restricciones y criterios de aceptación

- **No edites nada dentro de `Sahan/`** — es material de referencia; solo se porta desde ahí.
- Mantén el estilo y las convenciones del código existente (nombres, docstrings, estructura de endpoints).
- El backend debe **arrancar aunque falten dependencias pesadas** (torch, sunpy): imports perezosos y
  degradación elegante (como ya hace `/api/goes`).
- Añade dependencias nuevas a `requirements.txt`.
- Prioriza en este orden: **A (bugs) → B (UI) → C (features)**. Empieza por A1, A2, A3, A4.
- Tras cada cambio grande, verifica que backend y frontend arrancan sin errores.
- Explica brevemente cada cambio y actualiza el README cuando añadas funciones.

Empieza revisando `backend/main.py`, `frontend/src/App.jsx`, `frontend/src/Spectrogram.jsx` y los ficheros de
`Sahan/` citados, y luego aborda los bugs A1–A4.
