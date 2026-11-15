"""Document lifecycle tests: delete (index rows + trash), retry, listing.

Runs against throwaway databases with the fake embedding — the real knowledge
base and source files are never modified (the test copies its own fixture file).
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.indexing import pg_store
from backend.indexing.index_pipeline import DocumentNotFoundError, IndexPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILE = PROJECT_ROOT / "resource data" / "差旅与费用报销管理办法.md"


class FakeEmbedding:
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
def sandbox_dir(tmp_path):
    """Copy one real source file into an isolated data dir — the original
    resource data files are never touched."""
    target = tmp_path / "data"
    target.mkdir()
    shutil.copy(SOURCE_FILE, target / SOURCE_FILE.name)
    return target


@pytest.fixture()
def pipeline(sandbox_dir, test_db, monkeypatch):
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

    monkeypatch.setattr("backend.indexing.index_pipeline.get_embedding", lambda: FakeEmbedding())
    return IndexPipeline(sandbox_dir, embedding=FakeEmbedding(), session_factory=factory)


@pytest.mark.integration
class TestDocumentLifecycle:
    def test_list_documents_reports_source_presence(self, pipeline):
        pipeline.full_build(reason="seed")
        listing = pipeline.list_documents()
        assert listing["documents"], "documents listed"
        first = listing["documents"][0]
        assert first["source_file_exists"] is True
        assert first["chunk_count"] > 0

    def test_delete_removes_rows_moves_source_to_trash(self, pipeline, test_db):
        pipeline.full_build(reason="seed")
        before = _stats(test_db)
        file_name = SOURCE_FILE.name

        result = pipeline.delete_document(file_name)

        assert result["deleted_from_index"] is True
        assert result["source_moved_to_trash"] is True
        assert Path(result["trash_path"]).is_file(), "source file recoverable from .trash"
        assert (pipeline.processor.data_dir / file_name).is_file() is False

        after = _stats(test_db)
        assert after["document_count"] == before["document_count"] - 1
        assert after["child_count"] < before["child_count"]

        # BM25 corpus source shrinks accordingly (same query the service reloads)
        session = Session(bind=test_db.engine)
        corpus = pg_store.load_children_for_bm25(session, _active_id(test_db))
        session.close()
        assert all(item["file_name"] != file_name for item in corpus)

        with pytest.raises(DocumentNotFoundError):
            pipeline.delete_document(file_name)

    def test_retry_reindexes_deleted_document(self, pipeline, sandbox_dir):
        pipeline.full_build(reason="seed")
        file_name = SOURCE_FILE.name
        pipeline.delete_document(file_name)

        # restore the source from trash, then retry
        trash_file = sandbox_dir / ".trash" / file_name
        trash_file.replace(sandbox_dir / file_name)
        result = pipeline.retry_document(file_name)

        assert result["status"] == "indexed"
        listing = pipeline.list_documents()
        assert any(doc["file_name"] == file_name for doc in listing["documents"])

    def test_retry_missing_source_raises_404_style_error(self, pipeline):
        with pytest.raises(DocumentNotFoundError, match="源文件不存在"):
            pipeline.retry_document("不存在的文档.md")

    def test_delete_unknown_document_raises(self, pipeline):
        pipeline.full_build(reason="seed")
        with pytest.raises(DocumentNotFoundError, match="不在索引中"):
            pipeline.delete_document("ghost.md")


def _active_id(test_db) -> int:
    session = Session(bind=test_db.engine)
    try:
        return pg_store.require_active_version(session).id
    finally:
        session.close()


def _stats(test_db) -> dict:
    session = Session(bind=test_db.engine)
    try:
        return pg_store.version_stats(session, _active_id(test_db))
    finally:
        session.close()
