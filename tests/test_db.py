from backend.db import normalize_database_url


def test_managed_postgres_urls_use_psycopg3():
    assert normalize_database_url("postgres://user:pass@db/name") == (
        "postgresql+psycopg://user:pass@db/name"
    )
    assert normalize_database_url("postgresql://user:pass@db/name") == (
        "postgresql+psycopg://user:pass@db/name"
    )
    assert normalize_database_url("sqlite:///data/test.db") == "sqlite:///data/test.db"
