"""X (Twitter) posting tool using X API v2 with OAuth 1.0a User Context."""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class XTool(BaseTool):
    """Tool for posting to X (Twitter) using the X API v2.

    Uses OAuth 1.0a User Context for write operations (post/delete tweets).
    Supports posting to Communities with automatic ID resolution and caching.
    Only posts when explicitly asked by the user — no auto-interactions.
    """

    name = "x_post"
    description = (
        "Post tweets to X (Twitter). Can post to timeline or to a specific Community. "
        "Can also delete tweets. Use post_to_community to post in an X Community by name or ID."
    )
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'post_tweet', 'delete_tweet', 'post_to_community', 'retweet', or 'quote_tweet'",
            "enum": ["post_tweet", "delete_tweet", "post_to_community", "retweet", "quote_tweet"]
        },
        "content": {
            "type": "string",
            "description": "Tweet text content (max 280 characters, for post_tweet/post_to_community)"
        },
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to delete (for delete_tweet)"
        },
        "community_id": {
            "type": "string",
            "description": "Community name (e.g. 'Build In Public') or numeric ID (for post_to_community or quote_tweet)"
        },
        "quote_tweet_id": {
            "type": "string",
            "description": "ID of tweet to quote or retweet (for quote_tweet)"
        }
    }

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
        data_dir: str = "./data"
    ):
        """Initialize X tool with OAuth 1.0a credentials.

        Args:
            api_key: X API Key (Consumer Key)
            api_secret: X API Secret (Consumer Secret)
            access_token: OAuth 1.0a Access Token
            access_token_secret: OAuth 1.0a Access Token Secret
            data_dir: Directory for persistent cache files
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.api_base = "https://api.x.com/2"
        self.data_dir = Path(data_dir)
        self.communities_cache_file = self.data_dir / "x_communities.json"
        self.user_cache_file = self.data_dir / "x_user_cache.json"

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Override to make only 'operation' required."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["operation"]
            }
        }

    def _get_oauth1_session(self):
        """Create an OAuth 1.0a session using requests_oauthlib."""
        from requests_oauthlib import OAuth1Session
        return OAuth1Session(
            self.api_key,
            client_secret=self.api_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret
        )

    async def execute(
        self,
        operation: str,
        content: Optional[str] = None,
        tweet_id: Optional[str] = None,
        community_id: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute X operation."""
        try:
            if operation == "post_tweet":
                return await self._post_tweet(content)
            elif operation == "delete_tweet":
                return await self._delete_tweet(tweet_id)
            elif operation == "post_to_community":
                return await self._post_to_community(content, community_id)
            elif operation == "retweet":
                return await self._retweet(tweet_id)
            elif operation == "quote_tweet":
                content = content or ""  # Content is optional for quote? No, usually required. But if empty, standard quote.
                return await self._quote_tweet(tweet_id, content, community_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown operation: {operation}"
                )
        except ImportError as e:
            return ToolResult(
                success=False,
                error="Missing dependency: pip install requests-oauthlib"
            )
        except Exception as e:
            logger.error(f"X operation error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"X operation failed: {str(e)}"
            )

    async def _post_tweet(self, content: Optional[str]) -> ToolResult:
        """Post a tweet to X."""
        import asyncio

        if not content:
            return ToolResult(success=False, error="Tweet content is required")

        if len(content) > 280:
            return ToolResult(
                success=False,
                error=f"Tweet too long ({len(content)} chars). Max is 280."
            )

        def _do_post():
            oauth = self._get_oauth1_session()
            resp = oauth.post(
                f"{self.api_base}/tweets",
                json={"text": content}
            )
            return resp

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _do_post)

        if resp.status_code in (200, 201):
            data = resp.json()
            tweet_id = data.get("data", {}).get("id", "unknown")
            logger.info(f"Tweet posted: {tweet_id}")
            return ToolResult(
                success=True,
                output=f"Posted to X. Tweet ID: {tweet_id}",
                metadata={"tweet_id": tweet_id}
            )
        else:
            return self._handle_error(resp)

    async def _post_to_community(
        self,
        content: Optional[str],
        community_id: Optional[str]
    ) -> ToolResult:
        """Post a tweet to an X Community."""
        import asyncio

        if not content:
            return ToolResult(success=False, error="Tweet content is required")
        if not community_id:
            return ToolResult(success=False, error="community_id (name or numeric ID) is required")

        if len(content) > 280:
            return ToolResult(
                success=False,
                error=f"Tweet too long ({len(content)} chars). Max is 280."
            )

        # Resolve community name to numeric ID if needed
        resolved_id = await self._resolve_community_id(community_id)
        if not resolved_id:
            return ToolResult(
                success=False,
                error=f"Could not find community: '{community_id}'. "
                       "Try using the numeric community ID directly."
            )

        def _do_post():
            oauth = self._get_oauth1_session()
            resp = oauth.post(
                f"{self.api_base}/tweets",
                json={"text": content, "community_id": resolved_id}
            )
            return resp

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _do_post)

        if resp.status_code in (200, 201):
            data = resp.json()
            tweet_id = data.get("data", {}).get("id", "unknown")
            logger.info(f"Tweet posted to community {resolved_id}: {tweet_id}")
            return ToolResult(
                success=True,
                output=f"Posted to X Community ({community_id}). Tweet ID: {tweet_id}",
                metadata={"tweet_id": tweet_id, "community_id": resolved_id}
            )
        else:
            return self._handle_error(resp)

    async def _resolve_community_id(self, name_or_id: str) -> Optional[str]:
        """Resolve a community name to its numeric ID.

        If name_or_id is already numeric, return as-is.
        Otherwise, check cache first, then search X API.
        Caches results for future lookups.
        """
        import asyncio

        # Already a numeric ID
        if name_or_id.isdigit():
            return name_or_id

        # Check cache
        cache = self._load_community_cache()
        cache_key = name_or_id.lower().strip()
        if cache_key in cache:
            logger.info(f"Community cache hit: '{cache_key}' → {cache[cache_key]}")
            return cache[cache_key]

        # Search X API for community
        def _do_search():
            oauth = self._get_oauth1_session()
            resp = oauth.get(
                f"{self.api_base}/communities/search",
                params={
                    "query": name_or_id,
                    "max_results": 5,
                    "community.fields": "name,description,member_count"
                }
            )
            return resp

        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, _do_search)

            if resp.status_code != 200:
                logger.warning(f"Community search failed ({resp.status_code}): {resp.text}")
                return None

            data = resp.json()
            communities = data.get("data", [])

            if not communities:
                logger.warning(f"No communities found for: '{name_or_id}'")
                return None

            # Find best match — exact name match first, otherwise first result
            search_lower = name_or_id.lower().strip()
            best = None
            for c in communities:
                if c.get("name", "").lower().strip() == search_lower:
                    best = c
                    break
            if not best:
                best = communities[0]

            community_id = best.get("id")
            community_name = best.get("name", name_or_id)

            if community_id:
                # Cache for future use
                cache[cache_key] = community_id
                cache[community_name.lower().strip()] = community_id
                self._save_community_cache(cache)
                logger.info(f"Community resolved: '{name_or_id}' → {community_id} ({community_name})")

            return community_id

        except Exception as e:
            logger.error(f"Community search error: {e}")
            return None

    def _load_community_cache(self) -> Dict[str, str]:
        """Load community name → ID cache from JSON file."""
        if not self.communities_cache_file.exists():
            return {}
        try:
            with open(self.communities_cache_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_community_cache(self, cache: Dict[str, str]):
        """Save community cache to JSON file."""
        self.communities_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.communities_cache_file, 'w') as f:
            json.dump(cache, f, indent=2)

    def _handle_error(self, resp) -> ToolResult:
        """Handle X API error response."""
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
        import asyncio

        if not tweet_id:
            return ToolResult(success=False, error="tweet_id is required")

        def _do_delete():
            oauth = self._get_oauth1_session()
            return oauth.delete(f"{self.api_base}/tweets/{tweet_id}")

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _do_delete)

        if resp.status_code == 200:
            logger.info(f"Tweet deleted: {tweet_id}")
            return ToolResult(
                success=True,
                output=f"Tweet {tweet_id} deleted."
            )
        else:
            return self._handle_error(resp)

    async def _retweet(self, tweet_id: Optional[str]) -> ToolResult:
        """Retweet a tweet."""
        import asyncio

        if not tweet_id:
            return ToolResult(success=False, error="tweet_id is required for retweet")

        # Get authenticated user ID (required for retweet endpoint)
        user_id = await self._get_me()
        if not user_id:
            return ToolResult(success=False, error="Could not determine authenticated User ID (required for retweet)")

        def _do_retweet():
            oauth = self._get_oauth1_session()
            # POST /2/users/:id/retweets
            # Body: {"tweet_id": "..."}
            resp = oauth.post(
                f"{self.api_base}/users/{user_id}/retweets",
                json={"tweet_id": tweet_id}
            )
            return resp

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _do_retweet)

        if resp.status_code in (200, 201):
            data = resp.json()
            rt_status = data.get("data", {}).get("retweeted", False)
            return ToolResult(
                success=True,
                output=f"Retweeted tweet {tweet_id}",
                metadata={"retweeted": rt_status}
            )
        else:
            return self._handle_error(resp)

    async def _quote_tweet(
        self,
        tweet_id: Optional[str],
        content: str,
        community_id: Optional[str] = None
    ) -> ToolResult:
        """Quote a tweet (with optional community support)."""
        import asyncio

        if not tweet_id:
            return ToolResult(success=False, error="tweet_id is required for quote_tweet")
        if not content:
            return ToolResult(success=False, error="content is required for quote_tweet")

        payload = {
            "text": content,
            "quote_tweet_id": tweet_id
        }

        # If posting to community, resolve ID
        resolved_community_id = None
        if community_id:
            resolved_community_id = await self._resolve_community_id(community_id)
            if not resolved_community_id:
                 return ToolResult(
                    success=False,
                    error=f"Could not resolve community: {community_id}"
                )
            payload["community_id"] = resolved_community_id

        def _do_quote():
            oauth = self._get_oauth1_session()
            resp = oauth.post(
                f"{self.api_base}/tweets",
                json=payload
            )
            return resp

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _do_quote)

        if resp.status_code in (200, 201):
            data = resp.json()
            new_id = data.get("data", {}).get("id", "unknown")
            target = f"Community {resolved_community_id}" if resolved_community_id else "Timeline"
            return ToolResult(
                success=True,
                output=f"Quote Tweet posted to {target}. ID: {new_id}",
                metadata={"tweet_id": new_id}
            )
        else:
            return self._handle_error(resp)

    async def _get_me(self) -> Optional[str]:
        """Get authenticated user ID (cached)."""
        import asyncio

        # Check cache
        if self.user_cache_file.exists():
            try:
                with open(self.user_cache_file, 'r') as f:
                    data = json.load(f)
                    return data.get("id")
            except Exception:
                pass

        # Fetch from API
        def _fetch_me():
            oauth = self._get_oauth1_session()
            return oauth.get(f"{self.api_base}/users/me")

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _fetch_me)

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            user_id = data.get("id")
            if user_id:
                # Cache it
                self.user_cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.user_cache_file, 'w') as f:
                    json.dump(data, f)
                return user_id
        
        logger.error(f"Failed to fetch user ID: {resp.status_code} {resp.text}")
        return None
