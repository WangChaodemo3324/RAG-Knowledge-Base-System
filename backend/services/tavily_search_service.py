from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class TavilySearchService:
    """Thin wrapper around Tavily Search API.

    Importing the SDK is delayed so the app can still run without tavily-python
    installed or without a Tavily API key; WebSearchTool handles fallback.
    """

    def __init__(self, api_key: str, timeout: int = 15) -> None:
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY is not configured.")
        try:
            from tavily import TavilyClient
        except Exception as exc:
            raise RuntimeError("tavily-python is not installed. Run: pip install tavily-python") from exc

        self.client = TavilyClient(api_key=api_key)
        self.timeout = timeout

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = False,
        include_raw_content: bool = False,
        topic: str = "general",
    ) -> list[dict[str, Any]]:
        response = self.client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=include_answer,
            include_raw_content=include_raw_content,
            topic=topic,
        )

        results: list[dict[str, Any]] = []
        for index, item in enumerate(response.get("results") or [], start=1):
            url = str(item.get("url") or "")
            content = str(item.get("content") or item.get("raw_content") or "")
            result = {
                "index": index,
                "title": str(item.get("title") or ""),
                "url": url,
                "content": content,
                "snippet": content,
                "preview": content[:260],
                "score": item.get("score"),
                "source": self._domain(url) or "Tavily",
                "provider": "tavily",
            }
            raw_content = item.get("raw_content")
            if raw_content:
                result["raw_content"] = raw_content
            results.append(result)
        return results

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc
