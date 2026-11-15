"""Batch upload tests: multi-file save + per-file isolation."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def _md_file(name: str, content: str):
    return ("files", (name, io.BytesIO(content.encode("utf-8")), "text/markdown"))


@pytest.mark.integration
class TestBatchUpload:
    def test_batch_indexes_all_and_reports(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 0)
        with TestClient(app) as client:
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

        # real index consistency: documents listed with chunks
        listing = client.get("/documents").json()
        for name in ("batch_a.md", "batch_b.md", "batch_c.md"):
            doc = next(d for d in listing["documents"] if d["file_name"] == name)
            assert doc["chunk_count"] > 0 and doc["status"] == "indexed"

    def test_bad_file_does_not_abort_batch(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 0)
        with TestClient(app) as client:
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

    def test_batch_requires_admin(self):
        with TestClient(app) as client:
            files = [_md_file("batch_x.md", "x" * 100)]
            response = client.post("/documents/upload-batch", files=files)
        assert response.status_code in {401, 429}
