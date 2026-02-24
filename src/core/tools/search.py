"""Web search tool — Tavily (primary) or DuckDuckGo (fallback).

Tavily is preferred when TAVILY_API_KEY is set:
- Designed for AI agents, not scraped from a search engine UI
- Reliable on cloud/EC2 IPs (DuckDuckGo aggressively rate-limits them)
- Returns clean, summarized content — not just titles and snippets

DuckDuckGo is the no-key fallback with retry on transient failures.

To enable Tavily: add TAVILY_API_KEY to .env (free tier: 1000/month at tavily.com)
"""

import asyncio
import logging
import os
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)

_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


class WebSearchTool(BaseTool):
    """Search the web. Uses Tavily when configured, DuckDuckGo otherwise."""

    name = "web_search"
    description = (
        "Tool to search the web for any topic. Returns titles, URLs, and content. "
        "Use when you need to find information but don't have a specific URL. "
        "Use before web_fetch: search first, then fetch the most relevant URLs. "
        "Use when: researching topics, finding current information, looking up "
        "businesses, phone numbers, restaurants, or any real-world information."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "The search query"
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5, max: 10)",
            "default": 5
        }
    }

    async def execute(self, query: str, max_results: int = 5, **kwargs) -> ToolResult:
        """Search the web via Tavily (primary) or DuckDuckGo (fallback)."""
        max_results = min(int(max_results), 10)

        # Primary: Tavily (reliable on cloud IPs, better structured results)
        if _TAVILY_API_KEY:
            result = await self._search_tavily(query, max_results)
            if result.success:
                return result
            logger.warning(f"Tavily search failed, falling back to DuckDuckGo: {result.error}")

        # Fallback: DuckDuckGo with retry
        return await self._search_duckduckgo(query, max_results)

    async def _search_tavily(self, query: str, max_results: int) -> ToolResult:
        """Search via Tavily API (structured, AI-optimised results)."""
        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=_TAVILY_API_KEY)
            # TavilyClient is sync; run in thread so we don't block the event loop
            response = await asyncio.to_thread(
                client.search,
                query,
                max_results=max_results,
                search_depth="basic",
            )

            results = response.get("results", [])
            if not results:
                return ToolResult(success=True, output=f"No results found for: {query}")

            lines = [f"Search results for: {query}\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("url", "")
                content = r.get("content", "")
                lines.append(f"{i}. {title}")
                if url:
                    lines.append(f"   URL: {url}")
                if content:
                    lines.append(f"   {content[:500]}")
                lines.append("")

            output = "\n".join(lines).strip()
            logger.info(f"Tavily search '{query}': {len(results)} results")
            return ToolResult(
                success=True,
                output=output,
                metadata={"query": query, "result_count": len(results), "provider": "tavily"}
            )

        except ImportError:
            return ToolResult(
                success=False,
                error="tavily-python not installed. Run: pip install tavily-python"
            )
        except Exception as e:
            logger.warning(f"Tavily search error: {e}")
            return ToolResult(success=False, error=str(e))

    async def _search_duckduckgo(self, query: str, max_results: int) -> ToolResult:
        """Search via DuckDuckGo with up to 2 retries on transient failures."""
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return ToolResult(
                success=False,
                error=(
                    "Web search unavailable: neither Tavily nor duckduckgo-search is configured. "
                    "Add TAVILY_API_KEY to .env (recommended) or run: pip install duckduckgo-search"
                )
            )

        last_error = None
        for attempt in range(3):
            try:
                results = []
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append(r)

                if not results:
                    return ToolResult(success=True, output=f"No results found for: {query}")

                lines = [f"Search results for: {query}\n"]
                for i, r in enumerate(results, 1):
                    title = r.get("title", "No title")
                    url = r.get("href", "")
                    snippet = r.get("body", "")
                    lines.append(f"{i}. {title}")
                    if url:
                        lines.append(f"   URL: {url}")
                    if snippet:
                        lines.append(f"   {snippet[:400]}")
                    lines.append("")

                output = "\n".join(lines).strip()
                logger.info(f"DuckDuckGo search '{query}': {len(results)} results")
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"query": query, "result_count": len(results), "provider": "duckduckgo"}
                )

            except Exception as e:
                last_error = e
                if attempt < 2:
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(
                        f"DuckDuckGo attempt {attempt + 1} failed ({e}), retrying in {wait}s..."
                    )
                    await asyncio.sleep(wait)

        logger.error(f"DuckDuckGo search failed after 3 attempts: {last_error}")
        return ToolResult(
            success=False,
            error=f"Search failed after retries: {str(last_error)}"
        )
