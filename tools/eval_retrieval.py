"""Retrieval quality metrics over the golden case set — REAL retrieval runs.

Categories: 精确 / 跨段落 / 多文档 / 无答案.
Metrics per endpoint: Hit Rate, MRR, NDCG@5, mean latency; per-category
breakdown on the rerank endpoint (the production retrieval path); the 无答案
category checks correct rejection (no results returned).
Run: .conda-py310/python.exe tools/eval_retrieval.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: F401  (kept for parity with other eval tools)
from fastapi.testclient import TestClient

from backend.main import app

# (category, question, expected_sources) — 无答案: expected_sources 为空列表
CASES = [
    # 精确查询
    ("精确", "生产环境发布失败后如何回滚？", ["生产环境发布与回滚操作规范"]),
    ("精确", "差旅报销需要提交哪些材料？", ["差旅与费用报销管理办法"]),
    ("精确", "客户数据访问控制有哪些分级？", ["客户数据分级与访问控制管理制度"]),
    ("精确", "XX-200 智能网关有哪些主要功能？", ["XX-200智能网关产品手册"]),
    # 跨段落查询（答案横跨同文档多个章节）
    ("跨段落", "生产环境发布的完整流程包括哪些阶段和检查项？", ["生产环境发布与回滚操作规范"]),
    ("跨段落", "新员工入职培训包括哪些内容？考核要求是什么？", ["澄星智能新员工入职培训手册"]),
    ("跨段落", "客户数据的分级标准和各级访问控制要求是什么？", ["客户数据分级与访问控制管理制度"]),
    # 多文档查询（任一期望来源命中即算）
    ("多文档", "哪些制度提到了审批流程？", ["差旅与费用报销管理办法", "生产环境发布与回滚操作规范"]),
    ("多文档", "故障和回滚分别应该怎么做？", ["核心业务系统故障应急响应预案", "生产环境发布与回滚操作规范"]),
    # 无答案（语料中无答案，期望系统返回空/低分被拒）
    ("无答案", "量子计算机的运算速度有多快？", []),
    ("无答案", "2026 年世界杯的举办地在哪里？", []),
    ("无答案", "怎样在火星上种土豆？", []),
]

ENDPOINTS = {
    "vector": ("/search", 5),
    "keyword": ("/keyword-search", 5),
    "hybrid": ("/hybrid-search", 10),
    "rerank": ("/rerank-search", 5),
}


def source_list(results: list[dict]) -> list[str]:
    return [
        str(item.get("source") or item.get("file_name") or "")
        for item in results
    ]


def evaluate(category: str, sources: list[str], expected_list: list[str], top_k: int, latency_ms: int) -> dict:
    """expected_list 为空 = 无答案场景：期望 sources 为空（正确拒答）。"""
    if not expected_list:
        return {
            "category": category,
            "hit": len(sources) == 0,  # 正确行为 = 未返回高相关内容
            "rank": None,
            "latency_ms": latency_ms,
            "ndcg": 0.0,
            "rejected": len(sources) == 0,
        }
    hits = [
        rank
        for rank, src in enumerate(sources[:top_k], start=1)
        if any(expected in src for expected in expected_list)
    ]
    dcg = sum(1.0 / math.log2(r + 1) for r in hits)
    ideal = list(range(1, len(hits) + 1))
    idcg = sum(1.0 / math.log2(r + 1) for r in ideal)
    return {
        "category": category,
        "hit": bool(hits),
        "rank": hits[0] if hits else None,
        "latency_ms": latency_ms,
        "ndcg": dcg / idcg if idcg else 0.0,
        "rejected": False,
    }


def main() -> None:
    with TestClient(app) as client:
        rows: dict[str, list[dict]] = {name: [] for name in ENDPOINTS}
        for endpoint, (path, top_k) in ENDPOINTS.items():
            for category, question, expected_list in CASES:
                started = time.perf_counter()
                response = client.post(path, json={"query": question, "top_k": top_k})
                latency = int((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                sources = source_list(response.json().get("results", []))
                m = evaluate(category, sources, expected_list, top_k, latency)
                m["question"] = question
                rows[endpoint].append(m)

        print(f"== retrieval metrics ({len(CASES)} cases, real runs) ==\n")
        print(f"{'endpoint':10s} {'HitRate':>8s} {'MRR':>6s} {'NDCG@5':>7s} {'mean_ms':>8s}")
        summary: dict[str, dict] = {}
        for endpoint, data in rows.items():
            hit_rate = sum(1 for m in data if m["hit"]) / len(data)
            ranked = [1.0 / m["rank"] for m in data if m["rank"]]
            mrr = statistics.mean(ranked) if ranked else 0.0
            ndcg = statistics.mean(m["ndcg"] for m in data)
            mean_ms = statistics.mean(m["latency_ms"] for m in data)
            summary[endpoint] = {
                "hit_rate": round(hit_rate, 4),
                "mrr": round(mrr, 4),
                "ndcg5": round(ndcg, 4),
                "mean_ms": mean_ms,
            }
            print(f"{endpoint:10s} {hit_rate:>8.0%} {mrr:>6.3f} {ndcg:>7.3f} {mean_ms:>8.0f}")

        # 按类别细分（rerank 端点 = 生产检索链路）
        print("\n== per-category (rerank endpoint) ==")
        category_report: dict[str, dict] = {}
        rr = rows["rerank"]
        for category in sorted({m["category"] for m in rr}):
            subset = [m for m in rr if m["category"] == category]
            if category == "无答案":
                rejects = sum(1 for m in subset if m["rejected"])
                category_report[category] = {"correct_rejects": rejects, "total": len(subset)}
                print(f"{category}: {rejects}/{len(subset)} 正确拒答（返回空）")
            else:
                hit = sum(1 for m in subset if m["hit"])
                category_report[category] = {"hits": hit, "total": len(subset)}
                print(f"{category}: {hit}/{len(subset)} 命中")

        out = Path("tests/golden/retrieval_metrics.json")
        out.write_text(
            json.dumps({"summary": summary, "categories": category_report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
