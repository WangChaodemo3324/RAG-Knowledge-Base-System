"""Routing evaluation: 44 cases across 6 categories against the rule router
(LLM router disabled → deterministic), with per-category accuracy and
misroute listing. Run: .conda-py310/python.exe tools/eval_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.routing.answer_route_service import AnswerRouteService

# (question, query_mode, expected_route)
CASES = [
    # -- DOCUMENT mode: always KB (5)
    ("生产环境发布前需要做哪些检查？", "DOCUMENT", "KB_ONLY"),
    ("差旅报销的审批流程是什么？", "DOCUMENT", "KB_ONLY"),
    ("今天北京的天气怎么样？", "DOCUMENT", "KB_ONLY"),
    ("XX-200 网关怎么配置？", "DOCUMENT", "KB_ONLY"),
    ("帮我写一首诗", "DOCUMENT", "KB_ONLY"),
    # -- AUTO mode: knowledge-base questions (7)
    ("差旅报销需要提交哪些材料？", "AUTO_MODE", "KB_ONLY"),
    ("客户数据访问控制有哪些分级？", "AUTO_MODE", "KB_ONLY"),
    ("生产环境发布失败后如何回滚？", "AUTO_MODE", "KB_ONLY"),
    ("新员工入职培训包括哪些内容？", "AUTO_MODE", "KB_ONLY"),
    ("客服平台上线后的运营流程是什么？", "AUTO_MODE", "KB_ONLY"),
    ("核心业务系统故障时应该怎么响应？", "AUTO_MODE", "KB_ONLY"),
    ("XX-200 智能网关有哪些主要功能？", "AUTO_MODE", "KB_ONLY"),
    # -- AUTO mode: chat/math/instruction → direct LLM (6)
    ("你好", "AUTO_MODE", "DIRECT_LLM"),
    ("你是谁？", "AUTO_MODE", "DIRECT_LLM"),
    ("3 + 5 = ?", "AUTO_MODE", "DIRECT_LLM"),
    ("帮我写一首关于大海的诗", "AUTO_MODE", "DIRECT_LLM"),
    ("把这句话翻译成英文：大家好", "AUTO_MODE", "DIRECT_LLM"),
    ("谢谢你的帮助", "AUTO_MODE", "DIRECT_LLM"),
    # -- AUTO mode: explicit web / time-sensitive (6)
    ("帮我搜一下今天的新闻", "AUTO_MODE", "WEB_ONLY"),
    ("网上有什么热搜？", "AUTO_MODE", "WEB_ONLY"),
    ("今天北京的天气怎么样？", "AUTO_MODE", "WEB_ONLY"),
    ("现在美元兑人民币的汇率是多少？", "AUTO_MODE", "WEB_ONLY"),
    ("最新版本的 Docker Desktop 更新了什么？", "AUTO_MODE", "WEB_ONLY"),
    ("帮我查一下官网的价格", "AUTO_MODE", "WEB_ONLY"),
    # -- AUTO mode stage-1 (no KB results yet): private/internal → retrieve KB first (4)
    ("公司的年假制度是怎样的？", "AUTO_MODE", "KB_ONLY"),
    ("公司内部的薪资水平怎么样？", "AUTO_MODE", "KB_ONLY"),
    ("部门的权限审批流程找谁？", "AUTO_MODE", "KB_ONLY"),
    ("员工的差旅补贴标准是多少？", "AUTO_MODE", "KB_ONLY"),
    # -- AUTO mode stage-2 (insufficient KB evidence): refuse to fabricate (4)
    ("公司的年假制度是怎样的？", "AUTO_MODE_INSUFFICIENT", "NO_EVIDENCE"),
    ("公司内部的薪资水平怎么样？", "AUTO_MODE_INSUFFICIENT", "NO_EVIDENCE"),
    ("部门的权限审批流程找谁？", "AUTO_MODE_INSUFFICIENT", "NO_EVIDENCE"),
    ("员工的差旅补贴标准是多少？", "AUTO_MODE_INSUFFICIENT", "NO_EVIDENCE"),
    # -- AUTO mode: vague reference → CLARIFY (5)
    ("这个怎么弄", "AUTO_MODE", "CLARIFY"),
    ("那个流程是什么", "AUTO_MODE", "CLARIFY"),
    ("它怎么配置", "AUTO_MODE", "CLARIFY"),
    ("上面说的对吗", "AUTO_MODE", "CLARIFY"),
    ("这个是什么", "AUTO_MODE", "CLARIFY"),
    # -- OPEN_CHAT mode (11)
    ("帮我搜一下最新的新闻", "OPEN_CHAT", "WEB_ONLY"),
    ("今天上海天气如何", "OPEN_CHAT", "WEB_ONLY"),
    ("现在比特币价格多少", "OPEN_CHAT", "WEB_ONLY"),
    ("你好呀", "OPEN_CHAT", "DIRECT_LLM"),
    ("什么是机器学习？", "OPEN_CHAT", "DIRECT_LLM"),
    ("帮我写一封请假邮件", "OPEN_CHAT", "DIRECT_LLM"),
    ("把这段话润色一下", "OPEN_CHAT", "DIRECT_LLM"),
    ("它是什么", "OPEN_CHAT", "CLARIFY"),
    ("这个怎么做", "OPEN_CHAT", "CLARIFY"),
    ("我们公司的报销制度是什么", "OPEN_CHAT", "DIRECT_LLM"),
    ("1+1=?", "OPEN_CHAT", "DIRECT_LLM"),
]


def main() -> None:
    service = AnswerRouteService(config={"api_key": ""})  # LLM router disabled → rules only
    per_category: dict[tuple[str, str], list[bool]] = {}
    misroutes = []

    for question, mode, expected in CASES:
        if mode == "AUTO_MODE_INSUFFICIENT":
            decision = service.route_question(question, "AUTO_MODE", kb_results=[])
        else:
            decision = service.route_question(question, mode)
        got = decision["route"]
        ok = got == expected
        key = (mode, expected)
        per_category.setdefault(key, []).append(ok)
        if not ok:
            misroutes.append((question, mode, expected, got, decision["route_reason"][:60]))

    total = len(CASES)
    passed = total - len(misroutes)
    print(f"== routing evaluation: {passed}/{total} ({passed / total:.0%}) ==\n")
    for (mode, expected), results in sorted(per_category.items()):
        accuracy = sum(results) / len(results)
        print(f"{mode:14s} expect={expected:12s} {sum(results)}/{len(results)} ({accuracy:.0%})")

    if misroutes:
        print("\n== misroutes ==")
        for question, mode, expected, got, reason in misroutes:
            print(f"- [{mode}] {question!r}: expect {expected}, got {got} — {reason}")

    # gate: any regression below 90% overall is a failure
    print(f"\ngate (>=90%): {'PASS' if passed / total >= 0.9 else 'FAIL'}")


if __name__ == "__main__":
    main()
