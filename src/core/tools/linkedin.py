"""LinkedIn Tool — post text and articles to LinkedIn on principal's behalf.

Uses LinkedIn UGC Posts API (v2) with OAuth 2.0 3-legged token.
This is the official API — no browser automation, no bot risk.

Setup (one-time):
    python scripts/linkedin_auth.py

Environment variables required:
    LINKEDIN_ACCESS_TOKEN   — OAuth access token (from setup script)
    LINKEDIN_PERSON_URN     — urn:li:person:XXXXXXX (from setup script)

Rate limits:
    150 posts/day per member (official LinkedIn limit)
"""

import logging
from typing import Optional

import aiohttp

from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)

_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_RESTLI_HEADER = {"X-Restli-Protocol-Version": "2.0.0"}


class LinkedInTool(BaseTool):
    """Tool to post to LinkedIn on principal's behalf via the official API.

    Supports text posts and article/URL shares. Uses OAuth 2.0 — no browser
    automation, no ToS violation, no ban risk.
    """

    name = "linkedin"
    description = (
        "Tool to post to LinkedIn on principal's behalf using the official LinkedIn API. "
        "Use for: publishing professional insights, sharing articles with commentary, "
        "posting thoughts on AI/tech trends to the professional network. "
        "Operations: 'post_text' (text only), 'post_article' (URL + commentary), "
        "'delete_post' (remove a post by its URN/ID), 'get_posts' (verify recent posts). "
        "Do NOT use for casual social posts — LinkedIn is professional context only."
    )
    parameters = {
        "operation": {
            "type": "string",
            "enum": ["post_text", "post_article", "delete_post", "get_posts"],
            "description": (
                "'post_text': publish a text-only LinkedIn post. "
                "'post_article': share a URL with commentary (and optional title). "
                "'delete_post': delete a post by its URN (e.g. 'urn:li:share:12345'). "
                "'get_posts': fetch recent posts by the principal (verify posts exist)."
            ),
        },
        "text": {
            "type": "string",
            "description": (
                "Post commentary / text. Required for post_text and post_article. "
                "LinkedIn best practice: 1-3 short paragraphs, end with a question or insight. "
                "Hashtags optional but effective (3-5 max)."
            ),
        },
        "url": {
            "type": "string",
            "description": "URL to share. Required for 'post_article'.",
        },
        "title": {
            "type": "string",
            "description": "Optional title override for the shared article.",
        },
        "visibility": {
            "type": "string",
            "enum": ["PUBLIC", "CONNECTIONS"],
            "description": "Who can see the post. Default: PUBLIC.",
        },
        "post_urn": {
            "type": "string",
            "description": "Post URN to delete. Required for 'delete_post'. Format: 'urn:li:share:12345'.",
        },
    }

    def __init__(self, access_token: str, person_urn: str):
        """
        Args:
            access_token: LinkedIn OAuth 2.0 access token
            person_urn: LinkedIn person URN, e.g. 'urn:li:person:XXXXXXX'
        """
        self.access_token = access_token
        self.person_urn = person_urn

    async def execute(
        self,
        operation: str,
        text: Optional[str] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
        visibility: str = "PUBLIC",
        post_urn: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        if operation == "delete_post":
            if not post_urn or not post_urn.strip():
                return ToolResult(success=False, error="'post_urn' is required for delete_post")
            return await self._delete_post(post_urn.strip())

        if operation == "get_posts":
            return await self._get_posts()

        if not text or not text.strip():
            return ToolResult(success=False, error="'text' is required")

        if operation == "post_text":
            return await self._post_text(text.strip(), visibility)
        elif operation == "post_article":
            if not url or not url.strip():
                return ToolResult(success=False, error="'url' is required for post_article")
            return await self._post_article(text.strip(), url.strip(), title, visibility)
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _post_text(self, text: str, visibility: str) -> ToolResult:
        body = {
            "author": self.person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": visibility
            },
        }
        return await self._call_api(body)

    async def _post_article(
        self,
        text: str,
        url: str,
        title: Optional[str],
        visibility: str,
    ) -> ToolResult:
        media: dict = {"status": "READY", "originalUrl": url}
        if title:
            media["title"] = {"text": title}

        body = {
            "author": self.person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "ARTICLE",
                    "media": [media],
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": visibility
            },
        }
        return await self._call_api(body)

    async def _get_posts(self, count: int = 5) -> ToolResult:
        """Fetch recent posts by the principal (requires r_member_social scope)."""
        from urllib.parse import quote
        encoded_author = quote(self.person_urn, safe="")
        url = f"{_UGC_POSTS_URL}?q=authors&authors=List({encoded_author})&count={count}"
        headers = {
            **_RESTLI_HEADER,
            "Authorization": f"Bearer {self.access_token}",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        elements = data.get("elements", [])
                        if not elements:
                            return ToolResult(success=True, output="No recent LinkedIn posts found.")
                        lines = []
                        for post in elements:
                            post_id = post.get("id", "unknown")
                            text = (
                                post.get("specificContent", {})
                                .get("com.linkedin.ugc.ShareContent", {})
                                .get("shareCommentary", {})
                                .get("text", "(no text)")
                            )
                            created = post.get("created", {}).get("time", "")
                            lines.append(f"- [{post_id}] {text[:120]}")
                        return ToolResult(
                            success=True,
                            output=f"Recent LinkedIn posts ({len(elements)}):\n" + "\n".join(lines),
                        )
                    elif resp.status == 403:
                        return ToolResult(
                            success=False,
                            error="Cannot read posts — r_member_social scope not granted. Re-run linkedin_auth.py to add this permission.",
                        )
                    else:
                        error_body = await resp.text()
                        return ToolResult(
                            success=False,
                            error=f"LinkedIn API error {resp.status}: {error_body[:200]}",
                        )
        except Exception as e:
            logger.error(f"LinkedIn get_posts failed: {e}", exc_info=True)
            return ToolResult(success=False, error=f"Failed to fetch posts: {e}")

    async def _delete_post(self, post_urn: str) -> ToolResult:
        """Delete a LinkedIn post by URN."""
        from urllib.parse import quote
        encoded_urn = quote(post_urn, safe="")
        delete_url = f"{_UGC_POSTS_URL}/{encoded_urn}"
        headers = {
            **_RESTLI_HEADER,
            "Authorization": f"Bearer {self.access_token}",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    delete_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 204:
                        logger.info(f"LinkedIn post deleted: {post_urn}")
                        return ToolResult(success=True, output=f"Post deleted: {post_urn}")
                    else:
                        error_body = await resp.text()
                        logger.error(f"LinkedIn delete {resp.status}: {error_body[:300]}")
                        return ToolResult(
                            success=False,
                            error=f"Failed to delete post ({resp.status}): {error_body[:200]}",
                        )
        except Exception as e:
            logger.error(f"LinkedIn delete failed: {e}", exc_info=True)
            return ToolResult(success=False, error=f"Delete failed: {e}")

    async def _call_api(self, body: dict) -> ToolResult:
        headers = {
            **_RESTLI_HEADER,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _UGC_POSTS_URL, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 201:
                        post_id = resp.headers.get("X-RestLi-Id", "unknown")
                        logger.info(f"LinkedIn post created: {post_id}")
                        return ToolResult(
                            success=True,
                            output=f"LinkedIn post published (ID: {post_id})",
                            metadata={"post_id": post_id},
                        )
                    else:
                        error_body = await resp.text()
                        logger.error(f"LinkedIn API {resp.status}: {error_body[:300]}")
                        # Token expired = 401; provide clear action
                        if resp.status == 401:
                            return ToolResult(
                                success=False,
                                error=(
                                    "LinkedIn access token expired. "
                                    "Run: python scripts/linkedin_auth.py to refresh."
                                ),
                            )
                        return ToolResult(
                            success=False,
                            error=f"LinkedIn API error {resp.status}: {error_body[:200]}",
                        )
        except aiohttp.ClientError as e:
            logger.error(f"LinkedIn network error: {e}")
            return ToolResult(success=False, error=f"LinkedIn network error: {e}")
        except Exception as e:
            logger.error(f"LinkedIn post failed: {e}", exc_info=True)
            return ToolResult(success=False, error=f"LinkedIn post failed: {e}")
