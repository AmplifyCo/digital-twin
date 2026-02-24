"""Grok client via LiteLLM — supports both text and tool-use calls.

Used for:
- Fallback when Claude or Gemini is unavailable
- Supports tiers: flash, haiku, sonnet, quality mapped to Grok models

Supports:
- Plain text generation
- Tool/function calling via LiteLLM translation
"""

import os
import json
import logging
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class GrokContentBlock:
    """Mimics anthropic ContentBlock interface."""
    type: str = "text"
    text: str = ""


@dataclass
class GrokToolUseBlock:
    """Mimics anthropic ToolUseBlock for tool calls."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrokUsage:
    """Mimics anthropic Usage interface."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class GrokResponse:
    """Mimics anthropic.types.Message so ConversationManager needs no changes.

    Callers access: response.content[0].text, response.stop_reason, response.usage
    """
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: GrokUsage = field(default_factory=GrokUsage)


class GrokClient:
    """LiteLLM-based client for Grok (xAI) models.

    All LLM calls go through LiteLLM for seamless provider switching.
    Model strings: "xai/grok-beta", etc.
    """

    def __init__(self, api_key: str):
        """Initialize LiteLLM client for Grok.

        Args:
            api_key: xAI API key
        """
        self.api_key = api_key
        self.enabled = bool(api_key)

        if self.enabled:
            os.environ["XAI_API_KEY"] = api_key
            logger.info("✨ LiteLLM client initialized for Grok")
        else:
            logger.info("Grok client disabled (no XAI_API_KEY)")

    # Fields that Grok function declarations support (assuming similar to OpenAI)
    _GROK_ALLOWED_FIELDS = {
        "type", "description", "properties", "required", "items",
        "nullable", "format"
    }

    def _sanitize_schema(self, schema: Any, _depth: int = 0) -> Any:
        """Recursively sanitize JSON schema for Grok/LiteLLM compatibility."""
        # Similar implementation as in gemini_client.py
        if schema is None or isinstance(schema, (str, int, float, bool)):
            return schema

        if isinstance(schema, list):
            return [self._sanitize_schema(item, _depth + 1) for item in schema]

        if isinstance(schema, dict):
            sanitized = {}
            for k, v in schema.items():
                if k in ("anyOf", "allOf", "oneOf", "enum", "default",
                         "title", "examples", "$ref", "$schema",
                         "additionalProperties", "minItems", "maxItems",
                         "minimum", "maximum", "pattern", "minLength",
                         "maxLength", "exclusiveMinimum", "exclusiveMaximum"):
                    continue

                if k == "properties" and isinstance(v, dict):
                    prop_dict = {}
                    for pk, pv in v.items():
                        cleaned = self._sanitize_schema(pv, _depth + 1)
                        if isinstance(cleaned, dict) and cleaned.get("type") == "object" and "properties" in cleaned:
                            prop_dict[pk] = {
                                "type": "string",
                                "description": cleaned.get("description", f"JSON string for {pk}")
                            }
                        else:
                            prop_dict[pk] = cleaned
                    sanitized[k] = prop_dict
                else:
                    sanitized[k] = self._sanitize_schema(v, _depth + 1)

            return sanitized

        return schema

    def _convert_tools_for_litellm(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Anthropic tool format to OpenAI/LiteLLM function format."""
        litellm_tools = []
        for tool in tools:
            raw_schema = tool.get("input_schema", {})
            safe_schema = self._sanitize_schema(raw_schema)
            
            litellm_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": safe_schema
                }
            })
        return litellm_tools

    def _convert_messages_for_litellm(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Anthropic-format messages to OpenAI/LiteLLM format."""
        litellm_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                litellm_messages.append({"role": role, "content": content})

            elif isinstance(content, list):
                text_parts = []
                tool_calls = []
                tool_results = []

                for block in content:
                    block_type = block.get("type", "") if isinstance(block, dict) else getattr(block, "type", "")

                    if block_type == "text":
                        text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                        text_parts.append(text)

                    elif block_type == "tool_use":
                        input_data = block.get("input", {}) if isinstance(block, dict) else getattr(block, "input", {})
                        tool_calls.append({
                            "id": block.get("id", "") if isinstance(block, dict) else getattr(block, "id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", "") if isinstance(block, dict) else getattr(block, "name", ""),
                                "arguments": json.dumps(input_data)
                            }
                        })

                    elif block_type == "tool_result":
                        result_content = block.get("content", "") if isinstance(block, dict) else getattr(block, "content", "")
                        if isinstance(result_content, list):
                            result_content = " ".join(b.get("text", "") for b in result_content if isinstance(b, dict) and b.get("type") == "text")
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", "") if isinstance(block, dict) else getattr(block, "tool_use_id", ""),
                            "content": str(result_content)
                        })

                if tool_calls:
                    msg_data = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None,
                        "tool_calls": tool_calls
                    }
                    litellm_messages.append(msg_data)
                elif text_parts:
                    litellm_messages.append({"role": role, "content": " ".join(text_parts)})

                for tr in tool_results:
                    litellm_messages.append(tr)

        return litellm_messages

    async def create_message(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> GrokResponse:
        """Send a message to Grok and return Anthropic-compatible response."""
        try:
            import litellm
            litellm.suppress_debug_info = True
            from litellm.exceptions import RateLimitError

            max_retries = 3
            base_delay = 2.0

            litellm_messages = []
            if system:
                litellm_messages.append({"role": "system", "content": system})

            converted = self._convert_messages_for_litellm(messages)
            litellm_messages.extend(converted)

            if not litellm_messages:
                return GrokResponse(
                    content=[GrokContentBlock(text="")],
                    stop_reason="end_turn"
                )

            call_kwargs = {
                "model": model,
                "messages": litellm_messages,
                "max_tokens": max_tokens,
                "api_key": self.api_key
            }

            if tools:
                call_kwargs["tools"] = self._convert_tools_for_litellm(tools)

            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    response = await litellm.acompletion(**call_kwargs)
                    break
                except Exception as e:
                    last_exception = e
                    is_rate_limit = "429" in str(e) or "Resource exhausted" in str(e) or isinstance(e, RateLimitError)
                    if is_rate_limit and attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Grok Rate Limit ({model}). Retrying in {delay}s... (Attempt {attempt+1}/{max_retries})")
                        await asyncio.sleep(delay)
                    else:
                        raise e

            choice = response.choices[0]
            message = choice.message
            finish_reason = choice.finish_reason or "stop"
            usage = response.usage

            logger.info(
                f"Grok ({model}): {getattr(usage, 'prompt_tokens', 0)} in / "
                f"{getattr(usage, 'completion_tokens', 0)} out"
            )

            if hasattr(message, 'tool_calls') and message.tool_calls:
                content_blocks = []
                if message.content:
                    content_blocks.append(GrokContentBlock(type="text", text=message.content))

                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    except (json.JSONDecodeError, AttributeError):
                        args = {}

                    content_blocks.append(GrokToolUseBlock(
                        type="tool_use",
                        id=tc.id or f"toolu_grok_{id(tc)}",
                        name=tc.function.name,
                        input=args
                    ))

                return GrokResponse(
                    content=content_blocks,
                    stop_reason="tool_use",
                    usage=GrokUsage(
                        input_tokens=getattr(usage, "prompt_tokens", 0),
                        output_tokens=getattr(usage, "completion_tokens", 0),
                    ),
                )

            text = message.content or ""
            return GrokResponse(
                content=[GrokContentBlock(type="text", text=text)],
                stop_reason="end_turn" if finish_reason == "stop" else "max_tokens",
                usage=GrokUsage(
                    input_tokens=getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                ),
            )

        except Exception as e:
            logger.error(f"Grok API error: {e}")
            raise

    async def test_connection(self) -> bool:
        """Test if Grok API is reachable."""
        try:
            response = await self.create_message(
                model="xai/grok-beta",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            return len(response.content) > 0 and bool(response.content[0].text)
        except Exception as e:
            logger.error(f"Grok connection test failed: {e}")
            return False