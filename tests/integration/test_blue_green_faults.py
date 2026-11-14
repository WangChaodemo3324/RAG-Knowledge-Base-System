"""Blue-green index pipeline fault-injection tests.

Every scenario runs against its own throwaway database (conftest.test_db) with
a deterministic fake embedding — the real knowledge base is never touched.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.db.models import (
    ChildChunk,
    IndexVersion,
    VERSION_STATUS_ACTIVE,
    VERSION_STATUS_FAILED,
)
from backend.indexing import pg_store
from backend.indexing.index_pipeline import IndexPipeline, IndexPipelineError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "resource data"


class FakeEmbedding:
    """Deterministic, instant embeddings (hash-seeded unit vectors)."""

    model_name = "fake-embed"

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    def _vec(self, text):
        vec = [0.0] * 1024
        vec[hash(str(text)) % 1024] = 1.0
        return vec


@pytest.fixture()
def pipeline(test_db, monkeypatch):
    @contextmanager
    def factory():
        session = Session(bind=test_db.engine, expire_on_commit=False, autoflush=False)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # keep the heavy real embedding out of unit-speed fault tests
    monkeypatch.setattr("backend.indexing.index_pipeline.get_embedding", lambda: FakeEmbedding())
    return IndexPipeline(DATA_DIR, embedding=FakeEmbedding(), session_factory=factory)


@pytest.mark.integration
class TestFullBuildFaults:
    def test_pdf_parse_failure_degrades_gracefully(self, pipeline, test_db):
        """One unreadable file must not take down the build: version activates
        with the remaining files, failure is reported."""
        original_load = pipeline.processor.load_file

        def flaky_load(file_path):
            if file_path.suffix.lower() == ".pdf":
                raise RuntimeError("injected PDF parse failure")
            return original_load(file_path)

        pipeline.processor.load_file = flaky_load  # type: ignore[method-assign]
        result = pipeline.full_build(reason="fault: pdf parse")

        assert result["failed_files"], "pdf failure must be reported"
        assert any("PDF parse" in item["error"] for item in result["failed_files"])
        stats = _stats_for(test_db, _active_id(test_db))
        # 6 markdown files still indexed (7 files total, pdf excluded)
        assert stats["document_count"] == 6

    def test_embedding_failure_keeps_old_active(self, pipeline, test_db):
        pipeline.full_build(reason="v1 ok")
        first_active = _active_id(test_db)

        def broken_embed(texts):
            raise RuntimeError("injected embedding service failure")

        pipeline.embedding.embed_documents = broken_embed  # type: ignore[method-assign]
        # every file fails to embed → empty build must be refused, old active kept
        with pytest.raises(RuntimeError, match="no files were indexed"):
            pipeline.full_build(reason="v2 broken")

        assert _active_id(test_db) == first_active, "old active version must survive"
        with test_db.engine.connect() as connection:
            failed = connection.execute(
                IndexVersion.__table__.select().where(IndexVersion.status == VERSION_STATUS_FAILED)
            ).fetchall()
        assert failed, "broken version must be marked failed"
        # old version still serves queries
        session = Session(bind=test_db.engine)
        results = pg_store.search_children(session, first_active, [0.5] * 1024, top_k=3)
        session.close()
        assert results

    def test_activate_failure_keeps_previous_active(self, pipeline, test_db, monkeypatch):
        pipeline.full_build(reason="v1 ok")
        first_active = _active_id(test_db)

        original_activate = pg_store.activate_version

        def broken_activate(session, version_id):
            if version_id != first_active:
                raise RuntimeError("injected activation failure")
            return original_activate(session, version_id)

        monkeypatch.setattr(pg_store, "activate_version", broken_activate)
        with pytest.raises(RuntimeError, match="activation failure"):
            pipeline.full_build(reason="v2 activate-broken")

        assert _active_id(test_db) == first_active

    def test_rebuild_twice_no_duplicate_records(self, pipeline, test_db):
        r1 = pipeline.full_build(reason="first")
        assert not r1["failed_files"], f"first build failures: {r1['failed_files']}"
        r2 = pipeline.full_build(reason="second")
        assert not r2["failed_files"], f"second build failures: {r2['failed_files']}"

        with test_db.engine.connect() as connection:
            duplicates = connection.execute(
                ChildChunk.__table__.select()
            ).fetchall()
        child_ids = [(row.version_id, row.child_id) for row in duplicates]
        assert len(child_ids) == len(set(child_ids)), "no (version, child_id) duplicates"
        active = _active_id(test_db)
        stats = _stats_for(test_db, active)
        # 7 source files in resource data; every build indexes all of them
        assert stats["document_count"] == 7, f"docs={stats}, indexed={len(r2['indexed'])}"
        session = Session(bind=test_db.engine)
        versions = pg_store.list_versions(session)
        session.close()
        assert sum(1 for v in versions if v["status"] == VERSION_STATUS_ACTIVE) == 1


@pytest.mark.integration
class TestIncrementalFaults:
    def test_pg_write_failure_rolls_back_swap(self, pipeline, test_db, monkeypatch):
        pipeline.full_build(reason="v1")
        version_id = _active_id(test_db)
        before = pg_store.search_children(_session_of(test_db), version_id, [0.3] * 1024, top_k=50)
        assert before

        target = Path(DATA_DIR) / "生产环境发布与回滚操作规范.md"
        # pretend the file changed so the swap path (not the skip path) runs
        monkeypatch.setattr(
            pipeline.processor,
            "fingerprint",
            lambda fp: {"file_hash": "injected-new-hash", "file_size": 1, "modified_at": "now"},
        )

        def broken_write(session, vid, record, prepared):
            raise RuntimeError("injected PG write failure")

        pipeline._write_prepared = broken_write  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="PG write failure"):
            pipeline.add_or_update_file(target)

        after = pg_store.search_children(_session_of(test_db), version_id, [0.3] * 1024, top_k=50)
        assert len(after) == len(before), "rollback must preserve old chunks"
        assert pg_store.validate_version(_session_of(test_db), version_id) == []

    def test_concurrent_same_document_updates_serialize(self, pipeline, test_db, monkeypatch):
        pipeline.full_build(reason="v1")
        target = Path(DATA_DIR) / "差旅与费用报销管理办法.md"
        # pretend the file changed so both threads take the swap path; the
        # second one should then find the content already swapped in → skipped
        monkeypatch.setattr(
            pipeline.processor,
            "fingerprint",
            lambda fp: {"file_hash": "injected-new-hash", "file_size": 1, "modified_at": "now"},
        )

        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def worker():
            barrier.wait()
            result = pipeline.add_or_update_file(target)
            outcomes.append(result.get("status", ""))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # RLock serializes: first thread indexes, second sees unchanged content
        assert sorted(outcomes) == ["indexed", "skipped"], f"got {outcomes}"
        assert pg_store.validate_version(_session_of(test_db), _active_id(test_db)) == []


@pytest.mark.integration
class TestRecovery:
    def test_recovery_after_crash_before_switch(self, pipeline, test_db):
        pipeline.full_build(reason="v1")
        first_active = _active_id(test_db)

        # simulate a process that died mid-build: building version + running task
        session = Session(bind=test_db.engine)
        orphan = pg_store.create_building_version(
            session, name="v_orphan", embedding_model="fake-embed",
            chunk_settings={}, metadata_schema_version="5",
        )
        session.commit()
        task_session = Session(bind=test_db.engine)
        pg_store.start_task(task_session, "full_rebuild", version_id=orphan.id)
        task_session.commit()

        pipeline.ensure_bootstrapped()

        session.refresh(orphan)
        assert orphan.status == VERSION_STATUS_FAILED
        assert _active_id(test_db) == first_active
        session.close()
        task_session.close()

    def test_recovery_after_crash_after_switch(self, pipeline, test_db):
        """Crash AFTER the switch: the new active version must stay active even
        though its task row is still 'running'."""
        result = pipeline.full_build(reason="v1")
        # simulate the task row never being finalized (crash after switch)
        with test_db.engine.connect() as connection:
            connection.execute(
                IndexVersion.__table__.update()
                .where(IndexVersion.id == result["version_id"])
                .values(status=VERSION_STATUS_ACTIVE, is_active=True)
            )
        stale_session = Session(bind=test_db.engine)
        # a running task attached to the now-active version
        task = pg_store.start_task(stale_session, "test_full_rebuild", version_id=result["version_id"])
        stale_session.commit()

        pg_store.recover_stale_tasks(stale_session, [])
        stale_session.commit()

        assert _active_id(test_db) == result["version_id"], "active version survives recovery"
        task_session = Session(bind=test_db.engine)
        reloaded = pg_store_start_task_guard(task_session, task.id)
        assert reloaded == "failed"
        task_session.close()
        stale_session.close()

    def test_bm25_version_snapshot_consistency_during_flip(self, pipeline, test_db):
        """A reader holding the old version id (like the BM25 cache) must keep
        reading coherent old data while the flip happens; new readers see v2."""
        pipeline.full_build(reason="v1")
        old_id = _active_id(test_db)
        old_corpus = pg_store.load_children_for_bm25(_session_of(test_db), old_id)
        assert old_corpus

        pipeline.full_build(reason="v2")
        new_id = _active_id(test_db)
        assert new_id != old_id

        # old snapshot still fully readable (retained, never pruned mid-flight)
        assert len(pg_store.load_children_for_bm25(_session_of(test_db), old_id)) == len(old_corpus)
        # active pointer now resolves to the new version
        session = Session(bind=test_db.engine)
        assert pg_store.require_active_version(session).id == new_id
        session.close()


@pytest.mark.integration
class TestVersionRetention:
    def test_prune_retires_but_keeps_active(self, pipeline, test_db):
        for index in range(4):
            pipeline.full_build(reason=f"build-{index}")
        session = Session(bind=test_db.engine)
        report = pg_store.prune_retired_versions(session, keep=2)
        session.commit()
        session.close()

        assert len(report["removed"]) == 1  # 4 builds → 3 retired, keep=2
        session = Session(bind=test_db.engine)
        remaining = pg_store.list_versions(session)
        active = pg_store.require_active_version(session)
        session.close()
        assert active.notes == "build-3"
        assert sum(1 for v in remaining if v["status"] == VERSION_STATUS_ACTIVE) == 1
        assert len(remaining) == 3  # active + 2 kept retired


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _session_of(test_db):
    return Session(bind=test_db.engine)


def _active_id(test_db) -> int:
    session = Session(bind=test_db.engine)
    try:
        return pg_store.require_active_version(session).id
    finally:
        session.close()


def _stats_for(test_db, version_id: int) -> dict:
    session = Session(bind=test_db.engine)
    try:
        return pg_store.version_stats(session, version_id)
    finally:
        session.close()


def pg_store_start_task_guard(session, task_id: int) -> str:
    from backend.db.models import IndexTask

    task = session.get(IndexTask, task_id)
    return task.status
