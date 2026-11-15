"""Rerank threshold calibration experiment (real model, real corpus).

Method:
  - positive set: on-topic questions over the knowledge base, expected source known
  - negative set: off-topic questions with NO relevant document in the corpus
  - for each query, run hybrid retrieval + CrossEncoder rerank, record top-1 rerank score
  - sweep thresholds and report recall (positives accepted) vs false-positive rate
    (negatives accepted), pick the operating point

Output: docs/PERFORMANCE_REPORT.md §3 numbers + recommended threshold.
Run: .conda-py310/python.exe tools/eval_rerank_calibration.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.rag_service import RagService

POSITIVES = [
    ("生产环境发布失败后如何回滚？", "生产环境发布与回滚操作规范"),
    ("生产环境发布前需要做哪些检查？", "生产环境发布与回滚操作规范"),
    ("核心业务系统故障时的应急响应流程是什么？", "核心业务系统故障应急响应预案"),
    ("故障发生后应该通知哪些角色？", "核心业务系统故障应急响应预案"),
    ("差旅报销需要提交哪些材料？", "差旅与费用报销管理办法"),
    ("差旅费用报销审批流程是什么？", "差旅与费用报销管理办法"),
    ("客户数据访问控制有哪些分级？", "客户数据分级与访问控制管理制度"),
    ("新员工入职培训包括哪些内容？", "澄星智能新员工入职培训手册"),
    ("客服平台上线后的运营流程是什么？", "星联智服全渠道客服平台上线与运营管理手册"),
    ("XX-200 智能网关有哪些主要功能？", "XX-200智能网关产品手册"),
]

NEGATIVES = [
    "今天北京的天气怎么样？",
    "周杰伦最新的专辑是什么？",
    "1 + 1 等于几？",
    "帮我写一首关于大海的诗",
    "英超最新积分榜是多少？",
    "美元兑人民币汇率现在是多少？",
    "如何用 Python 快速排序一个数组？",
    "苹果公司现任 CEO 是谁？",
]


def main() -> None:
    service = RagService()  # reuses container DB via localhost; real corpus
    hybrid = service.hybrid_search_service
    reranker = service.rerank_service

    def top1_score(question: str) -> tuple[float, str]:
        candidates = hybrid.search(question, top_k=10, vector_top_k=10, keyword_top_k=10, rrf_k=60)
        if not candidates:
            return -99.0, ""
        ranked = reranker.rerank(question, candidates, top_k=1)
        if not ranked:
            return -99.0, ""
        return float(ranked[0]["rerank_score"]), str(ranked[0].get("file_name", ""))

    started = time.perf_counter()
    positive_scores = []
    for question, expected in POSITIVES:
        score, source = top1_score(question)
        positive_scores.append(score)
        hit = expected in source
        print(f"POS score={score:+.4f} hit={hit}  {question}")

    negative_scores = []
    for question in NEGATIVES:
        score, source = top1_score(question)
        negative_scores.append(score)
        print(f"NEG score={score:+.4f} src={source}  {question}")

    elapsed = time.perf_counter() - started

    print("\n== distribution ==")
    print(f"positives n={len(positive_scores)} mean={statistics.mean(positive_scores):.3f} "
          f"min={min(positive_scores):.3f} p25={statistics.quantiles(positive_scores, n=4)[0]:.3f}")
    if negative_scores:
        print(f"negatives n={len(negative_scores)} mean={statistics.mean(negative_scores):.3f} "
              f"max={max(negative_scores):.3f}")

    print("\n== threshold sweep ==")
    print(f"{'thr':>6} {'recall':>7} {'fpr':>7}")
    best = None
    for thr in [i / 4 for i in range(-4, 25)]:
        recall = sum(1 for s in positive_scores if s >= thr) / len(positive_scores)
        fpr = (sum(1 for s in negative_scores if s >= thr) / len(negative_scores)) if negative_scores else 0.0
        print(f"{thr:>6.2f} {recall:>7.0%} {fpr:>7.0%}")
        if best is None or (recall - fpr) > (best[1] - best[2]):
            best = (thr, recall, fpr)
    print(f"\nrecommended threshold: {best[0]:.2f} (recall={best[1]:.0%}, fpr={best[2]:.0%})")

    report = {
        "positive_scores": positive_scores,
        "negative_scores": negative_scores,
        "recommended_threshold": best[0],
        "duration_s": round(elapsed, 1),
    }
    out = Path("tests/golden/rerank_calibration.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
