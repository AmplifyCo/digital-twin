"""Intent Data Collector — captures live intent classifications as training data.

Every message Nova classifies via the LLM intent parser produces a structured
label: intent, confidence, inferred_task, tools. This module persists those
labels as JSONL so they can later fine-tune a DistilBERT intent classifier.

Design:
- Writes are async (asyncio.create_task) — zero latency impact on main flow.
- Skips low-confidence samples (noisy labels hurt fine-tuning).
- On first run, seeds the dataset from data/golden_intents.json.
- Storage: data/intent_training/samples.jsonl (one JSON object per line).

Security: stores only user message text and classifier metadata.
No contact data, no API credentials, no raw tool outputs.
"""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT = Path("data/intent_training/samples.jsonl")
_DEFAULT_GOLDEN = Path("data/golden_intents.json")


class IntentDataCollector:
    """Persists intent classification results as a JSONL training dataset.

    Injected into ConversationManager by main.py (same pattern as EpisodicMemory).

    Usage:
        collector = IntentDataCollector()
        collector.record(
            text="remind me to call mom at 6pm",
            label="action",
            confidence=0.9,
            inferred_task="Set reminder: call mom at 6pm",
            tool_hints=["reminder_set"],
            model="gemini/gemini-2.0-flash",
        )
    """

    def __init__(
        self,
        output_path: str = str(_DEFAULT_OUTPUT),
        golden_path: str = str(_DEFAULT_GOLDEN),
        min_confidence: float = 0.7,
    ):
        """Initialize the data collector.

        Args:
            output_path: Path to the JSONL training data file.
            golden_path: Path to golden_intents.json (for cold-start seeding).
            min_confidence: Minimum confidence to accept a sample (0.7 = medium).
                            Low confidence (0.4) samples are skipped as noisy labels.
        """
        self._output = Path(output_path)
        self._golden = Path(golden_path)
        self._min_confidence = min_confidence

        self._output.parent.mkdir(parents=True, exist_ok=True)

        # Seed from golden_intents.json on first run (file absent or empty)
        if not self._output.exists() or self._output.stat().st_size == 0:
            self._seed_from_golden()

        logger.info(
            f"IntentDataCollector ready — {self._count_samples()} samples in {self._output}"
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def record(
        self,
        text: str,
        label: str,
        confidence: float,
        inferred_task: Optional[str],
        tool_hints: List[str],
        model: str,
    ) -> None:
        """Schedule a non-blocking write of one training sample.

        Called from _parse_intent_with_fallback() via asyncio.create_task().
        Returns immediately — disk write happens in the background.

        Skips:
        - confidence below min_confidence (low = 0.4, discarded as noisy)
        - label is "unknown" or empty (parse failure)

        Args:
            text: Raw user message (capped at 500 chars).
            label: Classified intent label (e.g., "action", "question").
            confidence: Numeric confidence (0.4 low / 0.7 medium / 0.9 high).
            inferred_task: Elaborated task description from the LLM (may be None).
            tool_hints: List of tool names the LLM predicted would be needed.
            model: LiteLLM model string that produced this classification.
        """
        if confidence < self._min_confidence:
            return
        if label in ("unknown", ""):
            return

        sample = {
            "text":          text.strip()[:500],
            "label":         label,
            "confidence":    round(confidence, 4),
            "inferred_task": (inferred_task or "").strip()[:200] or None,
            "tool_hints":    tool_hints,
            "model":         model,
            "timestamp":     datetime.now().isoformat(),
            "source":        "live",
        }

        # Fire-and-forget — does NOT block the caller
        asyncio.create_task(self._write_sample(sample))

    def get_stats(self) -> str:
        """Return label distribution and total count as a formatted string.

        Output is Telegram Markdown compatible and suitable for embedding in
        the status reply from _handle_status().

        Returns:
            Multi-line string with label counts and percentages.
        """
        try:
            counts: Dict[str, int] = defaultdict(int)
            golden_count = 0
            total = 0

            if self._output.exists():
                with open(self._output, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            label = obj.get("label", "unknown")
                            counts[label] += 1
                            total += 1
                            if obj.get("source") == "golden":
                                golden_count += 1
                        except json.JSONDecodeError:
                            continue

            if total == 0:
                return "Intent training dataset is empty — no samples yet."

            lines = [f"*Intent Training Dataset*\nTotal samples: {total}\n"]
            for label, count in sorted(counts.items(), key=lambda x: -x[1]):
                pct = count / total * 100
                lines.append(f"  `{label:<16}` {count:>4}  ({pct:.1f}%)")

            if golden_count:
                lines.append(f"\n  golden seeds: {golden_count}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"IntentDataCollector.get_stats() failed: {e}")
            return f"Could not read intent stats: {e}"

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _write_sample(self, sample: dict) -> None:
        """Append one sample to the JSONL file (background coroutine)."""
        try:
            with open(self._output, "a", encoding="utf-8") as f:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"IntentDataCollector write failed: {e}")

    def _seed_from_golden(self) -> None:
        """Convert golden_intents.json into training samples (source='golden').

        Runs synchronously at boot, before the event loop is hot.
        Each golden example gets confidence=1.0 — they are ground truth.

        golden_intents.json schema:
            [{"intent": "action", "examples": ["check my email", ...], "tools": [...]}]
        """
        if not self._golden.exists():
            logger.warning(
                f"golden_intents.json not found at {self._golden} — skipping seed."
            )
            return

        try:
            with open(self._golden, "r", encoding="utf-8") as f:
                groups = json.load(f)

            written = 0
            with open(self._output, "a", encoding="utf-8") as out:
                for group in groups:
                    intent = group.get("intent", "unknown")
                    tools = group.get("tools", [])
                    for phrase in group.get("examples", []):
                        sample = {
                            "text":          phrase.strip(),
                            "label":         intent,
                            "confidence":    1.0,
                            "inferred_task": None,
                            "tool_hints":    tools,
                            "model":         "golden",
                            "timestamp":     datetime.now().isoformat(),
                            "source":        "golden",
                        }
                        out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        written += 1

            logger.info(
                f"IntentDataCollector: seeded {written} samples from golden_intents.json"
            )

        except Exception as e:
            logger.error(f"IntentDataCollector: golden seed failed: {e}")

    def _count_samples(self) -> int:
        """Return current line count in the JSONL file."""
        if not self._output.exists():
            return 0
        try:
            with open(self._output, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return -1
