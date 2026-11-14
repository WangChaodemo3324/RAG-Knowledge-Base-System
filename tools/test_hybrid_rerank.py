from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class SearchCase:
    question: str
    expected_source: str


CASES = [
    SearchCase("生产环境发布失败后如何回滚？", "生产环境发布与回滚操作规范"),
    SearchCase("差旅报销需要提交哪些材料？", "差旅与费用报销管理办法"),
    SearchCase("客户数据访问控制有哪些分级？", "客户数据分级与访问控制管理制度"),
    SearchCase("核心业务系统故障时应该怎么响应？", "核心业务系统故障应急响应预案"),
    SearchCase("XX-200 智能网关有哪些主要功能？", "XX-200智能网关产品手册"),
]


def post(base_url: str, path: str, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    response = requests.post(f"{base_url}{path}", json=payload, timeout=timeout)
    if response.status_code >= 400:
        return {"error_status": response.status_code, "error": response.text, "results": []}
    return response.json()


def has_expected(results: list[dict[str, Any]], expected: str) -> bool:
    return any(expected in str(item.get("source") or item.get("file_name") or "") for item in results)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    top = results[0] if results else {}
    return {
        "top_source": top.get("source") or top.get("file_name") or "",
        "child_id": top.get("child_id", ""),
        "parent_id": top.get("parent_id", ""),
        "rrf_score": round(float(top.get("rrf_score") or 0), 5),
        "rerank_score": round(float(top.get("rerank_score") or 0), 5) if "rerank_score" in top else "",
        "retrievers": ",".join(top.get("retrievers") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test hybrid RRF and rerank search.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--skip-rerank", action="store_true")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    rerank_error = ""
    for case in CASES:
        hybrid_payload = {
            "query": case.question,
            "top_k": 5,
            "vector_top_k": 10,
            "keyword_top_k": 10,
            "rrf_k": 60,
        }
        hybrid = post(args.base_url, "/hybrid-search", hybrid_payload)
        hybrid_results = hybrid.get("results", [])

        rerank_results: list[dict[str, Any]] = []
        if not args.skip_rerank:
            rerank_payload = {
                "query": case.question,
                "top_k": 5,
                "vector_top_k": 10,
                "keyword_top_k": 10,
                "hybrid_top_k": 10,
                "rrf_k": 60,
            }
            rerank = post(args.base_url, "/rerank-search", rerank_payload, timeout=240)
            rerank_results = rerank.get("results", [])
            if rerank.get("error") and not rerank_error:
                rerank_error = rerank["error"]

        row = {
            "question": case.question,
            "hybrid_hit": has_expected(hybrid_results, case.expected_source),
            "rerank_hit": has_expected(rerank_results, case.expected_source) if not args.skip_rerank else "",
            "hybrid": summarize(hybrid_results),
            "rerank": summarize(rerank_results) if rerank_results else {},
        }
        rows.append(row)

    print("| # | hybrid | rerank | hybrid_top | rerank_top | question |")
    print("|---|---|---|---|---|---|")
    for index, row in enumerate(rows, 1):
        print(
            "| "
            + " | ".join(
                [
                    str(index),
                    "Y" if row["hybrid_hit"] else "N",
                    str(row["rerank_hit"]) if row["rerank_hit"] == "" else ("Y" if row["rerank_hit"] else "N"),
                    row["hybrid"].get("top_source", ""),
                    row["rerank"].get("top_source", ""),
                    row["question"],
                ]
            )
            + " |"
        )
    print()
    print(f"hybrid expected hit: {sum(1 for row in rows if row['hybrid_hit'])}/{len(rows)}")
    if not args.skip_rerank:
        print(f"rerank expected hit: {sum(1 for row in rows if row['rerank_hit'])}/{len(rows)}")
    if rerank_error:
        print()
        print("rerank error:")
        print(rerank_error[:1000])

    print()
    for index, row in enumerate(rows, 1):
        print(f"## {index}. {row['question']}")
        print(f"hybrid: {row['hybrid']}")
        if row["rerank"]:
            print(f"rerank: {row['rerank']}")
        print()


if __name__ == "__main__":
    main()
