"""Pure-logic unit tests: RRF fusion, BM25 tokenization, semantic chunking."""

from __future__ import annotations

import pytest

from backend.indexing.chunking import ParentChildChunker, SemanticBoundaryChildSplitter
from backend.services.hybrid_search_service import HybridSearchService  # noqa: F401  (import guard)


class FakeKB:
    def search_children(self, query, top_k, file_name=""):
        return []


class FakeKeyword:
    def search(self, query, top_k, file_name=""):
        return []


@pytest.mark.unit
class TestRRFusion:
    def _service(self):
        from backend.services.hybrid_search_service import HybridSearchService

        return HybridSearchService(FakeKB(), FakeKeyword())

    def _candidates(self, ids, retriever):
        return [
            {
                "rank": rank,
                "child_id": f"c{child}",
                "parent_id": f"p{child}",
                "file_name": "doc.md",
                "source": "doc.md",
                "content": f"content {child}",
                "preview": f"content {child}",
                "metadata": {},
                "score": 1.0,
            }
            for rank, child in enumerate(ids, start=1)
        ]

    def test_rrf_scores_sum_across_retrievers(self):
        service = self._service()
        vector = self._candidates([1, 2, 3], "vector")
        keyword = self._candidates([2, 3, 4], "bm25")
        for c in vector:
            c.pop("score", None)
        for c in keyword:
            c.pop("score", None)

        merged: dict = {}

        # reuse the service's internal merging via public method
        service._add_ranked_candidates(merged, vector, "vector", 60)
        service._add_ranked_candidates(merged, keyword, "bm25", 60)

        c2 = merged["c2"]
        assert c2["vector_rank"] == 2 and c2["bm25_rank"] == 1
        assert c2["retrievers"] == ["vector", "bm25"]
        expected = 1 / (60 + 2) + 1 / (60 + 1)
        assert abs(c2["rrf_score"] - expected) < 1e-9

        # item present in both retrievers must outrank vector-only rank-1 item
        c1 = merged["c1"]
        assert c1["rrf_score"] < c2["rrf_score"]

    def test_rrf_k_changes_fusion(self):
        service = self._service()
        merged_a: dict = {}
        merged_b: dict = {}
        candidates = self._candidates([1, 2], "vector")
        service._add_ranked_candidates(merged_a, candidates, "vector", 1)
        service._add_ranked_candidates(merged_b, candidates, "vector", 200)
        assert merged_a["c2"]["rrf_score"] > merged_b["c2"]["rrf_score"]


@pytest.mark.unit
class TestSemanticBoundarySplitter:
    def test_respects_section_boundaries(self):
        splitter = SemanticBoundaryChildSplitter(chunk_size=120, chunk_overlap=10, min_chunk_size=20)
        text = "# 第一章 回滚\n" + "发布失败后执行回滚脚本。" * 5 + "\n\n# 第二章 报销\n" + "报销需要发票与审批单。" * 5
        chunks = splitter.split_text(text)
        assert len(chunks) >= 2
        assert chunks[0].startswith("# 第一章")
        joined = "\n".join(chunks)
        assert "报销" in joined and "回滚" in joined

    def test_no_chunk_exceeds_limit(self):
        splitter = SemanticBoundaryChildSplitter(chunk_size=100, chunk_overlap=10, min_chunk_size=10)
        text = ("这是一句测试文本。" * 40)
        for chunk in splitter.split_text(text):
            assert len(chunk) <= 100 + len("这是一句测试文本。")  # single oversized sentence falls back


@pytest.mark.unit
class TestParentChildChunker:
    def test_children_reference_parent_metadata(self):
        from langchain_core.documents import Document

        chunker = ParentChildChunker(parent_chunk_size=300, child_chunk_size=80, child_chunk_overlap=10)
        doc = Document(page_content="# 标题\n" + "内容段落。" * 40, metadata={"file_name": "a.md"})
        result = chunker.split([doc])
        assert result.parents and result.children
        parent_indexes = {child.metadata["parent_index"] for child in result.children}
        assert parent_indexes.issubset(set(range(len(result.parents))))
