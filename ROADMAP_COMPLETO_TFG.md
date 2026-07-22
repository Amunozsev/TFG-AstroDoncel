# Roadmap completo del TFG AstroDoncel

Auditoría técnica actualizada: 23 de julio de 2026
Ámbito: backend, frontend, persistencia, worker, pipeline científico, modelo ML, pruebas, dependencias, despliegue y archivos versionados.

## 1. Resumen ejecutivo

AstroDoncel ya es un prototipo funcional avanzado: consulta el archivo e-CALLISTO, descarga y procesa FITS, muestra espectrogramas interactivos, compara estaciones, añade contexto GOES, mitiga RFI, ejecuta inferencia ONNX, mantiene un catálogo, genera estadísticas y delega análisis diarios a un worker persistente. La instalación local con SQLite funciona sin PostgreSQL ni los repositorios de Sahan.

La prioridad ya no es añadir muchas pantallas. Para convertirlo en una entrega de TFG reproducible y defendible hay que cerrar cinco frentes:

1. Trazabilidad científica del modelo y de las heurísticas.
2. Fiabilidad de base de datos, migraciones, descargas y tareas.
3. Pruebas de los flujos reales que hoy no están cubiertos.
4. Reducción de monolitos y estados obsoletos en la interfaz.
5. Piloto reproducible en Docker/NAS con límites de recursos y recuperación.

No se recomienda implementar todavía un clasificador multiclase II–V ni presentar el band-splitting como resultado validado. Ambas líneas necesitan datos etiquetados, protocolo experimental y métricas, no solo código.

### Estado de implementación — 23 de julio de 2026

Quedan implementados y verificados en el repositorio:

- inicio por lifespan, creación determinista de SQLite, readiness 503 y migraciones Alembic explícitas;
- deduplicación/límite global, validación previa, cancelación cooperativa, latido, recuperación y retención de tareas;
- descarga FITS temporal, limitada, validada, bloqueada por recurso y publicada atómicamente;
- catálogo mensual persistente con TTL y corrección de eventos que cruzan medianoche;
- separación `ml_cnn`/`heuristic_visual`, hash ONNX, método y coincidencia oficial como metadato, sin fingir clasificación de tipo;
- export FITS con ambos ejes, UTC, unidades, parámetros, historial y checksum;
- cancelación de peticiones frontend obsoletas, reinicio por contexto y regresiones Vitest para curva/overview;
- bundle parcial de Plotly: de aproximadamente 4,65 MB a 1,24 MB sin comprimir;
- `MODEL_CARD.md`, `THIRD_PARTY_NOTICES.md`, CI ampliada a PostgreSQL/migraciones/Vitest/audit.

Siguen abiertos porque necesitan datos, infraestructura o una decisión humana: licencia raíz y permiso de pesos, reproducción independiente de métricas ML, dataset científico versionado, E2E completo en CI, modularización de los monolitos y piloto Docker/NAS con backup/restauración. Las secciones siguientes conservan el plan completo como trazabilidad; los puntos de la lista anterior ya no son trabajo pendiente.

## 2. Estado verificado

### Arquitectura actual

```text
React 19 + Vite 8 + Plotly
  App.jsx (estado global y navegación)
  Spectrogram.jsx (visualización científica)
  páginas de mapa, catálogo, estadísticas, overview y curvas
                  │
                  │ HTTP/JSON + GZip
                  ▼
FastAPI
  main.py (archivo, FITS, RFI, GOES, mapas y endpoints principales)
  api_features.py (catálogo, exportación, curvas y tareas)
  burst_detect.py (ONNX + postprocesado y localizador heurístico)
                  │
       ┌──────────┴──────────┐
       ▼                     ▼
SQLite/PostgreSQL       Worker persistente
catálogo, metadatos,    detección diaria, overview,
GOES y tareas           combinación temporal y artefactos
```

### Fortalezas confirmadas

- Validación de estación, fecha y nombre FITS en `backend.security`; no se aceptan rutas locales arbitrarias.
- API utilizable con SQLite y degradación parcial cuando faltan servicios externos opcionales.
- ONNX Runtime en producción; PyTorch está separado en el toolchain ML.
- Trabajos de día completo en un worker con estado y progreso persistidos.
- Datos científicos con unidades en las respuestas principales y aviso explícito en Type II experimental.
- GZip, CORS configurable, proxy Nginx, contenedores sin privilegios y API de un solo worker.
- Interfaz funcional y responsive, incluyendo scroll del overview y cierre de la curva de luz.
- CI con Ruff, pytest, ESLint y build.
- 42 pruebas backend, 2 regresiones frontend y `npm audit` sin vulnerabilidades conocidas en el lockfile auditado.

