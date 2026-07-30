# AstroDoncel agent instructions

- Read `HANDOFF.md`, `ROADMAP_COMPLETO_TFG.md`, `README.md` and the real code before broad changes.
- Do not edit `Sahan/`; it is reference material.
- Authoritative station coordinates come from FITS headers or live archive data, not hand-written guesses.
- Keep the API functional without optional external services where possible.
- Never expose arbitrary local paths. Use `backend.security` for all archive identifiers.
- Run CPU/memory-heavy analysis through the persistent task worker.
- Preserve scientific units and distinguish measured facts, heuristics and experimental outputs.
- Required checks: Ruff, pytest, frontend ESLint and production build.
