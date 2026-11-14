"""Integration tests for the pgvector storage adapter (backend.indexing.pg_store).

Requires the compose database: docker compose up -d db, then alembic upgrade head.
Every test creates its own uniquely named version and cleans up afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.db import session_scope
from backend.db.models import VERSION_STATUS_ACTIVE
from backend.indexing import pg_store


def make_vec(seed: int, dim: int = 1024) -> list[float]:
    vector = [0.0] * dim
    vector[seed % dim] = 1.0
    return vector


@pytest.fixture()
def db_session():
    with session_scope() as session:
        yield session


@pytest.fixture()
def version(db_session):
    # remember the pre-test active version so teardown can restore it —
    # activate_version tests otherwise retire the shared database's active
    # version and leave the app without one until the next bootstrap
    original_active = pg_store.get_active_version(db_session)
    original_active_id = original_active.id if original_active else None

    name = f"test_{uuid.uuid4().hex[:12]}"
    version = pg_store.create_building_version(
        db_session,
        name=name,
        embedding_model="test-model",
        chunk_settings={"chunk_size": 700},
        metadata_schema_version="test",
    )
    db_session.flush()
    yield version
    # FK order: children/parents/documents CASCADE on version delete;
    # index_tasks.version_id is SET NULL, so tasks referencing this version
    # lose the FK and must be removed by matching the orphaned rows first.
    # Tests may create extra versions (v2 in fault-injection scenarios) — wipe
    # every test-prefixed version; real data versions start with "v_".
    db_session.execute(text("DELETE FROM index_tasks WHERE version_id IS NULL AND task_type LIKE 'test%' AND created_at > now() - interval '1 hour'"))
    db_session.execute(text("DELETE FROM index_versions WHERE name LIKE 'test_%'"))
    db_session.execute(text("DELETE FROM index_tasks WHERE version_id = :vid"), {"vid": version.id})
    db_session.execute(text("DELETE FROM index_versions WHERE id = :vid"), {"vid": version.id})
    if original_active_id is not None and pg_store.get_active_version(db_session) is None:
        pg_store.activate_version(db_session, original_active_id)
    db_session.flush()


def write_one_document(session, version, file_name: str = "doc_a.md") -> int:
    record = pg_store.upsert_document(
        session,
        version_id=version.id,
        file_name=file_name,
        file_hash="hash_" + file_name,
        file_size=123,
        modified_at="2026-11-15T00:00:00Z",
        document_count=1,
    )
    parent_id = uuid.uuid4().hex
    pg_store.write_chunks(
        session,
        version.id,
        record,
        parents=[
            {
                "parent_id": parent_id,
                "parent_index": 0,
                "content": "回滚流程：发布失败后执行 rollback 脚本，回滚到上一版本。",
                "metadata": {"file_name": file_name},
            }
        ],
        children=[
            {
                "child_id": uuid.uuid4().hex,
                "parent_index": 0,
                "child_index": 0,
                "content": "回滚流程：发布失败后执行 rollback 脚本。",
                "embedding": make_vec(1),
                "metadata": {"file_name": file_name},
            },
            {
                "child_id": uuid.uuid4().hex,
                "parent_index": 0,
                "child_index": 1,
                "content": "报销材料：发票、审批单、行程单。",
                "embedding": make_vec(2),
                "metadata": {"file_name": file_name},
            },
        ],
    )
    return record.id


@pytest.mark.integration
class TestVersionLifecycle:
    def test_only_one_active_version(self, db_session, version):
        pg_store.activate_version(db_session, version.id)
        active = pg_store.get_active_version(db_session)
        assert active is not None and active.id == version.id
        assert active.status == VERSION_STATUS_ACTIVE

        other = pg_store.create_building_version(
            db_session,
            name=version.name + "_b",
            embedding_model="m",
            chunk_settings={},
            metadata_schema_version="t",
        )
        db_session.flush()
        pg_store.activate_version(db_session, other.id)
        active2 = pg_store.get_active_version(db_session)
        assert active2 is not None and active2.id == other.id
        db_session.refresh(version)
        assert version.status == "retired"

    def test_cannot_duplicate_name(self, db_session, version):
        with pytest.raises(pg_store.VersionError):
            pg_store.create_building_version(
                db_session,
                name=version.name,
                embedding_model="m",
                chunk_settings={},
                metadata_schema_version="t",
            )


@pytest.mark.integration
class TestWritesAndSearch:
    def test_write_and_cosine_search(self, db_session, version):
        doc_id = write_one_document(db_session, version)
        assert doc_id > 0
        pg_store.activate_version(db_session, version.id)

        results = pg_store.search_children(db_session, version.id, make_vec(1), top_k=2)
        assert len(results) == 2
        assert results[0]["content"].startswith("回滚流程")
        assert results[0]["file_name"] == "doc_a.md"
        assert results[0]["parent_id"]
        assert results[0]["metadata"]["file_name"] == "doc_a.md"

    def test_expand_dedupes_parents(self, db_session, version):
        write_one_document(db_session, version)
        children = pg_store.search_children(db_session, version.id, make_vec(1), top_k=10)
        expanded = pg_store.expand_children_to_parents(db_session, version.id, children, top_k=10)
        assert len(expanded) == 1
        assert expanded[0]["retrieval_level"] == "parent"
        assert expanded[0]["content"].startswith("回滚流程")
        assert expanded[0]["metadata"]["matched_child_id"] == children[0]["child_id"]

    def test_validate_version_counts(self, db_session, version):
        write_one_document(db_session, version)
        assert pg_store.validate_version(db_session, version.id) == []

    def test_bm25_corpus_load(self, db_session, version):
        write_one_document(db_session, version)
        corpus = pg_store.load_children_for_bm25(db_session, version.id)
        assert len(corpus) == 2
        assert {item["file_name"] for item in corpus} == {"doc_a.md"}
        assert all("content" in item and "metadata" in item for item in corpus)

    def test_document_swap_keeps_no_orphans(self, db_session, version):
        write_one_document(db_session, version)
        record = pg_store.get_document(db_session, version.id, "doc_a.md")
        assert record is not None

        # swap: delete old chunks then write new ones inside the same transaction
        pg_store.delete_document_chunks(db_session, record)
        pg_store.write_chunks(
            db_session,
            version.id,
            record,
            parents=[
                {
                    "parent_id": uuid.uuid4().hex,
                    "parent_index": 0,
                    "content": "新版内容",
                    "metadata": {},
                }
            ],
            children=[
                {
                    "child_id": uuid.uuid4().hex,
                    "parent_index": 0,
                    "child_index": 0,
                    "content": "新版内容",
                    "embedding": make_vec(3),
                    "metadata": {},
                }
            ],
        )
        assert pg_store.validate_version(db_session, version.id) == []
        results = pg_store.search_children(db_session, version.id, make_vec(3), top_k=5)
        assert len(results) == 1 and results[0]["content"] == "新版内容"


@pytest.mark.integration
class TestTasksAndRecovery:
    def test_running_task_blocks_new_task(self, db_session, version):
        task = pg_store.start_task(db_session, "test_full_rebuild", version_id=version.id)
        with pytest.raises(pg_store.VersionError):
            pg_store.start_task(db_session, "test_incremental")
        pg_store.finish_task(db_session, task.id, succeeded=True, message="ok")

        task2 = pg_store.start_task(db_session, "test_incremental", version_id=version.id)
        pg_store.finish_task(db_session, task2.id, succeeded=False, error="boom")
        assert task2.status == "failed"

    def test_recover_stale_tasks(self, db_session, version):
        pg_store.start_task(db_session, "test_full_rebuild", version_id=version.id)
        recovered = pg_store.recover_stale_tasks(db_session, [])
        assert recovered == 1
        db_session.refresh(version)
        assert version.status == "failed"


@pytest.mark.integration
class TestFaultInjection:
    def test_failed_build_leaves_active_version_intact(self, db_session, version):
        """Building version 2 crashes: version 1 must remain active and readable."""
        write_one_document(db_session, version)
        pg_store.activate_version(db_session, version.id)

        v2 = pg_store.create_building_version(
            db_session,
            name=version.name + "_v2",
            embedding_model="m",
            chunk_settings={},
            metadata_schema_version="t",
        )
        db_session.flush()
        record = pg_store.upsert_document(
            db_session,
            version_id=v2.id,
            file_name="doc_x.md",
            file_hash="h",
            file_size=1,
            modified_at="",
            document_count=1,
        )
        pg_store.write_chunks(
            db_session,
            v2.id,
            record,
            parents=[{"parent_id": uuid.uuid4().hex, "parent_index": 0, "content": "x", "metadata": {}}],
            children=[],
        )
        pg_store.mark_version_failed(db_session, v2.id, "injected failure")

        active = pg_store.get_active_version(db_session)
        assert active is not None and active.id == version.id
        results = pg_store.search_children(db_session, active.id, make_vec(1), top_k=3)
        assert results and results[0]["content"].startswith("回滚流程")

    def test_partial_transaction_rollback(self, db_session, version):
        """A crash mid-swap must leave the document readable from its previous chunks."""
        write_one_document(db_session, version)
        pg_store.activate_version(db_session, version.id)
        db_session.commit()  # make setup visible to other sessions (READ COMMITTED)
        before = pg_store.search_children(db_session, version.id, make_vec(1), top_k=5)
        assert len(before) == 2

        from sqlalchemy.orm import Session

        from backend.db import engine as global_engine

        with Session(global_engine) as session2:
            record = pg_store.get_document(session2, version.id, "doc_a.md")
            pg_store.delete_document_chunks(session2, record)
            pg_store.write_chunks(
                session2,
                version.id,
                record,
                parents=[{"parent_id": uuid.uuid4().hex, "parent_index": 0, "content": "半途写入", "metadata": {}}],
                children=[
                    {
                        "child_id": uuid.uuid4().hex,
                        "parent_index": 0,
                        "child_index": 0,
                        "content": "半途写入",
                        "embedding": make_vec(4),
                        "metadata": {},
                    }
                ],
            )
            session2.rollback()  # injected crash before commit

        after = pg_store.search_children(db_session, version.id, make_vec(1), top_k=5)
        assert len(after) == 2
        assert pg_store.validate_version(db_session, version.id) == []
