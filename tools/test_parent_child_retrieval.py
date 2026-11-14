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
    SearchCase("生产环境发布前需要做哪些检查？", "生产环境发布与回滚操作规范"),
    SearchCase("核心业务系统故障时的应急响应流程是什么？", "核心业务系统故障应急响应预案"),
    SearchCase("故障发生后应该通知哪些角色？", "核心业务系统故障应急响应预案"),
    SearchCase("差旅报销需要提交哪些材料？", "差旅与费用报销管理办法"),
    SearchCase("差旅费用报销审批流程是什么？", "差旅与费用报销管理办法"),
    SearchCase("客户数据访问控制有哪些分级？", "客户数据分级与访问控制管理制度"),
    SearchCase("新员工入职培训包括哪些内容？", "澄星智能新员工入职培训手册"),
    SearchCase("客服平台上线后的运营流程是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
    SearchCase("XX-200 智能网关有哪些主要功能？", "XX-200智能网关产品手册"),
]


def fetch_info(base_url: str) -> dict[str, Any]:
    response = requests.get(f"{base_url}/info", timeout=30)
    response.raise_for_status()
    return response.json()


def search(base_url: str, question: str, top_k: int) -> list[dict[str, Any]]:
    response = requests.post(f"{base_url}/search", json={"query": question, "top_k": top_k}, timeout=30)
    response.raise_for_status()
    return response.json()["results"]


def compact(text: str, limit: int = 56) -> str:
    one_line = " ".join(str(text).split())
    return one_line[:limit] + ("..." if len(one_line) > limit else "")


def evaluate_case(base_url: str, case: SearchCase, top_k: int) -> dict[str, Any]:
    results = search(base_url, case.question, top_k)
    expected_hits = [item for item in results if case.expected_source in item.get("source", "")]
    selected = expected_hits[0] if expected_hits else (results[0] if results else {})
    metadata = selected.get("metadata", {}) or {}
    child_preview = metadata.get("matched_child_preview", "") or ""
    parent_content = selected.get("content", "") or ""
    return {
        "question": case.question,
        "expected_source": case.expected_source,
        "expected_hit": bool(expected_hits),
        "rank": results.index(expected_hits[0]) + 1 if expected_hits else "",
        "top_source": results[0].get("source", "") if results else "",
        "used_source": selected.get("source", ""),
        "retrieval_level": selected.get("retrieval_level", ""),
        "parent_id": selected.get("parent_id", ""),
        "child_id": selected.get("matched_child_id", ""),
        "parent_len": len(parent_content),
        "child_preview_len": len(child_preview),
        "child_preview": compact(child_preview),
        "parent_preview": compact(parent_content),
    }


def print_info(info: dict[str, Any]) -> None:
    print("== Offline Index ==")
    print(f"files: {len(info.get('data_files', []))}")
    print(f"documents: {info.get('document_count')}")
    print(f"parents: {info.get('parent_count')}")
    print(f"parent_store: {info.get('parent_store_count')}")
    print(f"child_vectors: {info.get('vector_count')}")
    print(f"chunks: {info.get('chunk_count')}")
    print()


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = ["#", "hit", "rank", "level", "parent", "child", "source", "question"]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for index, row in enumerate(rows, 1):
        values = [
            str(index),
            "Y" if row["expected_hit"] else "N",
            str(row["rank"]),
            row["retrieval_level"],
            "Y" if row["parent_id"] else "N",
            "Y" if row["child_id"] else "N",
            row["used_source"],
            row["question"],
        ]
        print("| " + " | ".join(values) + " |")
    print()


def print_details(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows, 1):
        print(f"## {index}. {row['question']}")
        print(f"expected: {row['expected_source']}")
        print(f"used: {row['used_source']} rank={row['rank'] or '-'} hit={row['expected_hit']}")
        print(f"level: {row['retrieval_level']} parent_id={row['parent_id']} child_id={row['child_id']}")
        print(f"parent_len={row['parent_len']} child_preview_len={row['child_preview_len']}")
        print(f"child: {row['child_preview']}")
        print(f"parent: {row['parent_preview']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test parent-child retrieval quality.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    info = fetch_info(args.base_url)
    rows = [evaluate_case(args.base_url, case, args.top_k) for case in CASES]
    print_info(info)
    print_table(rows)

    expected_hits = sum(1 for row in rows if row["expected_hit"])
    parent_hits = sum(1 for row in rows if row["retrieval_level"] == "parent")
    child_ids = sum(1 for row in rows if row["child_id"])
    print("== Summary ==")
    print(f"expected source hit: {expected_hits}/{len(rows)}")
    print(f"returned parent: {parent_hits}/{len(rows)}")
    print(f"has matched child id: {child_ids}/{len(rows)}")
    print()

    if args.details:
        print_details(rows)


if __name__ == "__main__":
    main()
