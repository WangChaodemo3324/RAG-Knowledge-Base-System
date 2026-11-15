"""Batch upload tests: multi-file save + per-file isolation."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(autouse=True)
def fake_embedding_for_ci(monkeypatch):
    """CI 无 BGE-M3 缓存：嵌入走确定性假向量（模型边界已由单元测试覆盖）。"""

    class _FakeEmbedding:
        model_name = "fake-embed"

        def embed_documents(self, texts):
            return [[0.1] * 1024 for _ in texts]

        def embed_query(self, text):
            return [0.1] * 1024

    monkeypatch.setattr("backend.indexing.embedding_provider.get_embedding", lambda: _FakeEmbedding())
    monkeypatch.setattr("backend.knowledge.knowledge_base.get_embedding", lambda: _FakeEmbedding())



def _md_file(name: str, content: str):
    return ("files", (name, io.BytesIO(content.encode("utf-8")), "text/markdown"))


@pytest.mark.integration
class TestBatchUpload:
    def test_batch_indexes_all_and_reports(self, monkeypatch):
        import uuid

        marker = uuid.uuid4().hex[:8]
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 0)
        uploaded: list[str] = []
        with TestClient(app) as client:
            try:
                files = [
                    _md_file("batch_a.md", "# 批量测试 A\n\n" + "批量上传内容 A。" * 30),
                    _md_file("batch_b.md", "# 批量测试 B\n\n" + "批量上传内容 B。" * 30),
                    _md_file("batch_c.md", "# 批量测试 C\n\n" + "批量上传内容 C。" * 30),
                ]
                response = client.post(
                    "/documents/upload-batch",
                    files=files,
                    headers={"X-API-Key": "test-admin-key-2026"},
                )
                assert response.status_code == 200
                body = response.json()
                assert body["summary"] == {"indexed": 3, "skipped": 0, "failed": 0}
                names = [r["filename"] for r in body["results"]]
                assert {"batch_a.md", "batch_b.md", "batch_c.md"} <= set(names)
                uploaded = names

                # real index consistency: documents listed with chunks
                listing = client.get("/documents").json()
                for name in ("batch_a.md", "batch_b.md", "batch_c.md"):
                    doc = next(d for d in listing["documents"] if d["file_name"] == name)
                    assert doc["chunk_count"] > 0 and doc["status"] == "indexed"
            finally:
                # restore the real knowledge base to its baseline; cleanup
                # failures must fail the test loudly (no silent residue)
                for name in uploaded:
                    del_response = client.delete(
                        f"/documents/{name}",
                        headers={"X-API-Key": "test-admin-key-2026"},
                    )
                    assert del_response.status_code == 200, (
                        f"cleanup delete failed for {name}: {del_response.status_code} {del_response.text[:200]}"
                    )

    def test_bad_file_does_not_abort_batch(self, monkeypatch):
        import uuid

        marker = uuid.uuid4().hex[:8]
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 0)
        uploaded: list[str] = []
        with TestClient(app) as client:
            try:
                files = [
                    _md_file("batch_ok.md", "# 批量测试 OK\n\n" + "合法内容。" * 30),
                    ("files", ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")),
                ]
                response = client.post(
                    "/documents/upload-batch",
                    files=files,
                    headers={"X-API-Key": "test-admin-key-2026"},
                )
                assert response.status_code == 200
                body = response.json()
                statuses = {r["filename"]: r["status"] for r in body["results"]}
                assert statuses["virus.exe"] == "rejected"
                assert statuses["batch_ok.md"] == "indexed"
                assert body["summary"]["failed"] == 1 and body["summary"]["indexed"] == 1
                uploaded = ["batch_ok.md"]
            finally:
                for name in uploaded:
                    del_response = client.delete(
                        f"/documents/{name}",
                        headers={"X-API-Key": "test-admin-key-2026"},
                    )
                    assert del_response.status_code == 200, (
                        f"cleanup delete failed for {name}: {del_response.status_code} {del_response.text[:200]}"
                    )

    def test_batch_requires_admin(self):
        with TestClient(app) as client:
            files = [_md_file("batch_x.md", "x" * 100)]
            response = client.post("/documents/upload-batch", files=files)
        assert response.status_code in {401, 429}