### Deuda confirmada que permanece abierta

- `backend/main.py`, `App.jsx`, `Spectrogram.jsx` y `App.css` siguen siendo monolitos; deben dividirse detrás de tests de caracterización.
- La cobertura crítica ha mejorado, pero faltan pruebas de descarga real simulada, GOES, paridad ONNX, PostgreSQL concurrente y un E2E completo de navegador en CI.
- El límite de cola es global; si se expone el portal a usuarios no confiables harán falta identidad, cuota por usuario/IP y almacenamiento del dedupe en DB para múltiples réplicas de API.
- La cancelación es cooperativa y espera al siguiente punto de control entre ficheros; una inferencia/lectura individual no se puede abortar a mitad.
- El overview omite segmentos incompatibles o erróneos y calcula el baseline después de una reducción que preserva máximos; hace falta validar la definición científica y mostrar omisiones.
- El bundle Plotly bajó a ~1,24 MB sin comprimir, pero sigue siendo el principal coste de carga y merece medición de TTI/memoria.
- `MODEL_CARD.md` y `THIRD_PARTY_NOTICES.md` registran lo conocido, pero faltan licencia raíz, upstream commits exactos, dataset de validación y permiso escrito para redistribuir los pesos.
- Docker no está instalado en el equipo auditado, por lo que el Compose se revisó estáticamente pero no se ejecutó de extremo a extremo en el NAS objetivo.

## 3. Prioridad P0 — antes de entregar o publicar

### P0.1 Trazabilidad científica y ficha del modelo

Objetivo: que cada resultado pueda defenderse como medido, inferido o heurístico.

Cambios:

- Crear `MODEL_CARD.md` con origen de pesos, licencia, dataset, partición, preprocessing, umbral, PR-AUC, ROC-AUC, F1, limitaciones y estaciones/épocas representadas.
- Unificar el umbral efectivo en una sola fuente versionada y validar su hash al cargar el bundle.
- Separar en base de datos y API `cnn_mil`, `visual_candidate` y coincidencia con catálogo oficial.
- No presentar el tipo oficial heredado por coincidencia temporal como una clasificación producida por la red.
- Añadir al resultado versión del modelo, hash ONNX, parámetros, método localizador y advertencias.
- Medir el localizador visual en un conjunto independiente o mantenerlo etiquetado como heurística exploratoria.

Criterio de aceptación: a partir de una fila del catálogo se puede reconstruir qué método produjo cada campo y con qué versión/configuración.

### P0.2 Cola de tareas segura y recuperable

Cambios:

- Deduplicar tareas activas por tipo, estación, fecha y opciones normalizadas.
- Limitar número de tareas pendientes por cliente y globalmente.
- Validar los nombres de `combine_time` antes de guardar la tarea, no al ejecutarla.
- Añadir cancelación cooperativa y marca de latido del worker.
- Reencolar o fallar tareas `running` obsoletas al arrancar.
- Añadir retención para filas finalizadas y artefactos, con limpieza segura programable.
- Registrar excepciones del worker con `request/task id`; hoy varios fallos se convierten solo en texto de error.

Criterio de aceptación: una caída del worker no deja trabajos bloqueados indefinidamente y repetir un clic no duplica un análisis diario.

### P0.3 Persistencia, migraciones y readiness

Cambios:

- Crear el directorio de SQLite antes de construir/inicializar el motor.
- Sustituir `create_all/drop_all` de la migración por operaciones Alembic explícitas.
- Eliminar la inicialización silenciosa durante imports y usar un lifespan de FastAPI.
- Hacer que `/ready` devuelva 503 cuando una dependencia obligatoria no está lista.
- Decidir qué endpoints siguen disponibles sin DB y reflejarlo en readiness.
- Ejecutar `alembic upgrade head` en el flujo de despliegue, con copia de seguridad previa.
- Probar SQLite y PostgreSQL en CI.

Criterio de aceptación: un clon limpio crea su SQLite de forma determinista; una instancia con DB caída no pasa el healthcheck de disponibilidad.

### P0.4 Pruebas de regresión críticas

Añadir:

- Tests de `/api/files`, espectrograma, zoom, light curve, export FITS y tareas usando FITS sintéticos pequeños.
- Tests del worker para éxito, reintento, fallo, artefacto gzip y recuperación.
- Tests de catálogo para duplicados concurrentes, rangos, medianoche y estaciones reales complejas.
- Paridad ONNX con fixture reproducible y tolerancia numérica documentada.
- Test de que el FITS exportado vuelve a abrirse y conserva ejes/metadatos.
- Frontend tests para cambio de estación, respuestas fuera de orden, cierre de curva y overview.
- Un smoke E2E de navegador con API y worker reales.

