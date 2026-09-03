"""Periodically enforce the configured limits for the downloaded FITS cache."""

from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path

from tools.prune_cache import apply_plan, plan_prune, print_plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
_stop = threading.Event()


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def run_once() -> None:
    data_dir = Path(os.environ.get("DATA_DIR_LOCAL", "/data"))
    plan = plan_prune(
        data_dir,
        max_gb=_float_env("FITS_CACHE_MAX_GB", 20.0),
        max_age_days=_float_env("FITS_CACHE_MAX_AGE_DAYS", 90.0),
        min_idle_minutes=_float_env("FITS_CACHE_MIN_IDLE_MINUTES", 60.0),
        min_free_gb=_float_env("FITS_CACHE_MIN_FREE_GB", 5.0),
    )
    apply = _bool_env("FITS_CACHE_PRUNE_APPLY")
    print_plan(plan, apply=apply)
    if apply:
        deleted = apply_plan(plan)
        logger.info("FITS cache maintenance deleted %d files", len(deleted))
    else:
        logger.info("FITS cache maintenance is in dry-run mode; no files were deleted")


def _request_stop(_signum: int, _frame: object) -> None:
    _stop.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    interval = max(1.0, _float_env("FITS_CACHE_PRUNE_INTERVAL_HOURS", 6.0)) * 3600
    logger.info("FITS cache maintenance started; interval %.1f hours", interval / 3600)
    while not _stop.is_set():
        try:
            run_once()
        except Exception:
            logger.exception("FITS cache maintenance failed")
        _stop.wait(interval)


if __name__ == "__main__":
    main()
