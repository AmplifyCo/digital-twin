"""Browser tool for web browsing and visual verification using Playwright.

Takes screenshots of pages so Claude can visually verify content,
similar to how Cursor and Claude Code browse the web.
Uses Xvfb on headless servers to run Chrome in headed mode (anti-detection).
"""

import asyncio
import base64
import logging
import os
import subprocess
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)

# Track whether Xvfb has been started this process
_xvfb_started = False


def _ensure_virtual_display():
    """Start Xvfb virtual display if no DISPLAY is set (headless server).

    Allows Chrome to run in headed mode on servers without a monitor,
    making it indistinguishable from a real user's browser.
    """
    global _xvfb_started
    if os.environ.get("DISPLAY") or _xvfb_started:
        return

    try:
        subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
        _xvfb_started = True
        logger.info("Xvfb virtual display started on :99")
    except FileNotFoundError:
        logger.debug("Xvfb not installed — will use headless mode")


class BrowserTool(BaseTool):
    """Tool for web browsing with visual verification via screenshots.

    Text mode: w3m/curl for lightweight page fetching (no screenshots).
    Full mode: Playwright + Chromium with screenshot capture for Claude vision.
    """

    name = "browser"
    description = (
        "Tool to load a webpage using a real browser. "
        "Use when web_fetch returns empty or incomplete content (JavaScript-heavy pages). "
        "Use 'text' mode for fast text extraction (articles, docs). "
        "Use 'full' mode for JS-rendered pages or when you need a visual screenshot. "
        "Slower than web_fetch — only use when web_fetch fails."
    )

    parameters = {
        "url": {
            "type": "string",
            "description": "The URL to browse"
        },
        "mode": {
            "type": "string",
            "description": "Browser mode: 'text' for w3m text dump, 'full' for Chromium with screenshot",
            "enum": ["text", "full"],
            "default": "text"
        },
        "javascript": {
            "type": "boolean",
            "description": "Wait for JavaScript to finish (full mode only)",
            "default": False
        },
        "wait_for_selector": {
            "type": "string",
            "description": "CSS selector to wait for before capturing (full mode only)",
            "default": None
        },
        "screenshot": {
            "type": "boolean",
            "description": "Capture screenshot for visual verification (full mode only)",
            "default": True
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
            logger.warning(
                "Playwright not installed. Only text mode available. "
                "Install with: pip install playwright && playwright install chromium"
            )

    async def execute(
        self,
        url: str,
        mode: str = "text",
        javascript: bool = False,
        wait_for_selector: Optional[str] = None,
        screenshot: bool = True,
    ) -> ToolResult:
        """Browse a web page.

        Args:
            url: URL to browse
            mode: 'text' for w3m, 'full' for Playwright with screenshot
            javascript: Wait for JS execution (full mode only)
            wait_for_selector: CSS selector to wait for (full mode only)
            screenshot: Capture screenshot for visual verification (full mode only)

        Returns:
            ToolResult with page content (and screenshot if full mode)
        """
        try:
            if mode == "text":
                return await self._browse_text(url)
            elif mode == "full":
                return await self._browse_full(url, javascript, wait_for_selector, screenshot)
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
            process = await asyncio.create_subprocess_shell(
                f"w3m -dump '{url}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30,
            )

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                logger.warning(f"w3m failed, trying curl: {error_msg}")
                return await self._fallback_curl(url)

            content = stdout.decode("utf-8", errors="replace")

            return ToolResult(
                success=True,
                output=content,
                metadata={"url": url, "mode": "text", "browser": "w3m"},
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Timeout browsing {url} with w3m",
            )
        except Exception as e:
            logger.error(f"w3m error: {e}")
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
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30,
            )

            if process.returncode == 0:
                content = stdout.decode("utf-8", errors="replace")
                return ToolResult(
                    success=True,
                    output=content,
                    metadata={"url": url, "mode": "text", "browser": "curl"},
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Failed to fetch {url}: {stderr.decode()}",
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Curl error: {str(e)}",
            )

    async def _browse_full(
        self,
        url: str,
        execute_js: bool = False,
        wait_for_selector: Optional[str] = None,
        take_screenshot: bool = True,
    ) -> ToolResult:
        """Browse using Chromium via Playwright with optional screenshot.

        Uses Xvfb on headless servers to run Chrome in headed mode,
        avoiding bot detection. Falls back to headless if Xvfb unavailable.

        Args:
            url: URL to browse
            execute_js: Whether to wait for JavaScript execution
            wait_for_selector: CSS selector to wait for before capturing
            take_screenshot: Whether to capture a screenshot for visual verification

        Returns:
            ToolResult with page content and optional screenshot
        """
        if not self.playwright_available:
            return ToolResult(
                success=False,
                error=(
                    "Playwright not available. Install with: "
                    "pip install playwright && playwright install chromium"
                ),
            )

        # Start Xvfb if needed (headed mode for anti-detection)
        _ensure_virtual_display()
        use_headless = not os.environ.get("DISPLAY")

        playwright = None
        browser = None
        try:
            playwright = await self.async_playwright().start()

            browser = await playwright.chromium.launch(
                headless=use_headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            page.set_default_timeout(30000)

            await page.goto(url, wait_until="domcontentloaded")

            if execute_js:
                await page.wait_for_load_state("networkidle")

            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=10000)

            # Extract text content
            page_text = await page.inner_text("body")
            page_title = await page.title()
            page_url = page.url  # May differ if redirected

            # Capture screenshot for visual verification
            screenshot_b64 = None
            if take_screenshot:
                try:
                    png_bytes = await page.screenshot(full_page=False, type="png")
                    screenshot_b64 = base64.b64encode(png_bytes).decode("utf-8")
                    logger.debug(f"Screenshot captured: {len(png_bytes)} bytes")
                except Exception as e:
                    logger.warning(f"Screenshot failed (continuing with text): {e}")

            await context.close()

            metadata = {
                "url": page_url,
                "title": page_title,
                "mode": "full",
                "browser": "chromium-playwright",
                "headed": not use_headless,
                "javascript": execute_js,
                "screenshot": screenshot_b64 is not None,
                "content_length": len(page_text),
            }

            # Return multimodal result (screenshot + text) for Claude vision
            if screenshot_b64:
                return ToolResult(
                    success=True,
                    content_blocks=[
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Page: {page_title} ({page_url})\n\n{page_text}",
                        },
                    ],
                    metadata=metadata,
                )
            else:
                # Fallback: text-only
                return ToolResult(
                    success=True,
                    output=page_text,
                    metadata=metadata,
                )

        except Exception as e:
            logger.error(f"Playwright error: {e}")
            return ToolResult(
                success=False,
                error=f"Playwright browser error: {str(e)}",
            )

        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass
