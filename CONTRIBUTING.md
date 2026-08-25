# Contributing to AstroDoncel

Use Python 3.12 and Node 22. Install `requirements-dev.txt` and run `npm ci` in
`frontend/`. Keep third-party reference projects under `Sahan/` unchanged;
port only the minimal algorithm with attribution and tests.

Before opening a pull request run:

```text
ruff check backend tests migrations tools scripts/start_single_host.py
python -m pytest
pip-audit -r requirements-dev.txt
cd frontend
npm run lint
npm run test
npm run build
```

Deployment changes must also pass `docker compose config --quiet` and the
Compose smoke job in CI. Keep Alembic migrations in the production dependency
profile because the deployment runs them before API and worker startup.

Never accept an arbitrary filesystem path from an API client. Station, date and
FITS filename must pass `backend.security`, and filenames must match the
requested station/date. Heavy overview and temporal-combination work belongs in
`backend.worker` and must expose progress through the task API.

Scientific changes require a reproducible fixture or synthetic test, units in
the response and an explicit warning when the method is experimental.
