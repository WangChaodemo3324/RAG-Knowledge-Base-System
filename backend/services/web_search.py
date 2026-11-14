from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

NEWS_QUERY_WORDS = (
    "新闻",
    "热搜",
    "头条",
    "资讯",
    "今日",
    "今天",
    "最新",
    "近期",
    "刚刚",
    "本周",
    "本月",
    "发布",
    "更新",
)


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _resolve_duckduckgo_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


class DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._in_title = False
        self._in_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        class_name = attr.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._current = {"title": "", "url": _resolve_duckduckgo_url(attr.get("href", "")), "snippet": ""}
            self._title_parts = []
            self._in_title = True
        elif "result__snippet" in class_name and self.results:
            self._snippet_parts = []
            self._in_snippet = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            if self._current and self._current["url"]:
                self._current["title"] = _clean_text("".join(self._title_parts))
                self.results.append(self._current)
        elif self._in_snippet and tag in {"a", "div"}:
            self._in_snippet = False
            if self.results:
                self.results[-1]["snippet"] = _clean_text("".join(self._snippet_parts))


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth and tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = _clean_text(data)
            if len(text) >= 20:
                self.parts.append(text)

    def text(self, max_chars: int = 4000) -> str:
        return _clean_text(" ".join(self.parts))[:max_chars]


def fetch_page_text(client: httpx.Client, url: str, max_chars: int = 4000) -> str:
    try:
        response = client.get(url, timeout=12)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return ""
        parser = TextExtractor()
        parser.feed(response.text)
        return parser.text(max_chars=max_chars)
    except Exception:
        return ""


def _is_news_like_query(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    return any(word in normalized for word in NEWS_QUERY_WORDS)


def _news_queries(query: str) -> list[str]:
    today = date.today()
    normalized = str(query or "").strip()
    candidates = [normalized]
    if _is_news_like_query(normalized):
        candidates.extend(
            [
                f"{today.year}年{today.month}月{today.day}日 中国 新闻",
                f"{today.isoformat()} China news",
                "China news today",
                "latest world news today",
            ]
        )
    return [item for index, item in enumerate(candidates) if item and item not in candidates[:index]]


def _source_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or "web"


def _bing_news_rss(client: httpx.Client, query: str, top_k: int) -> list[dict[str, Any]]:
    response = client.get(
        "https://www.bing.com/news/search",
        params={"q": query, "format": "rss"},
    )
    response.raise_for_status()
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        title = _clean_text(item.findtext("title") or "")
        link = _clean_text(item.findtext("link") or "")
        description = _clean_text(item.findtext("description") or "")
        pub_date = _clean_text(item.findtext("pubDate") or "")
        if not title or not link or link in seen:
            continue
        seen.add(link)
        content = f"{title}。{description}"
        if pub_date:
            content = f"发布时间：{pub_date}。{content}"
        results.append(
            {
                "index": len(results) + 1,
                "source": _source_from_url(link),
                "title": title,
                "url": link,
                "snippet": description,
                "content": content,
                "preview": content[:260],
                "provider": "bing_news_rss",
                "query": query,
            }
        )
        if len(results) >= top_k:
            break
    return results


def _duckduckgo_html(client: httpx.Client, query: str, top_k: int, fetch_pages: bool) -> list[dict[str, Any]]:
    response = client.get("https://duckduckgo.com/html/", params={"q": query})
    response.raise_for_status()
    parser = DuckDuckGoParser()
    parser.feed(response.text)

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parser.results:
        url = item["url"]
        if not url or url in seen:
            continue
        seen.add(url)
        content = fetch_page_text(client, url) if fetch_pages else ""
        text = content or item.get("snippet", "")
        domain = urlparse(url).netloc
        results.append(
            {
                "index": len(results) + 1,
                "source": domain,
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("snippet", ""),
                "content": text,
                "preview": text[:260],
                "provider": "duckduckgo_html",
                "query": query,
            }
        )
        if len(results) >= top_k:
            break
    return results


def _merge_results(groups: list[list[dict[str, Any]]], top_k: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = item.get("url") or f"{item.get('source')}::{item.get('title')}"
            if not key or key in seen:
                continue
            seen.add(key)
            result = dict(item)
            result["index"] = len(merged) + 1
            merged.append(result)
            if len(merged) >= top_k:
                return merged
    return merged


def search_web(query: str, top_k: int = 4, fetch_pages: bool = False) -> list[dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        groups: list[list[dict[str, Any]]] = []
        if _is_news_like_query(query):
            for news_query in _news_queries(query):
                results = _bing_news_rss(client, news_query, top_k)
                if results:
                    groups.append(results)
                    break

        groups.append(_duckduckgo_html(client, query, top_k, fetch_pages))

        if not groups or not any(groups):
            for news_query in _news_queries(query):
                results = _bing_news_rss(client, news_query, top_k)
                if results:
                    groups.append(results)
                    break

        return _merge_results(groups, top_k)
