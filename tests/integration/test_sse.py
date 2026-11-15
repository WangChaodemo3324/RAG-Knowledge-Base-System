"""SSE streaming tests: real retrieval + mocked streaming LLM, plus the
client-disconnect (GeneratorExit) semantics."""

from __future__ import annotations

import json

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

from backend.services.memory_store import ShortTermMemory
from backend.services.qa_service import QAService


class FakeStreamLLM:
    """Stands in for ChatOpenAI.stream()."""

    def __init__(self, tokens):
        self._tokens = tokens

    def stream(self, messages):
        for token in self._tokens:
            yield type("Chunk", (), {"content": token})()


def parse_sse(raw: str) -> list[dict]:
    events = []
    for block in raw.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                events.append(json.loads(line[len("data: "):]))
    return events


@pytest.mark.integration
class TestSSEEndpoint:
    def test_stream_events_shape(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.qa_service.build_llm",
            lambda *args, **kwargs: FakeStreamLLM(["这是", "流式", "答案"]),
        )
        with TestClient(app) as client:
            response = client.post(
                "/chat/stream",
                json={
                    "question": "生产环境发布失败后如何回滚？",
                    "top_k": 3,
                    "query_mode": "DOCUMENT",
                    "retrieval_mode": "vector",  # skip the cross-encoder load in tests
                    "file_name": "生产环境发布与回滚操作规范.md",
                    "session_id": "sse-test",
                    "use_memory": False,
                },
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text.rstrip().endswith("data: [DONE]")

        events = parse_sse(response.text)
        kinds = [event["type"] for event in events]
        assert kinds[0] == "sources" and events[0]["sources"]
        tokens = [event["text"] for event in events if event["type"] == "token"]
        assert tokens == ["这是", "流式", "答案"]
        done = [event for event in events if event["type"] == "done"][-1]
        assert done["completed"] is True and done["answer"] == "这是流式答案"

    def test_error_event_when_llm_fails_midstream(self, monkeypatch):
        class BrokenStreamLLM:
            def stream(self, messages):
                yield type("Chunk", (), {"content": "部分"})()
                raise RuntimeError("injected stream failure")

        monkeypatch.setattr(
            "backend.services.qa_service.build_llm",
            lambda *args, **kwargs: BrokenStreamLLM(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/chat/stream",
                json={"question": "差旅报销需要提交哪些材料？", "top_k": 2, "retrieval_mode": "vector", "use_memory": False},
            )
        events = parse_sse(response.text)
        errors = [event for event in events if event["type"] == "error"]
        assert errors and "中断" in errors[-1]["detail"]
        done = [event for event in events if event["type"] == "done"][-1]
        assert done["completed"] is False and "部分" in done["answer"]


class TestDisconnectSemantics:
    """Direct generator-level tests: no DB, no server — disconnect behaviour."""

    def _service(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.qa_service.build_llm",
            lambda *args, **kwargs: FakeStreamLLM(["A", "B", "C", "D"]),
        )
        return QAService(
            config={"api_key": "test", "model": "fake", "base_url": "http://localhost"},
            knowledge_base=object(),
            memory=ShortTermMemory(),
        )

    def test_client_disconnect_still_records_partial_answer(self, monkeypatch):
        service = self._service(monkeypatch)
        sources = [{"index": 1, "content": "内容"}]
        generator = service.chat_stream(
            "测试问题", use_memory=True, session_id="disc", precomputed_sources=sources
        )
        # consume sources event + two tokens, then simulate client disconnect
        sources_event = next(generator)
        assert sources_event["type"] == "sources"
        consumed = [next(generator), next(generator)]
        generator.close()  # raises GeneratorExit inside the generator

        assert consumed == [
            {"type": "token", "text": "A"},
            {"type": "token", "text": "B"},
        ]
        turns = service.memory.get_turns("disc", 1)
        assert turns and "AB" in turns[0]["answer"] and "连接中断" in turns[0]["answer"]

    def test_disconnect_without_tokens_records_nothing(self, monkeypatch):
        service = self._service(monkeypatch)
        generator = service.chat_stream(
            "空问题", use_memory=True, session_id="disc2", precomputed_sources=[{"index": 1, "content": "c"}]
        )
        next(generator)  # sources event
        generator.close()

        assert service.memory.count("disc2") == 0
