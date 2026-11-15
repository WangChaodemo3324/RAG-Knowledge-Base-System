from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config):
    sys_path = str(PROJECT_ROOT)
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)


def pytest_collection_modifyitems(items):
    """Default unknown tests to unit; integration tests must opt in explicitly."""
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.integration)


@dataclass
class TestDatabase:
    """A throwaway PostgreSQL database with the full schema migrated."""

    engine: Engine
    url: str
    name: str


def _create_test_database() -> TestDatabase:
    from alembic import command
    from alembic.config import Config

    from backend.core.config import DATABASE_URL

    # Force IPv4: a WSL-distro postgres relay can bind [::1]:5433 and hijack
    # localhost's IPv6 resolution away from the Docker container.
    base_url = make_url(DATABASE_URL).set(host="127.0.0.1")
    admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    db_name = f"rag_test_{uuid.uuid4().hex[:10]}"
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    # Keep the URL OBJECT everywhere: str(url) masks the password as "***"
    # (SQLAlchemy 2.0) and a string round-trip would silently break auth.
    db_url_obj = base_url.set(database=db_name)
    engine = create_engine(db_url_obj, pool_pre_ping=True, connect_args={"connect_timeout": 10})

    # immediate smoke connection: surface auth problems here with full context
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"test db connect failed: host={db_url_obj.host} db={db_url_obj.database} "
            f"user={db_url_obj.username} err={exc}"
        ) from exc

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option(
        "sqlalchemy.url", db_url_obj.render_as_string(hide_password=False)
    )
    command.upgrade(alembic_cfg, "head")

    return TestDatabase(engine=engine, url=db_url_obj.render_as_string(hide_password=False), name=db_name)


def _drop_test_database(db: TestDatabase) -> None:
    db.engine.dispose()
    from backend.core.config import DATABASE_URL

    base_url = make_url(DATABASE_URL).set(host="127.0.0.1")
    admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{db.name}" WITH (FORCE)'))
    admin_engine.dispose()


@pytest.fixture()
def test_db() -> TestDatabase:
    """Fresh, fully-migrated throwaway database per test — fault injection and
    destructive scenarios never touch the real knowledge base."""
    db = _create_test_database()
    yield db
    _drop_test_database(db)


@pytest.fixture()
def db_session(test_db: TestDatabase):
    session = Session(bind=test_db.engine, expire_on_commit=False, autoflush=False)
    try:
        yield session
    finally:
        session.close()
