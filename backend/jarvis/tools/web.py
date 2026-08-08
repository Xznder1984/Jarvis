"""Web search using DuckDuckGo (no API key needed).

If BRAVE_API_KEY or SERPAPI_API_KEY are configured those are preferred, but the
built-in DuckDuckGo HTML search keeps JARVIS functional with zero setup.
"""
from __future__ import annotations

import json
import logging
import os
import re
from html import unescape

import httpx

logger = logging.getLogger("jarvis.tools.web")


class WebSearch:
    def __init__(self, router=None) -> None:
        self._router = router

    def search(self, query: str, max_results: int = 5) -> str:
        """Search the web and return a compact text summary for the LLM."""
        brave_key = os.environ.get("BRAVE_API_KEY", "")
        if brave_key:
            return self._brave(query, brave_key, max_results)
        return self._duckduckgo(query, max_results)

    def _brave(self, query: str, api_key: str, max_results: int) -> str:
        try:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": api_key},
                timeout=20.0,
            )
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Brave search failed, falling back to DuckDuckGo: %s", exc)
            return self._duckduckgo(query, max_results)

        lines = []
        for r in results:
            title = unescape(r.get("title", ""))
            desc = unescape(r.get("description", ""))
            url = r.get("url", "")
            lines.append(f"* {title}\n  {desc}\n  {url}")
        return "\n\n".join(lines) if lines else "No results."

    def _duckduckgo(self, query: str, max_results: int) -> str:
        try:
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "JARVIS/0.1 (personal assistant)"},
                timeout=20.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("DuckDuckGo search failed: %s", exc)
            return "Search failed."

        # Parse result blocks from the HTML page.
        html = resp.text
        blocks = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
        snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        lines = []
        for i, (href, title) in enumerate(blocks[:max_results]):
            title = re.sub(r"<[^>]+>", "", title)
            snippet = re.sub(r"<[^>]+>", "", snippets[i]) if i < len(snippets) else ""
            lines.append(f"* {unescape(title)}\n  {unescape(snippet)}\n  {unescape(href)}")
        return "\n\n".join(lines) if lines else "No results."
