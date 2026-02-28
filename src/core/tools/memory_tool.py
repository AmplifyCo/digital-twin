"""Memory Query Tool — gives the agent mid-task access to Nova's memory.

Without this, the agent gets memory context once at the start (system prompt)
and can't query it during multi-turn execution. With this tool, the agent can:
  - "What happened last time I tried to post on LinkedIn?" (episodes)
  - "What do I know about John?" (context/contacts)
  - "How does the principal write?" (style)
  - "What went wrong with web_search before?" (failures)

Security: READ-only. No writes to memory. No raw PII — results are already
filtered by VectorDatabase's storage policies (trimmed, redacted).
"""

import logging
from typing import Optional

from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class MemoryQueryTool(BaseTool):
    """Search Nova's memory during task execution."""

    name = "memory_query"
    description = (
        "Search Nova's memory for relevant information. Use this to recall:\n"
        "• 'episodes' — past events and outcomes ('what happened when I emailed John?')\n"
        "• 'context' — the principal's preferences, contacts, conversation history\n"
        "• 'style' — how the principal writes (for matching voice in content)\n"
        "• 'failures' — what went wrong with a specific tool before\n"
        "Always use this before composing content (to check style) or contacting someone (to check history)."
    )

    parameters = {
        "operation": {
            "type": "string",
            "description": (
                "What to search: 'episodes' (past events), 'context' (preferences/contacts), "
                "'style' (writing voice), 'failures' (tool error history)"
            ),
            "enum": ["episodes", "context", "style", "failures"],
        },
        "query": {
            "type": "string",
            "description": (
                "What to search for. Examples: 'LinkedIn posts', 'emails to John', "
                "'web_search', 'communication preferences'"
            ),
        },
    }

    def __init__(self):
        self.brain = None  # DigitalCloneBrain — injected by registry.set_memory_sources()
        self.episodic_memory = None  # EpisodicMemory — injected by registry.set_memory_sources()

    async def execute(
        self,
        operation: str,
        query: str = "",
        **kwargs,
    ) -> ToolResult:
        """Execute a memory query."""
        if not query:
            return ToolResult(success=False, error="Query is required")

        try:
            if operation == "episodes":
                return await self._recall_episodes(query)
            elif operation == "context":
                return await self._recall_context(query)
            elif operation == "style":
                return await self._recall_style(query)
            elif operation == "failures":
                return await self._recall_failures(query)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as e:
            logger.warning(f"MemoryQueryTool error: {e}")
            return ToolResult(success=False, error=f"Memory search failed: {str(e)}")

    async def _recall_episodes(self, query: str) -> ToolResult:
        """Search episodic memory for past events and outcomes."""
        if not self.episodic_memory:
            return ToolResult(success=True, output="No episodic memory available.")

        result = await self.episodic_memory.recall(query=query, n=5, days_back=90)
        if not result:
            return ToolResult(success=True, output=f"No past episodes found for: {query}")
        return ToolResult(success=True, output=result)

    async def _recall_context(self, query: str) -> ToolResult:
        """Search brain for preferences, contacts, and conversation context."""
        if not self.brain:
            return ToolResult(success=True, output="No brain context available.")

        if hasattr(self.brain, 'get_relevant_context'):
            context = await self.brain.get_relevant_context(query, max_results=5)
            if not context:
                return ToolResult(success=True, output=f"No context found for: {query}")
            return ToolResult(success=True, output=context)

        return ToolResult(success=True, output="Brain does not support context queries.")

    async def _recall_style(self, query: str) -> ToolResult:
        """Search identity/style memory for communication patterns."""
        if not self.brain or not hasattr(self.brain, 'identity'):
            return ToolResult(success=True, output="No style memory available.")

        results = await self.brain.identity.search(
            query=f"communication_style {query}",
            n_results=3,
            filter_metadata={"type": "communication_style"},
        )
        if not results:
            return ToolResult(
                success=True,
                output=f"No style examples found for: {query}. The principal hasn't approved any posts yet.",
            )

        examples = "\n\n---\n\n".join(r["text"][:500] for r in results)
        return ToolResult(
            success=True,
            output=f"STYLE EXAMPLES ({len(results)} found):\n\n{examples}",
        )

    async def _recall_failures(self, query: str) -> ToolResult:
        """Search for past failures with a specific tool."""
        if not self.episodic_memory:
            return ToolResult(success=True, output="No episodic memory available.")

        failures = await self.episodic_memory.recall_failures(tool=query, n=5)
        if not failures:
            return ToolResult(
                success=True,
                output=f"No recorded failures for tool: {query}",
            )

        lines = [f"PAST FAILURES with '{query}':"]
        for f in failures:
            lines.append(f"  • {f}")
        return ToolResult(success=True, output="\n".join(lines))
