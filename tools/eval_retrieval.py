"""Retrieval quality metrics over the golden case set — REAL retrieval runs.

Metrics per endpoint: Hit Rate, Recall@K (binary relevance on expected source),
MRR, NDCG@5, mean latency. Run: .conda-py310/python.exe tools/eval_retrieval.py
"""

from __future__ import annotations

import math
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from fastapi.testclient import TestClient

from backend.main import app

CASES = [
    ("生产环境发布失败后如何回滚？", "生产环境发布与回滚操作规范"),
    ("生产环境发布前需要做哪些检查？", "生产环境发布与回滚操作规范"),
    ("核心业务系统故障时的应急响应流程是什么？", "核心业务系统故障应急响应预案"),
    ("故障发生后应该通知哪些角色？", "核心业务系统故障应急响应预案"),
    ("差旅报销需要提交哪些材料？", "差旅与费用报销管理办法"),
    ("差旅费用报销审批流程是什么？", "差旅与费用报销管理办法"),
    ("客户数据访问控制有哪些分级？", "客户数据分级与访问控制管理制度"),
    ("新员工入职培训包括哪些内容？", "澄星智能新员工入职培训手册"),
    ("客服平台上线后的运营流程是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
    ("PARENT-CHILD 切块配置原则是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
    ("XX-200 智能网关有哪些主要功能？", "XX-200智能网关产品手册"),
    ("XX-200 网关支持哪些通信协议？", "XX-200智能网关产品手册"),
    ("客户数据泄露后第一时间要做什么？", "客户数据分级与访问控制管理制度"),
]

ENDPOINTS = {
    "vector": ("/search", 5),
    "keyword": ("/keyword-search", 5),
    "hybrid": ("/hybrid-search", 10),
    "rerank": ("/rerank-search", 5),
}


def metrics_for(ranked_sources: list[str], expected: str, k: int, latency_ms: int) -> dict:
    hits = [i + 1 for i, s in enumerate(ranked_sources[:k]) if expected in s]
    first = hits[0] if hits else None
    dcg = sum(1.0 / math.log2(r + 1) for r in hits if r <= k)
    idcg = sum(1.0 / math.log2(r + 1) for r in range(1, min(k, sum(1 for s in ranked_sources[:k] if expected in s)) + 1))
    return {
        "hit": bool(hits),
        "rank": first,
        "latency_ms": latency_ms,
        "ndcg": dcg / idcg if idcg else 0.0,
    }


def main() -> None:
    with TestClient(app) as client:
        rows: dict[str, list[dict]] = {name: [] for name in ENDPOINTS}
        for endpoint, (path, top_k) in ENDPOINTS.items():
            for question, expected in CASES:
                started = time.perf_counter()
                response = client.post(path, json={"query": question, "top_k": top_k})
                latency = int((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                sources = [
                    str(item.get("source") or item.get("file_name") or "")
                    for item in response.json().get("results", [])
                ]
                rows[endpoint].append(metrics_for(sources, expected, top_k, latency))

        print(f"== retrieval metrics ({len(CASES)} cases, real runs) ==\n")
        print(f"{'endpoint':10s} {'HitRate':>8s} {'MRR':>6s} {'NDCG@5':>7s} {'mean_ms':>8s}")
        summary = {}
        for endpoint, data in rows.items():
            hit_rate = sum(1 for m in data if m["hit"]) / len(data)
            mrr = statistics.mean(1.0 / m["rank"] for m in data if m["rank"]) if any(m["rank"] for m in data) else 0.0
            ndcg = statistics.mean(m["ndcg"] for m in data)
            mean_ms = statistics.mean(m["latency_ms"] for m in data)
            summary[endpoint] = {"hit_rate": round(hit_rate, 4), "mrr": round(mrr, 4), "ndcg5": round(ndcg, 4), "mean_ms": mean_ms}
            print(f"{endpoint:10s} {hit_rate:>8.0%} {mrr:>6.3f} {ndcg:>7.3f} {mean_ms:>8.0f}")

        out = Path("tests/golden/retrieval_metrics.json")
        out.write_text(__import__("json").dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
