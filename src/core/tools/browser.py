"""Browser tool for web browsing and automation using Playwright."""

import asyncio
import logging
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class BrowserTool(BaseTool):
    """Tool for web browsing using text-based or headless browser (Playwright)."""

    name = "browser"
    description = """Browse web pages using text-based (w3m) or full browser (Playwright).
    Use text mode for reading articles, documentation. Use full mode for JavaScript-heavy sites."""

    parameters = {
        "url": {
            "type": "string",
            "description": "The URL to browse"
        },
        "mode": {
            "type": "string",
            "description": "Browser mode: 'text' for w3m text dump, 'full' for headless Chromium",
            "enum": ["text", "full"],
            "default": "text"
        },
        "javascript": {
            "type": "boolean",
            "description": "Execute JavaScript (only for full mode)",
            "default": False
        },
        "wait_for_selector": {
            "type": "string",
            "description": "CSS selector to wait for before returning content (full mode only)",
            "default": None
        }
    }

    def __init__(self):
        """Initialize BrowserTool."""
        self.playwright_available = False
        try:
            from playwright.async_api import async_playwright
            self.async_playwright = async_playwright
            self.playwright_available = True
            logger.info("Playwright available for full browser mode")
        except ImportError:
            logger.warning("Playwright not installed. Only text mode available. Install with: pip install playwright && playwright install chromium")

    async def execute(
        self,
        url: str,
        mode: str = "text",
        javascript: bool = False,
        wait_for_selector: Optional[str] = None
    ) -> ToolResult:
        """Browse a web page.

        Args:
            url: URL to browse
            mode: 'text' for w3m, 'full' for Playwright
            javascript: Execute JavaScript (full mode only)
            wait_for_selector: CSS selector to wait for (full mode only)

        Returns:
            ToolResult with page content
        """
        try:
            if mode == "text":
                return await self._browse_text(url)
            elif mode == "full":
                return await self._browse_full(url, javascript, wait_for_selector)
            else:
                return ToolResult(
                    success=False,
                    error=f"Invalid mode: {mode}. Use 'text' or 'full'"
                )

        except Exception as e:
            logger.error(f"Error browsing {url}: {e}")
            return ToolResult(
                success=False,
                error=f"Browser error: {str(e)}"
            )

    async def _browse_text(self, url: str) -> ToolResult:
        """Browse using text-based w3m browser.

        Args:
            url: URL to fetch

        Returns:
            ToolResult with text content
        """
        try:
            # Use w3m to dump text content
            process = await asyncio.create_subprocess_shell(
                f"w3m -dump '{url}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace')
                # Fallback to curl if w3m fails
                logger.warning(f"w3m failed, trying curl: {error_msg}")
                return await self._fallback_curl(url)

            content = stdout.decode('utf-8', errors='replace')

            return ToolResult(
                success=True,
                output=content,
                metadata={
                    "url": url,
                    "mode": "text",
                    "browser": "w3m"
                }
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Timeout browsing {url} with w3m"
            )
        except Exception as e:
            logger.error(f"w3m error: {e}")
            # Fallback to curl
            return await self._fallback_curl(url)

    async def _fallback_curl(self, url: str) -> ToolResult:
        """Fallback to curl if w3m fails.

        Args:
            url: URL to fetch

        Returns:
            ToolResult with raw content
        """
        try:
            process = await asyncio.create_subprocess_shell(
                f"curl -L -s '{url}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )

            if process.returncode == 0:
                content = stdout.decode('utf-8', errors='replace')
                return ToolResult(
                    success=True,
                    output=content,
                    metadata={
                        "url": url,
                        "mode": "text",
                        "browser": "curl"
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Failed to fetch {url}: {stderr.decode()}"
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Curl error: {str(e)}"
            )

    async def _browse_full(
        self,
        url: str,
        execute_js: bool = False,
        wait_for_selector: Optional[str] = None
    ) -> ToolResult:
        """Browse using headless Chromium via Playwright.

        Args:
            url: URL to browse
            execute_js: Whether to wait for JavaScript execution
            wait_for_selector: CSS selector to wait for before extracting content

        Returns:
            ToolResult with page content
        """
        if not self.playwright_available:
            return ToolResult(
                success=False,
                error="Playwright not available. Install with: pip install playwright && playwright install chromium"
            )

        playwright = None
        browser = None
        try:
            # Launch Playwright
            playwright = await self.async_playwright().start()

            # Launch browser (headless by default)
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu'
                ]
            )

            # Create context and page
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            page = await context.new_page()

            # Set timeout
            page.set_default_timeout(30000)  # 30 seconds

            # Navigate to URL
            await page.goto(url, wait_until='domcontentloaded')

            # Wait for JavaScript if requested
            if execute_js:
                await page.wait_for_load_state('networkidle')

            # Wait for specific selector if provided
            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=10000)

            # Get page content
            page_text = await page.inner_text('body')
            page_title = await page.title()
            page_url = page.url  # May differ from original if redirected

            # Close page and context
            await context.close()

            return ToolResult(
                success=True,
                output=page_text,
                metadata={
                    "url": page_url,
                    "title": page_title,
                    "mode": "full",
                    "browser": "chromium-playwright",
                    "javascript": execute_js,
                    "wait_for_selector": wait_for_selector,
                    "content_length": len(page_text)
                }
            )

        except Exception as e:
            logger.error(f"Playwright error: {e}")
            return ToolResult(
                success=False,
                error=f"Playwright browser error: {str(e)}"
            )

        finally:
            # Cleanup
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except:
                    pass
