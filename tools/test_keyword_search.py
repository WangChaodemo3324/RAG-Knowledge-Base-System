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
    SearchCase("XX-200 智能网关有哪些主要功能？", "XX-200智能网关产品手册"),
    SearchCase("生产环境发布失败后如何回滚？", "生产环境发布与回滚操作规范"),
    SearchCase("客户数据访问控制有哪些分级？", "客户数据分级与访问控制管理制度"),
    SearchCase("差旅报销需要哪些材料？", "差旅与费用报销管理办法"),
    SearchCase("PARENT-CHILD 切块配置原则是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
]


def post_search(base_url: str, path: str, question: str, top_k: int) -> list[dict[str, Any]]:
    response = requests.post(f"{base_url}{path}", json={"query": question, "top_k": top_k}, timeout=30)
    response.raise_for_status()
    return response.json()["results"]


def source_hit(results: list[dict[str, Any]], expected: str) -> bool:
    return any(expected in str(item.get("source") or item.get("file_name") or "") for item in results)


def compact(text: str, limit: int = 70) -> str:
    one_line = " ".join(str(text).split())
    return one_line[:limit] + ("..." if len(one_line) > limit else "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare vector search and BM25 keyword search.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for case in CASES:
        vector_results = post_search(args.base_url, "/search", case.question, args.top_k)
        keyword_results = post_search(args.base_url, "/keyword-search", case.question, args.top_k)
        rows.append(
            {
                "question": case.question,
                "expected_source": case.expected_source,
                "vector_hit": source_hit(vector_results, case.expected_source),
                "keyword_hit": source_hit(keyword_results, case.expected_source),
                "vector_top": vector_results[0].get("source", "") if vector_results else "",
                "keyword_top": keyword_results[0].get("source", "") if keyword_results else "",
                "keyword_score": round(float(keyword_results[0].get("score", 0)), 3) if keyword_results else 0,
                "keyword_child_id": keyword_results[0].get("child_id", "") if keyword_results else "",
                "keyword_preview": compact(keyword_results[0].get("content", "")) if keyword_results else "",
            }
        )

    print("| # | vector | bm25 | score | vector_top | bm25_top | question |")
    print("|---|---|---|---|---|---|---|")
    for index, row in enumerate(rows, 1):
        print(
            "| "
            + " | ".join(
                [
                    str(index),
                    "Y" if row["vector_hit"] else "N",
                    "Y" if row["keyword_hit"] else "N",
                    str(row["keyword_score"]),
                    row["vector_top"],
                    row["keyword_top"],
                    row["question"],
                ]
            )
            + " |"
        )

    print()
    print(f"vector expected hit: {sum(1 for row in rows if row['vector_hit'])}/{len(rows)}")
    print(f"bm25 expected hit: {sum(1 for row in rows if row['keyword_hit'])}/{len(rows)}")

    if args.details:
        print()
        for index, row in enumerate(rows, 1):
            print(f"## {index}. {row['question']}")
            print(f"BM25 child_id: {row['keyword_child_id']}")
            print(f"BM25 preview: {row['keyword_preview']}")
            print()


if __name__ == "__main__":
    main()
