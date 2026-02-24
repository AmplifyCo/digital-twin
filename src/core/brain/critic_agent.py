"""Critic Agent — validates background task results before delivery.

Inspired by arXiv:2507.01446 (multi-agent hallucination mitigation) and
arXiv:2507.02004 / STELLA (self-evolving agent with critic feedback loop).

Runs after all subtasks complete in TaskRunner. Evaluates whether the output
genuinely answers the goal, then either:
  1. Passes → delivers result to user as-is
  2. Fails → runs one refinement pass with targeted hint, then delivers

Design principles:
  - Fail-open: any LLM error returns passed=True (never block delivery)
  - Gemini Flash only (fast, cheap — ~1-2s overhead per task)
  - One refinement pass max (avoid infinite loops)
  - Score threshold = 0.75 (balanced; not too strict, not too lenient)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_CRITIC_PROMPT = """You are a quality critic for an AI agent's task output.

GOAL: {goal}

TASK OUTPUT (from sequential execution steps):
{results_text}

Evaluate whether the output genuinely answers the goal:
1. Does it directly address what was asked?
2. Are factual claims grounded in the search/fetch results shown?
3. Is the output complete enough to be useful?

Respond ONLY with valid JSON, no markdown, no explanation:
{{"passed": true_or_false, "score": 0.0_to_1.0, "issues": ["issue1", "issue2"], "refinement_hint": "one sentence on what to improve, or empty string if passed"}}

Score guide: 0.9+ = excellent, 0.75+ = acceptable, below 0.75 = needs improvement.
Be fair but critical. If the output is reasonable even if imperfect, score ≥ 0.75."""

_REFINE_PROMPT = """You are synthesizing the final answer for a completed research task.

GOAL: {goal}

PREVIOUS RESULTS (from task execution):
{results_text}

FEEDBACK FROM QUALITY CHECK:
{hint}

Using the information already gathered above, produce an improved, complete answer
that directly addresses the goal. Be concise and factual. Do not invent information
not present in the results above."""


@dataclass
class CriticResult:
    passed: bool
    score: float
    issues: List[str] = field(default_factory=list)
    refinement_hint: str = ""


class CriticAgent:
    """Validates task outputs before user delivery and triggers refinement when needed."""

    PASS_THRESHOLD = 0.75
    MAX_RESULTS_CHARS = 2000  # cap to avoid huge prompts

    def __init__(self, gemini_client=None, anthropic_client=None):
        """
        Args:
            gemini_client: GeminiClient for fast critic evaluation (Flash).
            anthropic_client: AnthropicClient for Sonnet-quality refinement (optional;
                              falls back to gemini_client if not provided).
        """
        self.gemini_client = gemini_client
        self.anthropic_client = anthropic_client
        logger.info("CriticAgent initialized")

    async def evaluate(
        self,
        goal: str,
        subtasks: list,
        results: List[str],
    ) -> CriticResult:
        """Evaluate task output quality.

        Args:
            goal: The original high-level task goal.
            subtasks: List of Subtask objects (for context; not used in prompt directly).
            results: List of per-subtask result strings from TaskRunner.

        Returns:
            CriticResult — always returns a valid result (fail-open on errors).
        """
        if not self.gemini_client or not self.gemini_client.enabled:
            logger.debug("CriticAgent: Gemini unavailable — skipping evaluation (pass-through)")
            return CriticResult(passed=True, score=1.0)

        results_text = self._format_results(results)

        prompt = _CRITIC_PROMPT.format(
            goal=goal[:300],
            results_text=results_text,
        )

        try:
            response = await self.gemini_client.create_message(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            text = self._extract_text(response)
            return self._parse_critic_response(text)

        except Exception as e:
            logger.warning(f"CriticAgent evaluate error (passing through): {e}")
            return CriticResult(passed=True, score=1.0)

    async def refine(
        self,
        goal: str,
        results: List[str],
        hint: str,
    ) -> Optional[str]:
        """Run one refinement pass using the critic's feedback hint.

        Uses Sonnet if available (better synthesis), falls back to Gemini Flash.

        Args:
            goal: The original task goal.
            results: Per-subtask results from TaskRunner.
            hint: The refinement_hint from CriticResult.

        Returns:
            Refined answer string, or None if refinement fails.
        """
        results_text = self._format_results(results)

        prompt = _REFINE_PROMPT.format(
            goal=goal[:300],
            results_text=results_text,
            hint=hint,
        )

        # Prefer Sonnet for synthesis quality; fall back to Flash
        client = self.anthropic_client if (self.anthropic_client and self.anthropic_client.enabled) else self.gemini_client

        if not client or not client.enabled:
            logger.warning("CriticAgent refine: no LLM client available")
            return None

        try:
            if client is self.anthropic_client:
                import anthropic
                response = await client.create_message(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2048,
                )
            else:
                response = await client.create_message(
                    model="gemini/gemini-2.0-flash",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2048,
                )

            refined = self._extract_text(response)
            logger.info(f"CriticAgent refinement produced {len(refined)} chars")
            return refined if refined else None

        except Exception as e:
            logger.warning(f"CriticAgent refine error: {e}")
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_results(self, results: List[str]) -> str:
        """Format the last 3 subtask results, capped at MAX_RESULTS_CHARS."""
        recent = results[-3:] if len(results) > 3 else results
        text = "\n\n".join(recent)
        if len(text) > self.MAX_RESULTS_CHARS:
            text = text[: self.MAX_RESULTS_CHARS] + "\n...[truncated]"
        return text

    def _parse_critic_response(self, text: str) -> CriticResult:
        """Parse the JSON critic response into a CriticResult."""
        text = text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

        try:
            data = json.loads(text)
            score = float(data.get("score", 0.5))
            passed = bool(data.get("passed", score >= self.PASS_THRESHOLD))
            # Override passed based on threshold to be consistent
            if score < self.PASS_THRESHOLD:
                passed = False
            return CriticResult(
                passed=passed,
                score=score,
                issues=data.get("issues", []),
                refinement_hint=data.get("refinement_hint", ""),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"CriticAgent: failed to parse response: {e} — text: {text[:200]}")
            # Fail-open: treat as passed
            return CriticResult(passed=True, score=0.8)

    def _extract_text(self, response) -> str:
        """Extract text from an LLM response object."""
        if hasattr(response, "content"):
            parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "\n".join(parts)
        if isinstance(response, str):
            return response
        return ""