Criterio de aceptación: los flujos que el usuario usa en la demo fallan en CI si se rompen.

### P0.5 Licencia, atribución y procedencia

Cambios:

- Añadir licencia del proyecto elegida por el autor/universidad.
- Añadir `THIRD_PARTY_NOTICES.md` para e-CALLISTO, Sahan, SunPy, Plotly y pesos del modelo.
- Confirmar por escrito que el modelo `.pt/.onnx` puede redistribuirse.
- Quitar rutas absolutas del equipo del autor original en metadatos publicados o marcarlas como procedencia histórica.
- Referenciar dataset y commits/repositorios de origen con versión exacta.

Criterio de aceptación: un tercero sabe qué puede reutilizar y de dónde procede cada algoritmo/modelo.

### P0.6 Piloto Docker/NAS

Cambios:

- Ejecutar Compose en Linux o NAS real; este punto no puede cerrarse solo con revisión estática.
- Validar arquitectura CPU, memoria ONNX, permisos UID 10001, montaje de archivo en solo lectura y persistencia PostgreSQL.
- Probar reinicios de API, worker, DB y host.
- Configurar HTTPS, backups, restauración y rotación de logs.
- Medir tiempo de carga de FITS, overview diario, inferencia y pico de memoria.

Criterio de aceptación: despliegue reproducible desde cero y recuperación documentada ante reinicio y pérdida de contenedor.

## 4. Prioridad P1 — robustez y mantenibilidad

### P1.1 Descargas y caché

- Descargar a `.part`, aplicar límite de tamaño y hacer `os.replace` atómico al terminar.
- Bloquear descargas concurrentes del mismo identificador.
- Validar cabecera FITS antes de publicar el fichero en caché.
- Diferenciar error remoto, timeout, contenido inválido y ausencia real.
- Aplicar política de retención también a GOES, artefactos y metadatos huérfanos.
- Limitar la caché LRU por bytes, no solo por ocho ficheros.

### P1.2 Modularización del backend sin cambiar resultados

Extraer gradualmente:

```text
backend/config.py
backend/archive.py
backend/fits_io.py
backend/pipeline.py
backend/rfi.py
backend/goes.py
backend/stations.py
backend/routes/*.py
```

Mantener primero tests de caracterización. No mezclar este refactor con cambios científicos.

### P1.3 Estado frontend y concurrencia

- Introducir un reducer o hooks por dominio en lugar de concentrar todo en `App.jsx`.
- Cancelar/ignorar respuestas obsoletas de estación, ficheros y espectrograma.
- Cerrar o reiniciar curva, overview, detecciones y tarea cuando cambia su contexto.
- Mostrar siempre estación, fecha, fichero y método junto a un resultado derivado.
- Añadir error boundary para Plotly y reintento de artefactos.
- Dar al overview y a la curva estados explícitos: cerrado, cargando, listo y error.

### P1.4 Exportación científica reproducible

- Conservar eje temporal, eje de frecuencia, unidades, cabecera original compatible y `HISTORY` del pipeline.
- Incluir parámetros de background, RFI, escala y versión de software.
- Evitar etiquetar `median_dB` como calibración absoluta si es una conversión instrumental aproximada.
- Añadir checksum y manifest JSON junto a productos derivados.

### P1.5 Catálogo e ingesta

- Persistir qué meses se descargaron, ETag/Last-Modified, hora de actualización y error.
- No consultar ETHZ en cada petición de lectura.
- Corregir eventos que terminan después de medianoche.
- Ampliar fixtures con formatos reales y casos dañados.
- Separar catálogo oficial, detecciones ML y relaciones de xmatch en el esquema.

### P1.6 Rendimiento frontend

- Construir un bundle parcial de Plotly con solo heatmap/scatter/scattergeo o cargar Plotly por vista.
- Medir tamaño, TTI y memoria antes/después.
- Virtualizar listas largas de estaciones/ficheros si las métricas lo justifican.
- Evaluar un transporte binario para matrices solo después de medir GZip JSON.

### P1.7 Observabilidad

- Garantizar `X-Request-ID` también en excepciones no controladas.
- Logging JSON en contenedores, sin rutas sensibles ni payloads científicos completos.
- Métricas de latencia, descargas, caché, tareas, fallos y memoria.
- Panel mínimo y alertas para cola bloqueada, DB no disponible y disco bajo.

### P1.8 Dependencias y CI

