"""Working Memory — persistent session state across conversations.

Humans carry mood, unresolved thoughts, and momentum between conversations.
Nova does the same via this module: tone, unfinished items, and behavioral
calibration instructions persist across restarts.

Security: read/write is local file only. No external calls. No PII stored here
— only tone labels, topic strings (trimmed to 100 chars), and directive text.
"""

import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT = {
    "tone":               "neutral",       # neutral | urgent | stressed | relaxed | formal
    "energy":             "normal",        # low | normal | high
    "unfinished":         [],              # list of brief strings (max 5)
    "momentum":           "",              # current topic thread (max 100 chars)
    "calibration":        "",              # user-issued behavioral directive ("be more concise")
    "session_count":      0,
    "last_active":        None,
}

_TONES = {
    "urgent":   "⚡ The user is in a hurry — be brief, skip preamble, lead with the answer.",
    "stressed": "🌊 The user seems under pressure — be calm, clear, and reassuring.",
    "relaxed":  "☀️  The user is relaxed — you can be more conversational and thorough.",
    "formal":   "📋 The user is in professional mode — be precise and structured.",
    "neutral":  "",   # no special instruction needed
}


class WorkingMemory:
    """Lightweight session-state store that persists to disk between restarts."""

    def __init__(self, path: str = "data/working_memory.json"):
        self._path = Path(path)
        self._state = self._load()

    # ── Load / Save ──────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                return {**_DEFAULT, **data}
            except Exception:
                pass
        return dict(_DEFAULT)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self._state, indent=2, default=str)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(data)
            Path(tmp).rename(self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── Update after each conversation turn ──────────────────────────

    def update(self, user_message: str, response: str, detected_tone: str = "neutral"):
        """Called after each message pair to update session state.

        Args:
            user_message: What the user said
            response: What Nova replied
            detected_tone: Tone detected from user_message
        """
        self._state["tone"] = detected_tone
        self._state["last_active"] = datetime.now().isoformat()
        self._state["session_count"] = self._state.get("session_count", 0) + 1

        # Update momentum (current topic thread — last 100 chars of user message)
        topic = user_message.strip()[:100]
        if topic:
            self._state["momentum"] = topic

        # Prune unfinished list (keep max 5 most recent)
        if len(self._state["unfinished"]) > 5:
            self._state["unfinished"] = self._state["unfinished"][-5:]

        self._save()

    def add_unfinished(self, item: str):
        """Mark something as unfinished (e.g., a task mentioned but not completed)."""
        trimmed = item.strip()[:100]
        if trimmed and trimmed not in self._state["unfinished"]:
            self._state["unfinished"].append(trimmed)
            if len(self._state["unfinished"]) > 5:
                self._state["unfinished"].pop(0)
            self._save()

    def resolve_unfinished(self, item: str):
        """Remove an item from the unfinished list when it's completed."""
        self._state["unfinished"] = [
            x for x in self._state["unfinished"]
            if item.lower() not in x.lower()
        ]
        self._save()

    def set_calibration(self, directive: str):
        """Store a behavioral directive from the user ('be more concise')."""
        self._state["calibration"] = directive.strip()[:200]
        self._save()
        logger.info(f"Working memory calibration set: {directive[:60]}")

    def clear_calibration(self):
        """Clear any active behavioral directive."""
        self._state["calibration"] = ""
        self._save()

    # ── Context for system prompt ─────────────────────────────────────

    def get_context(self) -> str:
        """Return a formatted snippet for injection into system prompts.

        Returns empty string if nothing meaningful to add.
        """
        parts = []

        tone = self._state.get("tone", "neutral")
        tone_instruction = _TONES.get(tone, "")
        if tone_instruction:
            parts.append(tone_instruction)

        calibration = self._state.get("calibration", "")
        if calibration:
            parts.append(f"📌 User instruction (active until changed): {calibration}")

        unfinished = self._state.get("unfinished", [])
        if unfinished:
            items = "  • " + "\n  • ".join(unfinished)
            parts.append(f"🔖 Items mentioned but not yet resolved:\n{items}")

        if not parts:
            return ""

        return "WORKING MEMORY:\n" + "\n".join(parts)

    # ── Pending Actions (confirmation loop fix) ─────────────────────

    # Max age for a pending action before it auto-expires (seconds)
    _PENDING_ACTION_TTL = 1800  # 30 minutes

    def add_pending_action(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        label: str,
        proposal_text: str,
    ):
        """Store an action that Nova proposed and is awaiting user confirmation.

        Args:
            tool_name: The tool to execute (e.g. "x_tool", "email_send")
            parameters: The parameters to pass to the tool
            label: Short human label (e.g. "post tweet", "send email to Bob")
            proposal_text: The full bot message that proposed this action
        """
        pending: List[Dict] = self._state.get("pending_actions", [])

        # Replace existing pending action from the same tool (no two pending tweets)
        pending = [p for p in pending if p.get("tool_name") != tool_name]

        pending.append({
            "tool_name": tool_name,
            "parameters": parameters,
            "label": label.strip()[:80],
            "proposal_text": proposal_text.strip()[:500],
            "created_at": time.time(),
        })

        # Cap at 3 pending actions max
        if len(pending) > 3:
            pending = pending[-3:]

        self._state["pending_actions"] = pending
        self._save()
        logger.info(f"Pending action stored: {label[:60]} (tool={tool_name})")

    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Return non-expired pending actions, cleaning up stale ones."""
        pending: List[Dict] = self._state.get("pending_actions", [])
        now = time.time()

        live = [p for p in pending if now - p.get("created_at", 0) < self._PENDING_ACTION_TTL]

        if len(live) != len(pending):
            self._state["pending_actions"] = live
            self._save()

        return live

    def pop_pending_action(self, tool_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Remove and return a pending action (by tool_name or most-recent).

        Args:
            tool_name: Specific tool to pop. If None, pops the most recent.

        Returns:
            The pending action dict, or None if nothing matches.
        """
        pending = self.get_pending_actions()
        if not pending:
            return None

        matched = None
        if tool_name:
            for p in pending:
                if p["tool_name"] == tool_name:
                    matched = p
                    break
        else:
            matched = pending[-1]  # most recent

        if matched:
            self._state["pending_actions"] = [p for p in pending if p is not matched]
            self._save()
        return matched

    def pop_all_pending_actions(self) -> List[Dict[str, Any]]:
        """Remove and return all pending actions."""
        pending = self.get_pending_actions()
        if pending:
            self._state["pending_actions"] = []
            self._save()
        return pending

    def clear_pending_actions(self):
        """Discard all pending actions (user said 'no' / 'cancel')."""
        if self._state.get("pending_actions"):
            self._state["pending_actions"] = []
            self._save()
            logger.info("All pending actions cleared")

    # ── Properties ────────────────────────────────────────────────────

    @property
    def tone(self) -> str:
        return self._state.get("tone", "neutral")

    @property
    def calibration(self) -> str:
        return self._state.get("calibration", "")

    @property
    def momentum(self) -> str:
        return self._state.get("momentum", "")
