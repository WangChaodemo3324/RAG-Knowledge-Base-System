from __future__ import annotations

import re

from backend.services.routing.route_schema import QueryFeatures


class QueryFeatureExtractor:
    """Extract compact routing signals; it is not a full intent classifier."""

    EXPLICIT_WEB_WORDS = (
        "联网",
        "上网",
        "网上",
        "搜索一下",
        "查一下网上",
        "帮我搜",
        "官网",
        "网页",
        "新闻",
        "热搜",
    )
    TIME_SENSITIVE_WORDS = (
        "今天",
        "现在",
        "当前",
        "最新",
        "近期",
        "刚刚",
        "本周",
        "本月",
        "今年",
        "实时",
        "价格",
        "股价",
        "汇率",
        "天气",
        "版本",
        "发布",
        "更新",
        "排名",
    )
    COMPANY_DOMAIN_WORDS = (
        "文档",
        "制度",
        "手册",
        "流程",
        "规范",
        "预案",
        "报销",
        "xx-200",
        "客户数据",
        "生产环境",
        "回滚",
        "故障",
        "应急",
        "入职",
        "客服平台",
        "智能网关",
    )
    PRIVATE_INTERNAL_WORDS = (
        "公司",
        "内部",
        "年假",
        "薪资",
        "审批",
        "权限",
        "员工",
        "制度",
    )
    CHAT_WORDS = ("你好", "hello", "hi", "你是谁", "谢谢", "再见")
    INSTRUCTION_WORDS = (
        "翻译",
        "润色",
        "改写",
        "写一句",
        "写一段",
        "写封",
        "帮我写",
        "解释一下",
        "请解释",
        "是什么意思",
        "是什么",
    )
    FILE_CONTEXT_WORDS = ("这份", "这个文件", "当前文档", "文档里", "手册里")
    VAGUE_REFERENCE_WORDS = ("这个", "那个", "它", "上面", "前面")
    MATH_PATTERN = re.compile(
        r"^\s*[-+]?\d+(?:\.\d+)?\s*[\+\-\*/×÷]\s*[-+]?\d+(?:\.\d+)?\s*[=＝]?\s*\??\s*$"
    )

    def extract(
        self,
        query: str,
        query_mode: str = "",
        document_id: str = "",
        file_name: str = "",
    ) -> QueryFeatures:
        normalized = self._normalize(query)
        has_selected_document = bool(str(document_id or file_name).strip())
        explicit_web = self._contains(normalized, self.EXPLICIT_WEB_WORDS)
        has_current_time_need = self._contains(normalized, self.TIME_SENSITIVE_WORDS)
        has_company_domain_hint = self._contains(normalized, self.COMPANY_DOMAIN_WORDS)
        has_private_internal_hint = self._contains(normalized, self.PRIVATE_INTERNAL_WORDS)
        is_math_like = bool(self.MATH_PATTERN.match(normalized))
        is_chat_like = self._contains(normalized, self.CHAT_WORDS)
        is_instruction_task = self._contains(normalized, self.INSTRUCTION_WORDS)
        has_file_context = has_selected_document or self._contains(normalized, self.FILE_CONTEXT_WORDS)
        is_vague_reference = self._is_vague_reference(normalized)

        return QueryFeatures(
            query_length=len(normalized),
            has_selected_document=has_selected_document,
            has_file_context=has_file_context,
            explicit_web=explicit_web,
            has_current_time_need=has_current_time_need,
            has_company_domain_hint=has_company_domain_hint,
            has_private_internal_hint=has_private_internal_hint,
            is_math_like=is_math_like,
            is_chat_like=is_chat_like,
            is_instruction_task=is_instruction_task,
            is_vague_reference=is_vague_reference,
        )

    def _normalize(self, value: str) -> str:
        return str(value or "").strip().lower()

    def _contains(self, query: str, words: tuple[str, ...]) -> bool:
        return any(word in query for word in words)

    def _is_vague_reference(self, query: str) -> bool:
        if not query or len(query) > 16:
            return False
        return self._contains(query, self.VAGUE_REFERENCE_WORDS) and any(
            marker in query for marker in ("怎么", "如何", "流程", "配置", "是什么")
        )
