import pytest

from backend.db import init_db


@pytest.fixture(scope="session", autouse=True)
def initialize_test_schema():
    init_db()
