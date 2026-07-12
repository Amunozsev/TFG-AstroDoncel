# Contributing to AstroDoncel

Use Python 3.12 and Node 22. Install `requirements-dev.txt` and run `npm ci` in
`frontend/`. Keep third-party reference projects under `Sahan/` unchanged;
port only the minimal algorithm with attribution and tests.

Before opening a pull request run:

```text
ruff check backend tests tools
pytest
cd frontend
npm run lint
npm run build
```

Never accept an arbitrary filesystem path from an API client. Station, date and
FITS filename must pass `backend.security`, and filenames must match the
requested station/date. Heavy whole-day work belongs in `backend.worker` and
must expose progress through the task API.

Scientific changes require a reproducible fixture or synthetic test, units in
the response and an explicit warning when the method is experimental.
