FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY VERSION /VERSION
COPY frontend ./
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    SERVE_FRONTEND=1 \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    DATA_DIR_LOCAL=/data \
    TASK_RESULT_DIR=/data/task_results

WORKDIR /app
RUN groupadd --gid 10001 astrodoncel \
    && useradd --create-home --uid 10001 --gid 10001 astrodoncel
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY VERSION ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY backend ./backend
COPY scripts/start_single_host.py ./scripts/start_single_host.py
COPY tools ./tools
COPY --from=frontend-build /build/dist ./frontend/dist
RUN mkdir -p /data/task_results \
    && chown -R astrodoncel:astrodoncel /app /data

USER astrodoncel
EXPOSE 8000
CMD ["python", "scripts/start_single_host.py"]
