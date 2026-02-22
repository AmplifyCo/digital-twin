"""Goal decomposer — breaks a high-level goal into concrete, executable subtasks.

Uses Gemini Flash for cheap, fast structured planning before execution starts.

Design principles (from AOP research + Voyager):
  - Solvability: each subtask must be independently executable with available tools
  - Completeness: subtasks together fully accomplish the goal
  - Non-redundancy: no overlapping subtasks
  - Bounded: max 7 subtasks to prevent over-decomposition
  - Synthesis-last: final subtask always aggregates and writes a file
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from .task_queue import Subtask

logger = logging.getLogger(__name__)

_BOT_NAME = os.getenv("BOT_NAME", "Nova")

_DECOMPOSE_PROMPT = f"""You are a task planner for an autonomous AI agent named {_BOT_NAME}.
Your job: break a high-level goal into 3–7 concrete, sequential subtasks.

RULES:
1. Each subtask must be independently executable — it must have a clear single output
2. No redundant subtasks — don't repeat the same search with different wording
3. Max 7 subtasks total
4. Subtasks must be in execution order (earlier results feed into later ones)
5. The LAST subtask must always be a synthesis step: "Compile all findings into a file at ./data/tasks/{task_id}.txt and summarize in 3 bullet points"
6. Use ONLY tools from the Available Tools list
7. Assign model_tier: "flash" for searches/reads, "sonnet" for synthesis/writing

Available Tools: {tools}

Goal: {goal}

Respond ONLY with a JSON array. No explanation, no markdown fences.
Example format:
[
  {{"description": "Search X for posts about OpenClaw using x_tool search_tweets", "tool_hints": ["x_tool"], "model_tier": "flash"}},
  {{"description": "Search web for 'OpenClaw autonomous agent flaws reviews 2025'", "tool_hints": ["web_search"], "model_tier": "flash"}},
  {{"description": "Fetch the OpenClaw GitHub README from https://github.com/openclaw/openclaw", "tool_hints": ["web_fetch"], "model_tier": "flash"}},
  {{"description": "Compile all findings into ./data/tasks/{task_id}.txt with summary", "tool_hints": ["file_operations"], "model_tier": "sonnet"}}
]"""

# Fallback decomposition used when Gemini Flash is unavailable
_FALLBACK_SUBTASKS = [
    Subtask(description="Search the web for information about the requested topic", tool_hints=["web_search"], model_tier="flash"),
    Subtask(description="Compile findings and write a summary file at ./data/tasks/result.txt", tool_hints=["file_operations"], model_tier="sonnet"),
]


class GoalDecomposer:
    """Breaks a high-level goal into concrete subtasks using Gemini Flash.

    Falls back gracefully to a 2-step default if Gemini is unavailable.
    """

    def __init__(self, gemini_client=None):
        """
        Args:
            gemini_client: GeminiClient (LiteLLM wrapper). If None, uses fallback decomposition.
        """
        self.gemini_client = gemini_client
        self._model = "gemini/gemini-2.0-flash"

    async def decompose(
        self,
        goal: str,
        task_id: str,
        available_tools: Optional[List[str]] = None,
    ) -> List[Subtask]:
        """Decompose a goal into ordered subtasks.

        Args:
            goal: The high-level goal to accomplish
            task_id: Task ID (injected into the synthesis step file path)
            available_tools: List of registered tool names (for the planner prompt)

        Returns:
            List of Subtask objects ready for sequential execution
        """
        tools_str = ", ".join(available_tools or ["web_search", "file_operations", "x_tool", "web_fetch"])

        if not self.gemini_client or not self.gemini_client.enabled:
            logger.warning("GoalDecomposer: Gemini unavailable, using fallback decomposition")
            return self._make_fallback(goal, task_id)

        prompt = _DECOMPOSE_PROMPT.format(
            tools=tools_str,
            goal=goal,
            task_id=task_id,
        )

        try:
            # Single call to Gemini Flash — no tools needed, just JSON output
            response = await self.gemini_client.create_message(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )

            # Extract text from response
            text = self._extract_text(response)
            if not text:
                logger.warning("GoalDecomposer: empty response, using fallback")
                return self._make_fallback(goal, task_id)

            subtasks = self._parse_json(text, task_id)
            if not subtasks:
                return self._make_fallback(goal, task_id)

            logger.info(f"GoalDecomposer: decomposed into {len(subtasks)} subtasks for goal: {goal[:60]}")
            for i, st in enumerate(subtasks):
                logger.debug(f"  Subtask {i+1}: {st.description[:80]} [{st.model_tier}]")
            return subtasks

        except Exception as e:
            logger.error(f"GoalDecomposer error: {e}", exc_info=True)
            return self._make_fallback(goal, task_id)

    def _parse_json(self, text: str, task_id: str) -> List[Subtask]:
        """Parse JSON array from LLM response into Subtask objects."""
        # Strip markdown fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

        try:
            items: List[Dict[str, Any]] = json.loads(text)
            if not isinstance(items, list) or len(items) == 0:
                return []

            subtasks = []
            for item in items[:7]:  # cap at 7
                desc = item.get("description", "").strip()
                if not desc:
                    continue
                subtasks.append(Subtask(
                    description=desc,
                    tool_hints=item.get("tool_hints", []),
                    model_tier=item.get("model_tier", "flash"),
                    status="pending",
                ))

            # Ensure synthesis step mentions the task_id file path
            if subtasks:
                last = subtasks[-1]
                if "./data/tasks/" not in last.description:
                    last.description = f"Compile all findings into ./data/tasks/{task_id}.txt and summarize in 3 bullet points"
                    last.tool_hints = ["file_operations"]
                    last.model_tier = "sonnet"

            return subtasks

        except json.JSONDecodeError as e:
            logger.warning(f"GoalDecomposer: JSON parse error: {e} — text was: {text[:200]}")
            return []

    def _make_fallback(self, goal: str, task_id: str) -> List[Subtask]:
        """Minimal 2-step plan for when Gemini is unavailable."""
        return [
            Subtask(
                description=f"Research the following using web_search and web_fetch: {goal}",
                tool_hints=["web_search", "web_fetch"],
                model_tier="flash",
            ),
            Subtask(
                description=f"Compile all findings into ./data/tasks/{task_id}.txt and summarize in 3 bullet points",
                tool_hints=["file_operations"],
                model_tier="sonnet",
            ),
        ]

    def _extract_text(self, response) -> str:
        """Extract text content from an LLM response object."""
        if hasattr(response, "content"):
            parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "\n".join(parts)
        if isinstance(response, str):
            return response
        return ""
