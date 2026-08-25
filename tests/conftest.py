import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Set a process-unique database before importing the application. This keeps the
# suite deterministic when another pytest process or a local worker is running.
_TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="astrodoncel-tests-"))
os.environ["DATABASE_URL"] = os.environ.get(
    "ASTRODONCEL_TEST_DATABASE_URL",
    f"sqlite:///{(_TEST_STATE_DIR / 'test.db').as_posix()}",
)
os.environ["DATA_DIR_LOCAL"] = str(_TEST_STATE_DIR / "data")
os.environ["TASK_RESULT_DIR"] = str(_TEST_STATE_DIR / "task-results")

from backend.db import engine, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def initialize_test_schema():
    init_db()
    yield
    engine.dispose()
    shutil.rmtree(_TEST_STATE_DIR, ignore_errors=True)
