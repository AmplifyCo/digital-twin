"""Attention Engine — Nova proactively notices things and surfaces them.

Driven by NovaPurpose: different times of day trigger different observation
modes (morning briefing, evening summary, weekly look-ahead, curiosity scan).

Runs every 6 hours. Generates 1-3 observations using the LLM.
Sends via Telegram. Never sends more than once per topic per 24h.

Security:
- All LLM calls use the same security budget as regular Nova calls.
- Dedup log stored locally in data/attention_log.json — no PII.
- Never sends raw contact data or message content — only observations.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .nova_purpose import NovaPurpose, PurposeMode

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 6 * 3600   # 6 hours
MAX_ITEMS      = 3          # Max observations per cycle


class AttentionEngine:
    """Background loop that proactively surfaces relevant observations."""

    def __init__(
        self,
        digital_brain,
        llm_client,
        telegram_notifier,
        owner_name: str = "User",
        purpose: Optional[NovaPurpose] = None,
    ):
        self.brain = digital_brain
        self.llm = llm_client
        self.telegram = telegram_notifier
        self.owner_name = owner_name
        self.purpose = purpose or NovaPurpose()
        self._log_path = Path("data/attention_log.json")
        self._is_running = False

    # ── Background loop ───────────────────────────────────────────────

    async def start(self):
        """Start the background attention loop."""
        self._is_running = True
        logger.info("🔍 Attention Engine started")

        while self._is_running:
            try:
                await self._scan_and_surface()
            except Exception as e:
                logger.error(f"AttentionEngine error: {e}", exc_info=True)
            await asyncio.sleep(CHECK_INTERVAL)

    async def stop(self):
        self._is_running = False

    # ── Core scan ─────────────────────────────────────────────────────

    async def _scan_and_surface(self):
        """Scan memory and surface purpose-driven observations."""
        now = datetime.now()

        # Only send during waking hours (7am – 9pm)
        if not (7 <= now.hour <= 21):
            logger.debug("AttentionEngine: outside waking hours, skipping")
            return

        mode = self.purpose.get_mode(now)
        logger.info(f"🔍 Attention scan running (mode={mode.value})...")

        # Build context from memory
        snippets = await self._gather_memory_snippets()
        if not snippets:
            return

        # Build purpose-driven prompt and generate observations
        prompt = self.purpose.build_prompt(mode, snippets, self.owner_name, now)
        observations = await self._generate_observations_from_prompt(prompt)
        if not observations:
            return

        # Filter already-sent topics
        new_obs = [o for o in observations if not self._already_sent(o)]
        if not new_obs:
            return

        # Send via Telegram with purpose-appropriate header
        header = self.purpose.get_header(mode, self.owner_name, now)
        await self._notify_with_header(new_obs, header)

        # Log sent topics
        for o in new_obs:
            self._mark_sent(o)

    async def _gather_memory_snippets(self) -> str:
        """Pull relevant memory context for attention analysis."""
        parts = []

        try:
            # Recent conversations — use whichever API the brain supports
            query = "recent conversations tasks reminders follow-up"
            if hasattr(self.brain, 'get_relevant_context'):
                try:
                    recent = await self.brain.get_relevant_context(
                        query, max_results=5, channel="telegram"
                    )
                except TypeError:
                    recent = await self.brain.get_relevant_context(query, max_results=5)
                if recent:
                    parts.append(f"Recent activity:\n{recent[:800]}")
            elif hasattr(self.brain, 'search_context'):
                recent = await self.brain.search_context(query, channel="telegram", n_results=5)
                if recent:
                    parts.append(f"Recent activity:\n{recent[:800]}")
        except Exception as e:
            logger.debug(f"Memory snippet error: {e}")

        return "\n\n".join(parts) if parts else ""

    async def _generate_observations_from_prompt(self, prompt: str) -> list:
        """Use LLM with the given purpose-built prompt to generate observations."""
        if not self.llm:
            return []

        try:
            resp = await self.llm.create_message(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
            )
            text = resp.content[0].text.strip()
            # Strip markdown fences if present
            text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.debug(f"Attention LLM failed: {e}")
            return []

    async def _notify_with_header(self, observations: list, header: str):
        """Send observations via Telegram with the purpose-appropriate header."""
        if not self.telegram or not observations:
            return

        lines = [header]
        for obs in observations:
            lines.append(f"  • {obs}")

        try:
            await self.telegram.notify("\n".join(lines), level="info")
            logger.info(f"Attention Engine sent {len(observations)} observation(s) [{header[:30]}]")
        except Exception as e:
            logger.error(f"Attention notify failed: {e}")

    # ── Dedup log ─────────────────────────────────────────────────────

    def _load_log(self) -> dict:
        if self._log_path.exists():
            try:
                return json.loads(self._log_path.read_text())
            except Exception:
                pass
        return {}

    def _save_log(self, log: dict):
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text(json.dumps(log, indent=2))

    def _already_sent(self, observation: str) -> bool:
        """Return True if this observation was sent in the last 24 hours."""
        log = self._load_log()
        key = observation[:50].lower()
        if key in log:
            sent_at = datetime.fromisoformat(log[key])
            if datetime.now() - sent_at < timedelta(hours=24):
                return True
        return False

    def _mark_sent(self, observation: str):
        log = self._load_log()
        key = observation[:50].lower()
        log[key] = datetime.now().isoformat()
        # Prune old entries (keep last 100)
        if len(log) > 100:
            oldest = sorted(log.items(), key=lambda x: x[1])[:20]
            for k, _ in oldest:
                del log[k]
        self._save_log(log)
