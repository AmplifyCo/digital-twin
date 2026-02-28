"""Reasoning Context — structured symbolic signals for LLM reasoning.

LLM-driven symbolic AI: the LLM handles unstructured tasks, but structured
Python-derived signals (tone, risk, tool reliability, constraints) are injected
as "contracts" that shape its reasoning. The LLM sees WHY it should act a
certain way, not just instructions to follow blindly.

This is the bridge between rule-based systems (ToneAnalyzer, PolicyGate,
EpisodicMemory) and the LLM's reasoning capabilities.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReasoningContext:
    """Aggregates symbolic signals into a structured prompt block."""

    tone: str = ""
    risk: str = ""
    tool_reliability: str = ""
    constraints: str = ""
    memory_hits: str = ""

    @classmethod
    def build(
        cls,
        tone_signal=None,
        intent: Optional[Dict[str, Any]] = None,
        working_memory=None,
        tool_performance: Optional[Dict[str, Dict]] = None,
        brain_context_len: int = 0,
    ) -> "ReasoningContext":
        """Assemble from available signals. All parameters are optional.

        Args:
            tone_signal: ToneSignal from tone_analyzer.analyze()
            intent: Parsed intent dict (tool_hints, inferred_task)
            working_memory: WorkingMemory instance
            tool_performance: Dict from episodic_memory.get_tool_success_rates()
            brain_context_len: Length of brain context injected (proxy for memory confidence)

        Returns:
            ReasoningContext ready for to_prompt()
        """
        ctx = cls()
        intent = intent or {}

        # ── Tone signal ──────────────────────────────────────────────
        if tone_signal and hasattr(tone_signal, "register"):
            if tone_signal.register != "neutral":
                ctx.tone = (
                    f"{tone_signal.register} (urgency={tone_signal.urgency:.1f}). "
                    f"Reason: {tone_signal.note}"
                )

        # ── Risk assessment ──────────────────────────────────────────
        tool_hints = intent.get("tool_hints", [])
        # Import risk map lazily to avoid circular imports
        try:
            from src.core.nervous_system.policy_gate import TOOL_RISK_MAP, RiskLevel
            irreversible_tools = []
            for tool in tool_hints:
                tool_map = TOOL_RISK_MAP.get(tool, {})
                for op, risk in tool_map.items():
                    if op != "_default" and risk == RiskLevel.IRREVERSIBLE:
                        irreversible_tools.append(f"{tool}.{op}")
                if tool_map.get("_default") == RiskLevel.IRREVERSIBLE:
                    irreversible_tools.append(tool)
            if irreversible_tools:
                ctx.risk = f"HIGH — irreversible actions: {', '.join(irreversible_tools)}"
        except Exception:
            pass

        # ── Tool reliability ─────────────────────────────────────────
        if tool_performance:
            reliability_lines = []
            for tool in tool_hints:
                stats = tool_performance.get(tool)
                if stats:
                    rate = stats.get("rate", 1.0)
                    total = stats.get("total", 0)
                    label = "reliable" if rate >= 0.8 else ("flaky" if rate >= 0.5 else "unreliable")
                    reliability_lines.append(f"{tool}: {rate:.0%} success ({total} uses, {label})")
            if reliability_lines:
                ctx.tool_reliability = "; ".join(reliability_lines)

        # ── Active constraints from working memory ───────────────────
        if working_memory:
            parts = []
            cal = getattr(working_memory, "calibration", "")
            if cal:
                parts.append(f"Calibration: {cal}")
            tz = getattr(working_memory, "timezone_override", None)
            if tz:
                parts.append(f"Timezone: {tz.get('label', 'unknown')}")
            unfinished = getattr(working_memory, "_state", {}).get("unfinished", [])
            if unfinished:
                parts.append(f"Unfinished items: {len(unfinished)}")
            if parts:
                ctx.constraints = ". ".join(parts)

        # ── Memory confidence ────────────────────────────────────────
        if brain_context_len > 500:
            ctx.memory_hits = "rich context available (high confidence)"
        elif brain_context_len > 100:
            ctx.memory_hits = "some context available (moderate confidence)"
        elif brain_context_len > 0:
            ctx.memory_hits = "minimal context (low confidence — may need to search)"
        # If 0, leave empty (no signal)

        return ctx

    def to_prompt(self) -> str:
        """Format as structured block for injection into agent task.

        Returns "" if no meaningful signals are present.
        """
        lines = []

        if self.tone:
            lines.append(f"  Tone: {self.tone}")
        if self.risk:
            lines.append(f"  Risk: {self.risk}")
        if self.tool_reliability:
            lines.append(f"  Tool reliability: {self.tool_reliability}")
        if self.constraints:
            lines.append(f"  Active constraints: {self.constraints}")
        if self.memory_hits:
            lines.append(f"  Memory: {self.memory_hits}")

        if not lines:
            return ""

        return "REASONING CONTEXT (symbolic signals — use these to guide your approach):\n" + "\n".join(lines)