- Actualizar primero parches compatibles y luego mayores en PR separados.
- Evaluar `react-plotly.js` 4 y ESLint 10 solo con pruebas visuales/E2E.
- Añadir Dependabot/Renovate y auditoría Python (`pip-audit`) y npm.
- Hacer que Ruff incluya `migrations` y `tools` en CI.
- Añadir smoke de migración y build de imágenes Docker.
- Conservar lockfile frontend; valorar lock reproducible Python con hashes.

## 5. Prioridad P2 — calidad de producto y memoria del TFG

### P2.1 Validación científica de productos

- Dataset de referencia con eventos/no-eventos, varias estaciones, focus codes y niveles de RFI.
- Comparar background/RFI/overview con referencia Sahan mediante métricas y figuras.
- Reportar sensibilidad de umbrales y falsos positivos.
- Mostrar segmentos omitidos e incompatibilidades del overview.
- Mantener las coordenadas FITS/live como fuente autoritativa; cualquier fallback manual debe seguir marcado como aproximado y no usarse en cálculos.
- Documentar que el terminador del mapa es una aproximación visual.

### P2.2 Navegación y reproducibilidad de la UI

- Rutas URL para vista, estación, fecha, fichero y filtros; soporte de atrás/adelante.
- Historial de tareas y reapertura de resultados.
- Compartir enlaces sin exponer rutas locales.
- Presets exportables/importables con versión de esquema.

### P2.3 Accesibilidad

- Resumen tabular/textual alternativo para gráficos Plotly.
- Navegación completa por teclado, gestión de foco de modales y anuncios de progreso.
- Contraste y zoom al 200 %, pruebas con lector de pantalla y axe.

### P2.4 Documentación académica

- Diagrama de despliegue final y diccionario de datos.
- Tabla de decisiones: hecho medido, heurística y resultado experimental.
- Benchmarks reproducibles con hardware, versión, muestra y repeticiones.
- Capturas regeneradas desde una versión etiquetada del repositorio.

## 6. Prioridad P3 — investigación futura

- Clasificador multiclase II, III, IV y V después de crear y validar el dataset.
- Estimación Type II con incertidumbres, propagación de errores y revisión experta.
- Contexto SEP/Dst/Kp solo si aporta a los objetivos evaluables del TFG.
- Autenticación/roles si el portal deja de ser solo lectura pública.
- Almacenamiento de objetos y cola distribuida si una sola máquina deja de ser suficiente.
- API binaria/streaming para días completos si los benchmarks lo exigen.

## 7. Orden recomendado de ejecución

1. Congelar una versión funcional y fixtures científicos.
2. P0.1 trazabilidad ML y P0.5 licencias.
3. P0.3 persistencia/readiness y P0.2 recuperación de tareas.
4. P0.4 tests críticos.
5. P1.1 descargas atómicas y límites de caché.
6. P1.3 estados obsoletos del frontend.
7. P1.4 export FITS reproducible y P1.5 catálogo.
8. P0.6 piloto NAS con métricas.
9. Solo después: refactor de monolitos y optimización Plotly.
10. P2 para cerrar memoria, accesibilidad y reproducibilidad.

## 8. Definición de terminado para la entrega

- Ruff, pytest, ESLint y build pasan desde un clon limpio.
- Migraciones probadas en SQLite y PostgreSQL.
- Smoke E2E carga FITS, curva, overview y detección.
- No hay tareas huérfanas ni artefactos sin política de retención.
- Cada resultado indica unidad, método, versión y si es medido, heurístico o experimental.
- Modelo y código tienen licencia/procedencia documentada.
- Compose validado en el host objetivo con backup/restauración.
- README coincide con los comandos y endpoints reales.
- La memoria cita métricas reproducibles, no estimaciones sin protocolo.

## 9. Limpieza realizada durante esta auditoría

Se eliminaron únicamente elementos sin referencias ni valor de ejecución:

- `api-preview.log` y `api-preview.err.log` de una sesión antigua.
- `frontend/README.md`, que era el texto genérico de create-vite.
- `frontend/src/assets/hero.png` y `frontend/public/icons.svg`, sin referencias en el proyecto.

Se conservaron deliberadamente:

- `data/`, porque contiene caché, SQLite y artefactos de pruebas manuales y está ignorado por Git.
- `.venv`, `frontend/node_modules` y `frontend/dist`, necesarios para el entorno local/preview y ya ignorados.
- Modelos `.pt` y `.onnx`: el primero permite reproducir la exportación y el segundo es el runtime.
- Anteproyecto y capturas. Dos PDF del anteproyecto tienen el mismo hash, pero se mantienen por posible trazabilidad de entrega.
- Toda la carpeta `Sahan/`, que sigue siendo material de referencia ignorado y no se modificó.
