"""Engine and small helpers. SQLite runs in WAL mode so the web app and pipeline threads can share it."""
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from . import config
from .models import KV, AdapterCache, utcnow


def make_engine(url: str | None = None):
    url = url or config.DB_URL
    if url.startswith("sqlite"):
        config.ensure_dirs()
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in url or url == "sqlite://":
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):   # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s


def get_kv(engine, key: str, default: str = "") -> str:
    with session_scope(engine) as s:
        row = s.get(KV, key)
        return row.value if row else default


def set_kv(engine, key: str, value: str) -> None:
    with session_scope(engine) as s:
        row = s.get(KV, key) or KV(key=key)
        row.value = value
        s.add(row)
        s.commit()


def cache_get(engine, key: str, max_age_hours: float = 24):
    with session_scope(engine) as s:
        row = s.get(AdapterCache, key)
        if row and utcnow() - row.fetched_at < timedelta(hours=max_age_hours):
            return row.payload, row.fetched_at
    return None


def cache_put(engine, key: str, payload: dict) -> None:
    with session_scope(engine) as s:
        row = s.get(AdapterCache, key) or AdapterCache(key=key)
        row.payload, row.fetched_at = payload, utcnow()
        s.add(row)
        s.commit()


__all__ = ["make_engine", "session_scope", "get_kv", "set_kv", "cache_get", "cache_put", "select", "Session"]
