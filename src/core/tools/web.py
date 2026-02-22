"""Web search and fetch tool."""

import aiohttp
import logging
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class WebTool(BaseTool):
    """Tool for fetching web content."""

    name = "web_fetch"
    description = (
        "Tool to fetch content from a specific URL and return its text. "
        "Use when you already have a URL to read. "
        "Do NOT use for general searches — use web_search for that. "
        "If the page returns empty content (JavaScript-heavy site), use the browser tool instead."
    )
    parameters = {
        "url": {
            "type": "string",
            "description": "URL to fetch"
        }
    }

    async def execute(self, url: str) -> ToolResult:
        """Fetch content from URL.

        Args:
            url: URL to fetch

        Returns:
            ToolResult with fetched content
        """
        try:
            logger.info(f"Fetching URL: {url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        content = await response.text()
                        logger.info(f"Fetched {len(content)} chars from {url}")
                        return ToolResult(
                            success=True,
                            output=content[:10000],  # Limit to 10k chars
                            metadata={"url": url, "status": response.status}
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=f"HTTP {response.status}: {url}"
                        )

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching {url}: {e}")
            return ToolResult(
                success=False,
                error=f"Network error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return ToolResult(
                success=False,
                error=f"Error: {str(e)}"
            )
