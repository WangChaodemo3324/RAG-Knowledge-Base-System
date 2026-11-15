"""Pure-logic unit tests: routing subsystem, memory store, API key auth."""

from __future__ import annotations

import pytest

from backend.services.memory_store import ShortTermMemory
from backend.services.routing.answer_route_service import AnswerRouteService
from backend.services.routing.evidence_checker import EvidenceChecker
from backend.services.routing.feature_extractor import QueryFeatureExtractor


@pytest.mark.unit
class TestFeatureExtractor:
    def setup_method(self):
        self.extractor = QueryFeatureExtractor()

    def test_explicit_web(self):
        assert self.extractor.extract("帮我搜一下今天的新闻").explicit_web is True

    def test_time_sensitive(self):
        assert self.extractor.extract("现在最新版本是什么").has_current_time_need is True

    def test_private_internal_hint(self):
        assert self.extractor.extract("公司的年假制度是怎样的").has_private_internal_hint is True

    def test_math_like(self):
        assert self.extractor.extract("3 + 5 = ?").is_math_like is True

    def test_vague_reference(self):
        assert self.extractor.extract("这个怎么弄").is_vague_reference is True
        assert self.extractor.extract("这个具体的生产环境发布回滚流程怎么操作？").is_vague_reference is False


@pytest.mark.unit
class TestEvidenceChecker:
    def test_empty_results(self):
        checker = EvidenceChecker()
        assert checker.check([]).sufficient is False
        assert checker.check(None).sufficient is False

    def test_short_content_rejected(self):
        checker = EvidenceChecker(min_content_length=80)
        decision = checker.check([{"content": "太短", "rerank_score": 9.9}])
        assert decision.sufficient is False

    def test_calibrated_threshold_separates_distributions(self):
        """0.25 calibrated on real rerank score data (tests/golden/rerank_calibration.json):
        positives min 0.462 / negatives max 0.082 — margin symmetric."""
        checker = EvidenceChecker(score_threshold=0.25)
        assert checker.check([{"content": "x" * 200, "rerank_score": 0.462}]).sufficient is True
        assert checker.check([{"content": "x" * 200, "rerank_score": 0.082}]).sufficient is False

    def test_fallback_counts_when_no_scores(self):
        checker = EvidenceChecker()
        decision = checker.check([{"content": "x" * 100}, {"content": "y" * 100}])
        assert decision.sufficient is True
        decision2 = checker.check([{"content": "x" * 100}])
        assert decision2.sufficient is False


@pytest.mark.unit
class TestRouteService:
    def setup_method(self):
        self.service = AnswerRouteService(config={"api_key": ""})

    def test_document_mode_forces_kb(self):
        decision = self.service.route_question("今天天气如何", "DOCUMENT")
        assert decision["route"] == "KB_ONLY"
        assert "强制" in decision["route_reason"]

    def test_open_chat_web_explicit(self):
        decision = self.service.route_question("帮我搜一下最新的新闻", "OPEN_CHAT")
        assert decision["route"] == "WEB_ONLY"

    def test_auto_direct_llm_for_math(self):
        decision = self.service.route_question("3 + 5 = ?", "AUTO_MODE")
        assert decision["route"] == "DIRECT_LLM"

    def test_auto_kb_for_company_domain(self):
        decision = self.service.route_question("差旅报销审批流程是什么", "AUTO_MODE")
        assert decision["route"] == "KB_ONLY"

    def test_auto_clarify_for_vague(self):
        decision = self.service.route_question("这个怎么弄", "AUTO_MODE")
        assert decision["route"] == "CLARIFY"

    def test_auto_private_internal_no_evidence(self):
        """私有内部问题 + 证据不足 → 拒绝联网编造（P1 设计验证）"""
        decision = self.service.route_question("公司的审批权限流程是什么", "AUTO_MODE", kb_results=[])
        assert decision["route"] == "NO_EVIDENCE"
        assert decision["route_router"] == "evidence_checker"


@pytest.mark.unit
class TestMemoryStore:
    def test_add_and_window(self):
        memory = ShortTermMemory(max_turns=5)
        for i in range(7):
            memory.add_turn("s1", f"问{i}", f"答{i}", "chat")
        assert memory.count("s1") == 5
        turns = memory.get_turns("s1", 2)
        assert [t["question"] for t in turns] == ["问5", "问6"]

    def test_long_answers_truncated(self):
        memory = ShortTermMemory()
        memory.add_turn("s", "q" * 700, "a" * 2000, "chat")
        turn = memory.get_turns("s", 1)[0]
        assert len(turn["question"]) == 600 and len(turn["answer"]) == 1200

    def test_clear(self):
        memory = ShortTermMemory()
        memory.add_turn("s2", "q", "a", "chat")
        result = memory.clear("s2")
        assert result["removed_turns"] == 1
        assert memory.count("s2") == 0

    def test_sessions_isolated(self):
        memory = ShortTermMemory()
        memory.add_turn("a", "q1", "x", "chat")
        memory.add_turn("b", "q2", "y", "chat")
        assert memory.count("a") == 1 and memory.count("b") == 1


@pytest.mark.unit
class TestAdminAuth:
    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_auth_disabled_when_key_unset(self, monkeypatch):
        import backend.core.auth as auth_module

        monkeypatch.setattr(auth_module, "ADMIN_API_KEY", "")
        self._run(auth_module.require_admin(x_api_key=""))  # must not raise

    def test_auth_rejects_wrong_key(self, monkeypatch):
        import backend.core.auth as auth_module
        import fastapi

        monkeypatch.setattr(auth_module, "ADMIN_API_KEY", "secret-key")
        with pytest.raises(fastapi.HTTPException) as exc_info:
            self._run(auth_module.require_admin(x_api_key="wrong"))
        assert exc_info.value.status_code == 401

    def test_auth_accepts_valid_key(self, monkeypatch):
        import backend.core.auth as auth_module

        monkeypatch.setattr(auth_module, "ADMIN_API_KEY", "secret-key")
        self._run(auth_module.require_admin(x_api_key="secret-key"))  # must not raise
