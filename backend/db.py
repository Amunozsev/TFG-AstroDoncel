"""Small persistence layer; PostgreSQL in production, SQLite for local fallback."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DEFAULT_SQLITE = "sqlite:///./data/astrodoncel.db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE).replace("postgres://", "postgresql+psycopg://", 1)
_database_url = make_url(DATABASE_URL)
if _database_url.get_backend_name() == "sqlite" and _database_url.database not in {None, "", ":memory:"}:
    Path(_database_url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
ENGINE_KWARGS = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    ENGINE_KWARGS["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **ENGINE_KWARGS)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    coord_source: Mapped[str | None] = mapped_column(String(20))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FitsFile(Base):
    __tablename__ = "fits_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    station: Mapped[str] = mapped_column(String(80), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    focus_code: Mapped[str | None] = mapped_column(String(20), index=True)
    path: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(20), default="ethz")
    fits_header: Mapped[dict | None] = mapped_column(JSON_TYPE)


class BurstEvent(Base):
    __tablename__ = "burst_events"
    __table_args__ = (UniqueConstraint("source", "event_key", name="uq_burst_source_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    event_key: Mapped[str] = mapped_column(String(220))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    burst_type: Mapped[str | None] = mapped_column(String(30), index=True)
    intensity: Mapped[int | None] = mapped_column(Integer)
    min_lon: Mapped[float | None] = mapped_column(Float)
    mid_lon: Mapped[float | None] = mapped_column(Float)
    max_lon: Mapped[float | None] = mapped_column(Float)
    stations: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    score: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class TaskRecord(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class GoesDay(Base):
    __tablename__ = "goes_days"
    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON_TYPE)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CatalogMonth(Base):
    __tablename__ = "catalog_months"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    year_month: Mapped[str] = mapped_column(String(7), index=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
