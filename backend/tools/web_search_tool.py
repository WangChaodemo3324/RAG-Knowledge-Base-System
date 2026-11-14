from __future__ import annotations

from time import perf_counter, sleep
from typing import Any

from backend.core.config import (
    TAVILY_API_KEY,
    WEB_SEARCH_DEPTH,
    WEB_SEARCH_FALLBACK,
    WEB_SEARCH_INCLUDE_RAW_CONTENT,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_PROVIDER,
    WEB_SEARCH_REQUIRE_TAVILY,
    WEB_SEARCH_TAVILY_MAX_RETRIES,
    WEB_SEARCH_TIMEOUT,
)
from backend.services.tavily_search_service import TavilySearchService
from backend.services.web_search import search_web
from backend.tools.weather_tool import WeatherTool


class WebSearchTool:
    name = "web_search"
    description = "用于查询实时信息、新闻、价格、版本、天气等需要联网的问题"

    def __init__(self, weather_tool: WeatherTool | None = None) -> None:
        self.weather_tool = weather_tool or WeatherTool()
        self.require_tavily = WEB_SEARCH_REQUIRE_TAVILY
        self.configured_provider = WEB_SEARCH_PROVIDER
        self.provider = "tavily"
        self.fallback = WEB_SEARCH_FALLBACK
        self.default_max_results = WEB_SEARCH_MAX_RESULTS
        self.search_depth = WEB_SEARCH_DEPTH
        self.include_raw_content = WEB_SEARCH_INCLUDE_RAW_CONTENT
        self.timeout = WEB_SEARCH_TIMEOUT
        self.tavily_max_retries = WEB_SEARCH_TAVILY_MAX_RETRIES
        self.tavily_service = self._build_tavily_service()

    def run(self, query: str, max_results: int = 5, fetch_pages: bool = False) -> list[dict[str, Any]]:
        return self.run_with_trace(query, max_results=max_results, fetch_pages=fetch_pages)["results"]

    def run_with_trace(
        self,
        query: str,
        max_results: int | None = None,
        fetch_pages: bool = False,
    ) -> dict[str, Any]:
        max_results = max_results or self.default_max_results
        started_at = perf_counter()
        errors: list[str] = []

        if self.provider == "tavily":
            tavily_result = self._search_tavily(query, max_results, started_at, errors)
            if tavily_result["results"] or self.require_tavily:
                return tavily_result

        if self.weather_tool.can_handle(query):
            try:
                weather_results = self.weather_tool.run(query, max_results=1)
                if weather_results:
                    return self._result(
                        query=query,
                        provider="open_meteo_weather",
                        results=weather_results[:max_results],
                        started_at=started_at,
                        status="fallback_success" if errors else "success",
                        errors=errors,
                        fallback_from=self.provider if errors else "",
                        retry_count=self._tavily_retry_count(errors),
                    )
            except Exception as exc:
                errors.append(f"open_meteo_weather failed: {exc}")

        fallback_result = self._search_fallback(query, max_results, fetch_pages, started_at, errors)
        if fallback_result["results"]:
            return fallback_result

        return self._result(
            query=query,
            provider=self.provider,
            results=[],
            started_at=started_at,
            status="failed",
            errors=errors,
        )

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "configured_provider": self.configured_provider,
            "fallback": self.fallback,
            "provider_chain": "tavily -> open_meteo_weather -> duckduckgo_html/bing_news_rss",
            "tavily_configured": bool(TAVILY_API_KEY),
            "require_tavily": self.require_tavily,
            "search_depth": self.search_depth,
            "include_raw_content": self.include_raw_content,
            "tavily_max_retries": self.tavily_max_retries,
        }

    def _build_tavily_service(self) -> TavilySearchService | None:
        if self.provider != "tavily" or not TAVILY_API_KEY:
            return None
        try:
            return TavilySearchService(api_key=TAVILY_API_KEY, timeout=self.timeout)
        except Exception:
            return None

    def _search_tavily(
        self,
        query: str,
        max_results: int,
        started_at: float,
        errors: list[str],
    ) -> dict[str, Any]:
        if self.tavily_service is None:
            errors.append("tavily unavailable: missing API key or SDK")
            return self._result(query, "tavily", [], started_at, "failed", errors, retry_count=0)

        retry_count = 0
        max_attempts = self.tavily_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                results = self.tavily_service.search(
                    query=query,
                    max_results=max_results,
                    search_depth=self.search_depth,
                    include_answer=False,
                    include_raw_content=self.include_raw_content,
                )
                return self._result(
                    query,
                    "tavily",
                    results,
                    started_at,
                    "success",
                    errors,
                    retry_count=retry_count,
                )
            except Exception as exc:
                error_text = str(exc)
                errors.append(f"tavily attempt {attempt}/{max_attempts} failed: {error_text}")
                if self._is_non_retryable_tavily_error(error_text) or attempt >= max_attempts:
                    break
                retry_count += 1
                sleep(min(0.5 * attempt, 2.0))

        return self._result(query, "tavily", [], started_at, "failed", errors, retry_count=retry_count)

    def _search_fallback(
        self,
        query: str,
        max_results: int,
        fetch_pages: bool,
        started_at: float,
        errors: list[str],
    ) -> dict[str, Any]:
        if self.fallback not in {"duckduckgo", "local", "web_search"}:
            errors.append(f"unsupported fallback provider: {self.fallback}")
            return self._result(query, self.fallback, [], started_at, "failed", errors)
        try:
            results = search_web(query, top_k=max_results, fetch_pages=fetch_pages)
            provider = "duckduckgo"
            status = "fallback_success" if errors else "success"
            fallback_from = self.provider if errors else ""
            return self._result(
                query,
                provider,
                results,
                started_at,
                status,
                errors,
                fallback_from=fallback_from,
                retry_count=self._tavily_retry_count(errors),
            )
        except Exception as exc:
            errors.append(f"duckduckgo fallback failed: {exc}")
            return self._result(query, "duckduckgo", [], started_at, "failed", errors)

    def _result(
        self,
        query: str,
        provider: str,
        results: list[dict[str, Any]],
        started_at: float,
        status: str,
        errors: list[str],
        fallback_from: str = "",
        retry_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "tool": self.name,
            "provider": provider,
            "fallback_from": fallback_from,
            "query": query,
            "result_count": len(results),
            "results": results,
            "duration_ms": int((perf_counter() - started_at) * 1000),
            "status": status,
            "errors": list(errors),
            "retry_count": retry_count,
        }

    def _is_non_retryable_tavily_error(self, error_text: str) -> bool:
        normalized = error_text.lower()
        markers = ("401", "403", "unauthorized", "forbidden", "invalid api key", "api key")
        return any(marker in normalized for marker in markers)

    def _tavily_retry_count(self, errors: list[str]) -> int:
        tavily_attempts = sum(1 for error in errors if error.startswith("tavily attempt "))
        if tavily_attempts:
            return max(tavily_attempts - 1, 0)
        return 0
