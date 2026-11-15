"""Alembic migration tests: full upgrade/downgrade/upgrade cycle on a
throwaway database, plus schema-contract assertions."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def _alembic_cfg(db):
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db.url)
    return cfg


@pytest.mark.integration
class TestMigrations:
    def test_upgrade_downgrade_upgrade_cycle(self, test_db):
        cfg = _alembic_cfg(test_db)

        command.downgrade(cfg, "base")
        with test_db.engine.connect() as connection:
            tables = inspect(connection).get_table_names()
        assert "child_chunks" not in tables and "index_versions" not in tables

        command.upgrade(cfg, "head")
        with test_db.engine.connect() as connection:
            tables = inspect(connection).get_table_names()
        for table in ("index_versions", "documents", "parent_chunks", "child_chunks", "index_tasks", "alembic_version"):
            assert table in tables, f"{table} missing after re-upgrade"

    def test_pgvector_extension_and_indexes(self, test_db):
        with test_db.engine.connect() as connection:
            extension = connection.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one()
            indexes = {
                row[0]
                for row in connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'child_chunks'"))
            }
            embedding_type = connection.execute(
                text(
                    "SELECT udt_name FROM information_schema.columns "
                    "WHERE table_name='child_chunks' AND column_name='embedding'"
                )
            ).scalar_one()
            version_column_type = connection.execute(
                text(
                    "SELECT udt_name FROM information_schema.columns "
                    "WHERE table_name='child_chunks' AND column_name='metadata'"
                )
            ).scalar_one()

        assert extension == 1
        assert "ix_child_chunks_embedding_hnsw" in indexes
        assert "ux_child_chunks_version_child" in indexes
        assert embedding_type == "vector"
        assert version_column_type == "jsonb"

    def test_embedding_dimension_is_1024(self, test_db):
        with test_db.engine.connect() as connection:
            dimension = connection.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'child_chunks'::regclass AND attname = 'embedding'"
                )
            ).scalar_one()
        # pgvector typmod encodes the dimension
        assert dimension == 1024, f"BGE-M3 dense vectors are 1024-dim, column says {dimension}"
