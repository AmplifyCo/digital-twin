"""Gemini client via LiteLLM — supports both text and tool-use calls.

Used for:
- Intent parsing (cheap, fast, 1M context window)
- Simple/trivial chat responses
- Fallback when Claude hits rate limits (including tool use)
- Agent loop fallback when Claude is unavailable

Supports:
- Plain text generation
- Tool/function calling via LiteLLM translation
"""

import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class GeminiContentBlock:
    """Mimics anthropic ContentBlock interface."""
    type: str = "text"
    text: str = ""


@dataclass
class GeminiToolUseBlock:
    """Mimics anthropic ToolUseBlock for tool calls."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeminiUsage:
    """Mimics anthropic Usage interface."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class GeminiResponse:
    """Mimics anthropic.types.Message so ConversationManager needs no changes.

    Callers access: response.content[0].text, response.stop_reason, response.usage
    """
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: GeminiUsage = field(default_factory=GeminiUsage)


class GeminiClient:
    """LiteLLM-based Gemini client with Anthropic-compatible response format."""

    def __init__(self, api_key: str):
        """Initialize Gemini client.

        Args:
            api_key: Google AI API key (from aistudio.google.com/apikey)
        """
        self.api_key = api_key
        self.enabled = bool(api_key)

        if self.enabled:
            # LiteLLM reads GEMINI_API_KEY from environment
            os.environ["GEMINI_API_KEY"] = api_key
            logger.info("✨ Gemini Flash client initialized (intent + chat + tool fallback)")
        else:
            logger.info("Gemini client disabled (no GEMINI_API_KEY)")

    def _convert_tools_for_litellm(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Anthropic tool format to OpenAI/LiteLLM function format.

        Anthropic format:
            {"name": "x", "description": "y", "input_schema": {"type": "object", "properties": {...}}}

        OpenAI/LiteLLM format:
            {"type": "function", "function": {"name": "x", "description": "y", "parameters": {...}}}
        """
        litellm_tools = []
        for tool in tools:
            litellm_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                }
            })
        return litellm_tools

    def _convert_messages_for_litellm(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Anthropic-format messages to OpenAI/LiteLLM format.

        Handles:
        - Plain text messages (pass through)
        - Tool-use content blocks → assistant function calls
        - Tool-result content blocks → tool response messages
        """
        litellm_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                litellm_messages.append({"role": role, "content": content})

            elif isinstance(content, list):
                # Process Anthropic content blocks
                text_parts = []
                tool_calls = []
                tool_results = []

                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")

                        if block_type == "text":
                            text_parts.append(block.get("text", ""))

                        elif block_type == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })

                        elif block_type == "tool_result":
                            result_content = block.get("content", "")
                            if isinstance(result_content, list):
                                result_content = " ".join(
                                    b.get("text", "") for b in result_content
                                    if isinstance(b, dict) and b.get("type") == "text"
                                )
                            tool_results.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": str(result_content)
                            })
                    else:
                        # Handle anthropic SDK objects (ContentBlock, ToolUseBlock, etc.)
                        block_type = getattr(block, "type", "")

                        if block_type == "text":
                            text_parts.append(getattr(block, "text", ""))

                        elif block_type == "tool_use":
                            tool_calls.append({
                                "id": getattr(block, "id", ""),
                                "type": "function",
                                "function": {
                                    "name": getattr(block, "name", ""),
                                    "arguments": json.dumps(getattr(block, "input", {}))
                                }
                            })

                # Add text + tool calls as assistant message
                if tool_calls:
                    msg_data = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None,
                        "tool_calls": tool_calls
                    }
                    litellm_messages.append(msg_data)
                elif text_parts:
                    litellm_messages.append({"role": role, "content": " ".join(text_parts)})

                # Add tool results as separate messages
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
    ) -> GeminiResponse:
        """Send a message to Gemini and return Anthropic-compatible response.

        Supports both plain text and tool-use calls.

        Args:
            model: LiteLLM model string e.g. "gemini/gemini-2.0-flash"
            messages: Conversation messages (Anthropic or OpenAI format)
            system: System prompt (prepended as system role message)
            max_tokens: Max tokens to generate
            tools: Optional tool definitions (Anthropic format)

        Returns:
            GeminiResponse with .content, .stop_reason, .usage
        """
        try:
            import litellm
            litellm.suppress_debug_info = True

            # Build messages for LiteLLM
            litellm_messages = []
            if system:
                litellm_messages.append({"role": "system", "content": system})

            converted = self._convert_messages_for_litellm(messages)
            litellm_messages.extend(converted)

            if not litellm_messages:
                return GeminiResponse(
                    content=[GeminiContentBlock(text="")],
                    stop_reason="end_turn"
                )

            # Build kwargs for LiteLLM
            call_kwargs = {
                "model": model,
                "messages": litellm_messages,
                "max_tokens": max_tokens,
                "api_key": self.api_key,
            }

            # Add tools if provided
            if tools:
                call_kwargs["tools"] = self._convert_tools_for_litellm(tools)

            response = await litellm.acompletion(**call_kwargs)

            choice = response.choices[0]
            message = choice.message
            finish_reason = choice.finish_reason or "stop"
            usage = response.usage

            logger.info(
                f"Gemini ({model}): {getattr(usage, 'prompt_tokens', 0)} in / "
                f"{getattr(usage, 'completion_tokens', 0)} out"
            )

            # Check if Gemini wants to call tools
            if hasattr(message, 'tool_calls') and message.tool_calls:
                content_blocks = []

                # Add any text content first
                if message.content:
                    content_blocks.append(GeminiContentBlock(type="text", text=message.content))

                # Add tool use blocks
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    except (json.JSONDecodeError, AttributeError):
                        args = {}

                    content_blocks.append(GeminiToolUseBlock(
                        type="tool_use",
                        id=tc.id or f"toolu_gemini_{id(tc)}",
                        name=tc.function.name,
                        input=args
                    ))

                return GeminiResponse(
                    content=content_blocks,
                    stop_reason="tool_use",
                    usage=GeminiUsage(
                        input_tokens=getattr(usage, "prompt_tokens", 0),
                        output_tokens=getattr(usage, "completion_tokens", 0),
                    ),
                )

            # Plain text response
            text = message.content or ""
            return GeminiResponse(
                content=[GeminiContentBlock(type="text", text=text)],
                stop_reason="end_turn" if finish_reason == "stop" else "max_tokens",
                usage=GeminiUsage(
                    input_tokens=getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                ),
            )

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    async def test_connection(self) -> bool:
        """Test if Gemini API is reachable.

        Returns:
            True if connection successful
        """
        try:
            response = await self.create_message(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            return bool(response.content)
        except Exception as e:
            logger.error(f"Gemini connection test failed: {e}")
            return False
