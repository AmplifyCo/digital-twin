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

# Note: uses .format() at runtime — {bot_name}, {tools}, {goal}, {task_id} are runtime variables
_DECOMPOSE_PROMPT = """You are a task planner for an autonomous AI agent named {bot_name}.
Your job: break a high-level goal into 3–7 concrete, sequential subtasks.

RULES:
1. Each subtask must be independently executable — it must have a clear single output
2. No redundant subtasks — don't repeat the same search with different wording
3. Max 7 subtasks total
4. Subtasks must be in execution order (earlier results feed into later ones)
5. The LAST subtask must always be a synthesis step: "Compile all findings into a file at ./data/tasks/{task_id}.txt and summarize in 3 bullet points"
6. Use ONLY tools from the Available Tools list
7. Assign model_tier: "flash" for searches/reads, "sonnet" for synthesis/writing
8. For each subtask set verification_criteria: a one-sentence test for how to confirm it succeeded (e.g. "Search returns ≥3 results", "File exists at path", "Tweet ID is returned")
9. Set reversible: false for subtasks that CANNOT be undone (sending email, posting to X, deleting files, making purchases). Set true for reads, searches, writes to local files.

Available Tools: {tools}{tool_performance}

Goal: {goal}

Respond ONLY with a JSON array. No explanation, no markdown fences.
Example format:
[
  {{"description": "Search X for posts about OpenClaw using x_tool search_tweets", "tool_hints": ["x_tool"], "model_tier": "flash", "verification_criteria": "At least 3 relevant tweets returned", "reversible": true}},
  {{"description": "Search web for 'OpenClaw autonomous agent flaws reviews 2025'", "tool_hints": ["web_search"], "model_tier": "flash", "verification_criteria": "Search returns results with relevant content", "reversible": true}},
  {{"description": "Fetch the OpenClaw GitHub README from https://github.com/openclaw/openclaw", "tool_hints": ["web_fetch"], "model_tier": "flash", "verification_criteria": "Page content contains README text", "reversible": true}},
  {{"description": "Compile all findings into ./data/tasks/{task_id}.txt with summary", "tool_hints": ["file_operations"], "model_tier": "sonnet", "verification_criteria": "File exists at ./data/tasks/{task_id}.txt with content", "reversible": true}}
]"""

# Fallback decomposition used when Gemini Flash is unavailable (built in _make_fallback)


class GoalDecomposer:
    """Breaks a high-level goal into concrete subtasks using Gemini Flash.

    Falls back gracefully to a 2-step default if Gemini is unavailable.
    """

    def __init__(self, gemini_client=None, template_library=None):
        """
        Args:
            gemini_client: GeminiClient (LiteLLM wrapper). If None, uses fallback decomposition.
            template_library: ReasoningTemplateLibrary for reusing past decompositions.
        """
        self.gemini_client = gemini_client
        self.template_library = template_library
        self._model = "gemini/gemini-2.0-flash"

    async def decompose(
        self,
        goal: str,
        task_id: str,
        available_tools: Optional[List[str]] = None,
        tool_performance: Optional[Dict[str, Any]] = None,
    ) -> List[Subtask]:
        """Decompose a goal into ordered subtasks.

        Args:
            goal: The high-level goal to accomplish
            task_id: Task ID (injected into the synthesis step file path)
            available_tools: List of registered tool names (for the planner prompt)
            tool_performance: Dict of tool → success_rate from EpisodicMemory (optional)

        Returns:
            List of Subtask objects ready for sequential execution
        """
        tools_str = ", ".join(available_tools or ["web_search", "file_operations", "x_tool", "web_fetch"])

        if not self.gemini_client or not self.gemini_client.enabled:
            logger.warning("GoalDecomposer: Gemini unavailable, using fallback decomposition")
            return self._make_fallback(goal, task_id)

        # Query template library for similar past decompositions
        template_context = ""
        if self.template_library:
            try:
                templates = await self.template_library.query_similar(goal, top_k=2)
                if templates:
                    template_context = "\n\n" + self.template_library.format_for_prompt(templates) + "\n"
            except Exception as e:
                logger.debug(f"GoalDecomposer: template query failed (continuing without): {e}")

        # Build tool performance context for the planner
        tool_perf_str = ""
        if tool_performance:
            perf_lines = []
            for tool, stats in tool_performance.items():
                rate = stats.get("rate", 1.0)
                total = stats.get("total", 0)
                if total >= 3:  # Only show tools with enough data to be meaningful
                    label = "reliable" if rate >= 0.8 else ("flaky" if rate >= 0.5 else "unreliable")
                    perf_lines.append(f"  {tool}: {rate:.0%} success ({total} uses) — {label}")
            if perf_lines:
                tool_perf_str = "\n\nTool Performance (from past experience):\n" + "\n".join(perf_lines) + "\nPrefer reliable tools where possible."

        prompt = _DECOMPOSE_PROMPT.format(
            bot_name=_BOT_NAME,
            tools=tools_str,
            goal=goal,
            task_id=task_id,
            tool_performance=tool_perf_str,
        )
        if template_context:
            prompt = template_context + "\n" + prompt

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
                    verification_criteria=item.get("verification_criteria", ""),
                    reversible=item.get("reversible", True),
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
                verification_criteria="At least one search result or page content returned",
                reversible=True,
            ),
            Subtask(
                description=f"Compile all findings into ./data/tasks/{task_id}.txt and summarize in 3 bullet points",
                tool_hints=["file_operations"],
                model_tier="sonnet",
                verification_criteria=f"File exists at ./data/tasks/{task_id}.txt with content",
                reversible=True,
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
