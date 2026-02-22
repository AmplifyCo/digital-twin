"""Web search tool using DuckDuckGo (no API key required).

Returns structured search results: title, URL, snippet.
The agent can then decide which URLs to fetch with web_fetch or browser.
"""

import logging
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo."""

    name = "web_search"
    description = (
        "Tool to search the web for any topic. Returns titles, URLs, and snippets. "
        "Use when you need to find information but don't have a specific URL. "
        "Use before web_fetch: search first, then fetch the most relevant URLs. "
        "Use when: researching topics, finding current information, looking up businesses or phone numbers."
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
        """Search the web.

        Args:
            query: Search query string
            max_results: Max results to return

        Returns:
            ToolResult with formatted search results
        """
        max_results = min(int(max_results), 10)

        try:
            from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(r)

            if not results:
                return ToolResult(
                    success=True,
                    output=f"No results found for: {query}"
                )

            lines = [f"Search results for: {query}\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", "")
                snippet = r.get("body", "")
                lines.append(f"{i}. {title}")
                if url:
                    lines.append(f"   URL: {url}")
                if snippet:
                    lines.append(f"   {snippet[:300]}")
                lines.append("")

            output = "\n".join(lines).strip()
            logger.info(f"Web search '{query}': {len(results)} results")
            return ToolResult(
                success=True,
                output=output,
                metadata={"query": query, "result_count": len(results)}
            )

        except ImportError:
            return ToolResult(
                success=False,
                error="Web search unavailable: duckduckgo-search not installed. Run: pip install duckduckgo-search"
            )
        except Exception as e:
            logger.error(f"Web search error for '{query}': {e}")
            return ToolResult(
                success=False,
                error=f"Search failed: {str(e)}"
            )
