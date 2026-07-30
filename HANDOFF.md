# Continuidad de AstroDoncel

Fecha de actualización: 31 de julio de 2026.

Este documento permite retomar el proyecto desde otro ordenador o desde una conversación nueva sin depender del historial anterior de Codex.

## Por dónde empezar

1. Lee `AGENTS.md` para conocer las reglas que no deben romperse.
2. Lee `README.md` para instalar, ejecutar, probar y desplegar el sistema.
3. Lee `ROADMAP_COMPLETO_TFG.md` para distinguir lo ya implementado de lo pendiente.
4. Revisa el código real antes de proponer cambios amplios.

El repositorio oficial es:

```text
https://github.com/Amunozsev/TFG-AstroDoncel
```

La rama de trabajo actual es `main`.

## Estado funcional actual

AstroDoncel dispone de:

- frontend React/Vite/Plotly y API FastAPI;
- PostgreSQL en Docker y SQLite como fallback de desarrollo;
- migraciones Alembic;
- worker persistente para detección de día completo, overview y combinación temporal;
- catálogo de bursts `deARCE detection (v3)` con longitudes Min/Mid/Max;
- enlaces desde estaciones y marcadores Xmatch al espectrograma correspondiente;
- estadísticas, ranking, detecciones por día y Xmatch interactivo;
- inventario automático de estaciones y coordenadas aprendidas desde FITS/live archive;
- detector ONNX incluido en el repositorio;
- tests backend/frontend y CI;
- Compose con PostgreSQL, migración, API, worker, Nginx, healthchecks y persistencia;
- scripts de arranque y backup para Windows y Linux/NAS.

El despliegue Docker completo está probado en Windows con WSL 2. La ejecución física y los benchmarks en el NAS universitario siguen pendientes porque dependen de su arquitectura, permisos, memoria y rutas reales.

## Decisiones que deben conservarse

- `Sahan/` es solo referencia: no se modifica, no se versiona y no es necesario para ejecutar AstroDoncel.
- Las estaciones y coordenadas autoritativas proceden de FITS o del archivo vivo; no se mantiene un inventario manual inventado.
- La fuente predeterminada de Burst Reports es `dearce_v3`, mostrada como **deARCE detection (v3)**. No se mezclan datos oficiales, detecciones ML y heurísticas.
- Las operaciones pesadas se ejecutan en `backend.worker`, no dentro del proceso web.
- La API no acepta rutas locales arbitrarias; estación, fecha y filename pasan por `backend.security`.
- Se mantienen las unidades científicas y se distinguen datos medidos, inferencias, heurísticas y resultados experimentales.
- ONNX Runtime es el runtime de producción. PyTorch solo se instala para exportar o investigar el modelo.
- Docker/Nginx publica únicamente el portal web; PostgreSQL, API y worker permanecen internos.

## Qué viaja con un clon

GitHub contiene todo lo necesario para construir una instalación nueva:

- código y migraciones;
- `requirements*.txt` y `frontend/package-lock.json`;
- `model.onnx` y los metadatos del modelo;
- Dockerfiles, Compose, Nginx y scripts;
- pruebas, README, roadmap y reglas de agentes.

No viajan, deliberadamente:

- `.env` y secretos;
- `data/`, SQLite, cachés FITS, catálogo ya descargado y artefactos;
- volúmenes PostgreSQL de Docker;
- `backups/`;
- `.venv`, `node_modules` y builds;
- `Sahan/`.

Una instalación nueva reconstruye ese estado automáticamente desde ETHZ o desde el archivo NAS configurado. Para conservar el estado de otra instalación hay que trasladar un backup fuera de GitHub.

## Primer arranque en otro portátil

Instala Git y Docker Desktop. En Windows, Docker Desktop necesita WSL 2 y virtualización activa. Después:

```powershell
git clone https://github.com/Amunozsev/TFG-AstroDoncel.git
cd TFG-AstroDoncel
powershell -ExecutionPolicy Bypass -File .\scripts\docker-up.ps1
```

Comprueba:

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8080/ready
```

URLs:

- portal: <http://127.0.0.1:8080>
- OpenAPI: <http://127.0.0.1:8080/docs>
- disponibilidad: <http://127.0.0.1:8080/ready>

No hacen falta Python, Node.js ni los repositorios de Sahan para ejecutar el stack Docker. Para modificar y probar el código sin Docker, sigue la sección **Desarrollo local** del README.

## Comprobación antes de continuar

Desde la raíz:

```powershell
git status --short --branch
git pull --ff-only
docker compose ps
```

Antes de integrar cambios:

```powershell
.\.venv\Scripts\python.exe -m ruff check backend tests migrations tools
.\.venv\Scripts\python.exe -m pytest
cd frontend
npm run lint
npm run test
npm run build
```

Para cambios de despliegue se valida además:

```powershell
docker compose config --quiet
powershell -ExecutionPolicy Bypass -File .\scripts\docker-up.ps1
```

## Trabajo pendiente prioritario

No debe confundirse con un fallo de instalación:

- validar recursos, permisos UID/GID, rutas, reinicios, backup y restauración en el NAS real;
- decidir la licencia raíz y confirmar el permiso de redistribución de los pesos;
- crear un dataset científico versionado y reproducir métricas ML;
- añadir E2E completo de navegador;
- validar científicamente baseline, reducción del overview y heurísticas;
- modularizar gradualmente los archivos grandes detrás de tests de caracterización.

El detalle, criterios de aceptación y orden recomendado están en `ROADMAP_COMPLETO_TFG.md`.
