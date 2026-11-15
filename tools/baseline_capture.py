"""Capture retrieval regression baseline against the CURRENT stack.

Run inside the project's working environment:
    .conda-py310/python.exe tools/baseline_capture.py --label pgvector_v2
    .conda-py310/python.exe tools/baseline_capture.py --compare tests/golden/baseline_retrieval.json

Writes tests/golden/<label>_retrieval.json with per-case results and metric
summary for all four retrieval endpoints. No LLM calls are made.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from fastapi.testclient import TestClient

from backend.main import app

ENDPOINTS = {
    "vector": ("/search", 5),
    "keyword": ("/keyword-search", 5),
    "hybrid": ("/hybrid-search", 10),
    "rerank": ("/rerank-search", 5),
}

CASES = [
    ("生产环境发布失败后如何回滚？", "生产环境发布与回滚操作规范"),
    ("生产环境发布前需要做哪些检查？", "生产环境发布与回滚操作规范"),
    ("核心业务系统故障时的应急响应流程是什么？", "核心业务系统故障应急响应预案"),
    ("故障发生后应该通知哪些角色？", "核心业务系统故障应急响应预案"),
    ("核心业务系统故障时应该怎么响应？", "核心业务系统故障应急响应预案"),
    ("差旅报销需要提交哪些材料？", "差旅与费用报销管理办法"),
    ("差旅报销需要哪些材料？", "差旅与费用报销管理办法"),
    ("差旅费用报销审批流程是什么？", "差旅与费用报销管理办法"),
    ("客户数据访问控制有哪些分级？", "客户数据分级与访问控制管理制度"),
    ("新员工入职培训包括哪些内容？", "澄星智能新员工入职培训手册"),
    ("客服平台上线后的运营流程是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
    ("PARENT-CHILD 切块配置原则是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
    ("XX-200 智能网关有哪些主要功能？", "XX-200智能网关产品手册"),
]


def item_source(item: dict) -> str:
    return str(item.get("source") or item.get("file_name") or "")


def run_case(client: httpx.Client, path: str, top_k: int, question: str) -> list[dict]:
    response = client.post(path, json={"query": question, "top_k": top_k})
    response.raise_for_status()
    return response.json().get("results", [])


def evaluate(client: httpx.Client) -> dict:
    report: dict = {"endpoints": {}}
    for endpoint_name, (path, top_k) in ENDPOINTS.items():
        rows = []
        started = time.perf_counter()
        for question, expected in CASES:
            results = run_case(client, path, top_k, question)
            hits = [i + 1 for i, item in enumerate(results) if expected in item_source(item)]
            rows.append(
                {
                    "question": question,
                    "expected_source": expected,
                    "hit": bool(hits),
                    "best_rank": hits[0] if hits else None,
                    "returned": len(results),
                    "top3_sources": [item_source(item) for item in results[:3]],
                }
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        hit_count = sum(1 for row in rows if row["hit"])
        ranks = [row["best_rank"] for row in rows if row["best_rank"]]
        report["endpoints"][endpoint_name] = {
            "path": path,
            "top_k": top_k,
            "cases": rows,
            "metrics": {
                "hit_count": hit_count,
                "total_cases": len(rows),
                "hit_rate": round(hit_count / len(rows), 4),
                "mean_best_rank_hits_only": round(sum(ranks) / len(ranks), 4) if ranks else None,
            },
            "total_duration_ms": elapsed,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture/compare retrieval regression metrics.")
    parser.add_argument("--label", default="chroma_baseline", help="stack label used in the golden filename")
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="path to a previous golden file; prints per-endpoint deltas after capture",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    with TestClient(app) as client:
        health = client.get("/health")
        health.raise_for_status()
        info = client.get("/info").json()

        report = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "stack": args.label,
            "app_info": {
                "document_count": info.get("document_count"),
                "parent_count": info.get("parent_count"),
                "chunk_count": info.get("chunk_count"),
                "vector_count": info.get("vector_count"),
                "active_version": (info.get("active_version") or {}).get("name", "")
                if isinstance(info.get("active_version"), dict)
                else "",
            },
            "results": evaluate(client),
        }
    report["capture_duration_ms"] = int((time.perf_counter() - started) * 1000)

    out_dir = PROJECT_ROOT / "tests" / "golden"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{args.label}_retrieval.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"baseline saved: {out_file}")
    print(
        f"app info: docs={report['app_info']['document_count']} parents={report['app_info']['parent_count']}"
        f" chunks={report['app_info']['chunk_count']} version={report['app_info']['active_version'] or '-'}"
    )
    for name, data in report["results"]["endpoints"].items():
        metrics = data["metrics"]
        print(
            f"{name:8s} hit {metrics['hit_count']}/{metrics['total_cases']}"
            f" ({metrics['hit_rate']:.0%})  mean_rank={metrics['mean_best_rank_hits_only']}  {data['total_duration_ms']}ms"
        )

    if args.compare:
        compare_path = Path(args.compare)
        if compare_path.exists():
            previous = json.loads(compare_path.read_text(encoding="utf-8"))
            print(f"\n== delta vs {compare_path.name} ({previous.get('stack')}) ==")
            for name, data in report["results"]["endpoints"].items():
                old = previous["results"]["endpoints"].get(name, {}).get("metrics", {})
                now = data["metrics"]
                print(
                    f"{name:8s} hit {old.get('hit_count')}->{now['hit_count']}"
                    f"  mean_rank {old.get('mean_best_rank_hits_only')}->{now['mean_best_rank_hits_only']}"
                )
            # per-case regression detection
            for name, data in report["results"]["endpoints"].items():
                old_cases = {
                    case["question"]: case
                    for case in previous["results"]["endpoints"].get(name, {}).get("cases", [])
                }
                for case in data["cases"]:
                    old_case = old_cases.get(case["question"])
                    if old_case and old_case["hit"] and not case["hit"]:
                        print(f"REGRESSION [{name}] {case['question']} hit -> miss")
        else:
            print(f"compare file not found: {compare_path}")


if __name__ == "__main__":
    main()
