"""X (Twitter) posting tool using X API v2 with OAuth 2.0 Bearer Token."""

import logging
import os
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class XTool(BaseTool):
    """Tool for posting to X (Twitter) using the X API v2.

    Uses OAuth 2.0 Bearer Token for authentication.
    Only posts when explicitly asked by the user — no auto-interactions.
    """

    name = "x_post"
    description = "Post tweets to X (Twitter). Can post new tweets and delete tweets."
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'post_tweet' or 'delete_tweet'",
            "enum": ["post_tweet", "delete_tweet"]
        },
        "content": {
            "type": "string",
            "description": "Tweet text content (max 280 characters, for post_tweet)"
        },
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to delete (for delete_tweet)"
        }
    }

    def __init__(self, access_token: str):
        """Initialize X tool.

        Args:
            access_token: OAuth 2.0 access token for X API v2
        """
        self.access_token = access_token
        self.api_base = "https://api.x.com/2"

    async def execute(
        self,
        operation: str,
        content: Optional[str] = None,
        tweet_id: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute X operation.

        Args:
            operation: Operation to perform
            content: Tweet text (for post_tweet)
            tweet_id: Tweet ID (for delete_tweet)

        Returns:
            ToolResult with operation result
        """
        try:
            if operation == "post_tweet":
                return await self._post_tweet(content)
            elif operation == "delete_tweet":
                return await self._delete_tweet(tweet_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown operation: {operation}"
                )
        except Exception as e:
            logger.error(f"X operation error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"X operation failed: {str(e)}"
            )

    async def _post_tweet(self, content: Optional[str]) -> ToolResult:
        """Post a tweet to X."""
        import json

        if not content:
            return ToolResult(success=False, error="Tweet content is required")

        if len(content) > 280:
            return ToolResult(
                success=False,
                error=f"Tweet too long ({len(content)} chars). Max is 280."
            )

        # Use aiohttp if available, fall back to requests in thread
        try:
            import aiohttp
            return await self._post_tweet_aiohttp(content)
        except ImportError:
            return await self._post_tweet_requests(content)

    async def _post_tweet_aiohttp(self, content: str) -> ToolResult:
        """Post tweet using aiohttp (async)."""
        import aiohttp
        import json

        url = f"{self.api_base}/tweets"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {"text": content}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                response_data = await resp.json()

                if resp.status in (200, 201):
                    tweet_id = response_data.get("data", {}).get("id", "unknown")
                    logger.info(f"Tweet posted successfully: {tweet_id}")
                    return ToolResult(
                        success=True,
                        output=f"Tweet posted successfully!\nTweet ID: {tweet_id}\nContent: {content}",
                        metadata={"tweet_id": tweet_id}
                    )
                else:
                    error_detail = response_data.get("detail", response_data.get("title", str(response_data)))
                    logger.error(f"X API error: {resp.status} - {error_detail}")
                    return ToolResult(
                        success=False,
                        error=f"X API error ({resp.status}): {error_detail}"
                    )

    async def _post_tweet_requests(self, content: str) -> ToolResult:
        """Post tweet using requests (sync fallback)."""
        import requests
        import json
        import asyncio

        def _do_post():
            url = f"{self.api_base}/tweets"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            payload = {"text": content}
            return requests.post(url, headers=headers, json=payload, timeout=30)

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _do_post)

        if resp.status_code in (200, 201):
            response_data = resp.json()
            tweet_id = response_data.get("data", {}).get("id", "unknown")
            logger.info(f"Tweet posted successfully: {tweet_id}")
            return ToolResult(
                success=True,
                output=f"Tweet posted successfully!\nTweet ID: {tweet_id}\nContent: {content}",
                metadata={"tweet_id": tweet_id}
            )
        else:
            try:
                error_data = resp.json()
                error_detail = error_data.get("detail", error_data.get("title", str(error_data)))
            except Exception:
                error_detail = resp.text
            logger.error(f"X API error: {resp.status_code} - {error_detail}")
            return ToolResult(
                success=False,
                error=f"X API error ({resp.status_code}): {error_detail}"
            )

    async def _delete_tweet(self, tweet_id: Optional[str]) -> ToolResult:
        """Delete a tweet from X."""
        if not tweet_id:
            return ToolResult(success=False, error="tweet_id is required")

        try:
            import aiohttp

            url = f"{self.api_base}/tweets/{tweet_id}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
            }

            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as resp:
                    if resp.status == 200:
                        logger.info(f"Tweet deleted: {tweet_id}")
                        return ToolResult(
                            success=True,
                            output=f"Tweet {tweet_id} deleted successfully."
                        )
                    else:
                        response_data = await resp.json()
                        error_detail = response_data.get("detail", str(response_data))
                        return ToolResult(
                            success=False,
                            error=f"Failed to delete tweet ({resp.status}): {error_detail}"
                        )
        except ImportError:
            import requests
            import asyncio

            def _do_delete():
                url = f"{self.api_base}/tweets/{tweet_id}"
                headers = {"Authorization": f"Bearer {self.access_token}"}
                return requests.delete(url, headers=headers, timeout=30)

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, _do_delete)

            if resp.status_code == 200:
                logger.info(f"Tweet deleted: {tweet_id}")
                return ToolResult(
                    success=True,
                    output=f"Tweet {tweet_id} deleted successfully."
                )
            else:
                try:
                    error_data = resp.json()
                    error_detail = error_data.get("detail", str(error_data))
                except Exception:
                    error_detail = resp.text
                return ToolResult(
                    success=False,
                    error=f"Failed to delete tweet ({resp.status_code}): {error_detail}"
                )
