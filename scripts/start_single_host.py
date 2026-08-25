"""Start migrations, the persistent worker and the web API in one container."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("astrodoncel.single_host")


def _run_migrations() -> None:
    attempts = max(1, int(os.environ.get("MIGRATION_STARTUP_ATTEMPTS", "15")))
    delay = max(0.5, float(os.environ.get("MIGRATION_RETRY_SECONDS", "2")))
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt == attempts:
            raise SystemExit("Database migrations did not complete")
        logger.warning("Migration attempt %d/%d failed; retrying in %.1f s", attempt, attempts, delay)
        time.sleep(delay)


def _terminate(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    _run_migrations()
    port = os.environ.get("PORT", "8000")
    commands = []
    if os.environ.get("RUN_TASK_WORKER", "1").strip().lower() not in {"0", "false", "no"}:
        commands.append(("worker", [sys.executable, "-m", "backend.worker"]))
    commands.append(("api", [
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", "0.0.0.0", "--port", port, "--workers", "1",
        "--proxy-headers", "--forwarded-allow-ips=*",
    ]))
    processes = [
        subprocess.Popen(command, env=os.environ.copy())
        for _name, command in commands
    ]

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        _terminate(processes)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("Started %s on port %s", ", ".join(name for name, _ in commands), port)
    try:
        while not stopping:
            for (name, _command), process in zip(commands, processes, strict=True):
                return_code = process.poll()
                if return_code is not None:
                    logger.error("%s exited with code %d", name, return_code)
                    _terminate(processes)
                    return return_code or 1
            time.sleep(1)
    finally:
        _terminate(processes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
