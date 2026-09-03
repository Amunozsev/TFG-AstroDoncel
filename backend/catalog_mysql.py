"""Read-only access to Manuel's AstroDoncel burst-report database.

The application keeps its own PostgreSQL/SQLite catalogue.  This module only
reads the external MySQL source so a temporary source outage cannot make the
rest of the API unavailable.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import URL, make_url

SOURCE_ID = "uah_mysql"

_COLUMN_ALIASES = {
    "event_id": ("event_id", "eventid", "id"),
    "date": ("date", "event_date", "eventdate", "fecha"),
    "time": ("time", "event_time", "eventtime", "hora"),
    "key": ("key", "event_key", "eventkey", "clave"),
    "type": ("type", "burst_type", "bursttype", "tipo"),
    "intensity": ("intensity", "intensidad"),
    "remarks": ("remarks", "remark", "comments", "comment", "observaciones"),
    "stations": ("stations", "station", "estaciones", "estacion"),
    "min_lon": ("min_lon", "min_long", "min_longitude", "minlon", "minlong"),
    "mid_lon": ("mid_lon", "mid_long", "mid_longitude", "midlon", "midlong"),
    "max_lon": ("max_lon", "max_long", "max_longitude", "maxlon", "maxlong"),
}
_REQUIRED_COLUMNS = {"date", "time", "type", "intensity", "stations", "min_lon", "mid_lon", "max_lon"}


def _normalise_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@dataclass(frozen=True)
class ReflectedSource:
    table: Table
    columns: dict[str, object]


def is_configured() -> bool:
    """Return whether enough non-secret settings exist to attempt MySQL."""
    if os.environ.get("BURST_SOURCE_DATABASE_URL", "").strip():
        return True
    return all(
        os.environ.get(name, "").strip()
        for name in ("BURST_SOURCE_MYSQL_HOST", "BURST_SOURCE_MYSQL_USER", "BURST_SOURCE_MYSQL_DATABASE")
    )


def configured_source_url() -> URL:
    """Build a URL without forcing passwords to be URL-escaped in ``.env``."""
    explicit = os.environ.get("BURST_SOURCE_DATABASE_URL", "").strip()
    if explicit:
        url = make_url(explicit)
        if url.get_backend_name() not in {"mysql", "mariadb"}:
            raise ValueError("BURST_SOURCE_DATABASE_URL must use MySQL or MariaDB")
        if url.drivername in {"mysql", "mariadb"}:
            url = url.set(drivername=f"{url.drivername}+pymysql")
        return url

    host = os.environ.get("BURST_SOURCE_MYSQL_HOST", "").strip()
    user = os.environ.get("BURST_SOURCE_MYSQL_USER", "").strip()
    database = os.environ.get("BURST_SOURCE_MYSQL_DATABASE", "").strip()
    if not host or not user or not database:
        raise RuntimeError("The external Burst Reports MySQL source is not configured")
    raw_port = os.environ.get("BURST_SOURCE_MYSQL_PORT", "").strip()
    try:
        port = int(raw_port) if raw_port else None
    except ValueError as exc:
        raise ValueError("BURST_SOURCE_MYSQL_PORT must be an integer") from exc
    return URL.create(
        "mysql+pymysql",
        username=user,
        password=os.environ.get("BURST_SOURCE_MYSQL_PASSWORD", ""),
        host=host,
        port=port,
        database=database,
    )


def _resolved_columns(table: Table) -> dict[str, object]:
    by_normalised = {_normalise_identifier(column.name): column for column in table.columns}
    resolved: dict[str, object] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            column = by_normalised.get(_normalise_identifier(alias))
            if column is not None:
                resolved[canonical] = column
                break
    return resolved


def _reflect_source(connection, configured_table: str | None = None) -> ReflectedSource:
    inspector = inspect(connection)
    available = sorted(set(inspector.get_table_names()) | set(inspector.get_view_names()))
    if configured_table:
        if configured_table not in available:
            raise RuntimeError(f"Configured Burst Reports table/view '{configured_table}' was not found")
        names = [configured_table]
    else:
        names = available

    candidates: list[ReflectedSource] = []
    for name in names:
        table = Table(name, MetaData(), autoload_with=connection)
        columns = _resolved_columns(table)
        if _REQUIRED_COLUMNS.issubset(columns):
            candidates.append(ReflectedSource(table=table, columns=columns))

    if not candidates:
        detail = f" in '{configured_table}'" if configured_table else ""
        raise RuntimeError(f"No Burst Reports table/view with the required columns was found{detail}")
    if len(candidates) > 1:
        names = ", ".join(candidate.table.name for candidate in candidates)
        raise RuntimeError(
            "Several possible Burst Reports tables/views were found "
            f"({names}); set BURST_SOURCE_MYSQL_TABLE explicitly"
        )
    return candidates[0]


def read_rows(
    *,
    source_url: str | URL | None = None,
    table_name: str | None = None,
) -> list[Mapping[str, object]]:
    """Return canonical read-only rows from the configured source table/view.

    ``source_url`` and ``table_name`` are injectable so reflection and parsing
    can be tested without a live UAH service.  Production calls use environment
    configuration and never emit credentials.
    """
    url = make_url(source_url) if isinstance(source_url, str) else source_url
    url = url or configured_source_url()
    timeout = max(1, int(os.environ.get("BURST_SOURCE_MYSQL_TIMEOUT_SECONDS", "8")))
    connect_args = {}
    if url.get_backend_name() in {"mysql", "mariadb"}:
        connect_args = {"connect_timeout": timeout, "read_timeout": timeout, "write_timeout": timeout}
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800, connect_args=connect_args)
    try:
        with engine.connect() as connection:
            reflected = _reflect_source(
                connection,
                table_name if table_name is not None else os.environ.get("BURST_SOURCE_MYSQL_TABLE", "").strip() or None,
            )
            statement = select(*(
                column.label(canonical)
                for canonical, column in reflected.columns.items()
            ))
            return [dict(row._mapping) for row in connection.execute(statement)]
    finally:
        engine.dispose()
