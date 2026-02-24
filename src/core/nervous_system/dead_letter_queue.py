"""Dead Letter Queue — parks poison events/tool calls that fail repeatedly.

Architecture: Nervous System component.
Prevents infinite retry loops on messages or tool calls that always fail.
Stores failed items with error details for later investigation.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """Persistent DLQ for poison events and tool calls.

    Items land here after exceeding max retries. Can be inspected
    and replayed manually via Telegram commands or dashboard.
    """

    MAX_DLQ_SIZE = 100  # Keep last N items, oldest dropped

    def __init__(self, data_dir: str = "./data", telegram_notifier=None):
        """Initialize DLQ.

        Args:
            data_dir: Directory for persistent storage
            telegram_notifier: Optional notifier; sends alert when an item is dead-lettered
        """
        self.data_dir = Path(data_dir)
        self.dlq_file = self.data_dir / "dead_letter_queue.json"
        self._failure_counts: Dict[str, int] = {}  # key → consecutive failure count
        self.max_retries = 3  # failures before moving to DLQ
        self.telegram = telegram_notifier

    def record_failure(
        self,
        key: str,
        error: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Record a failure. Returns True if item should be dead-lettered.

        Args:
            key: Unique key for the event/tool call (e.g., 'tool:email:send_email:abc123')
            error: Error message
            context: Additional context (tool params, user message, etc.)

        Returns:
            True if max retries exceeded and item was moved to DLQ
        """
        count = self._failure_counts.get(key, 0) + 1
        self._failure_counts[key] = count

        if count >= self.max_retries:
            self._add_to_dlq(key, error, context, count)
            del self._failure_counts[key]
            return True

        return False

    def record_success(self, key: str):
        """Record a success — clears failure count for this key."""
        self._failure_counts.pop(key, None)

    def _add_to_dlq(
        self,
        key: str,
        error: str,
        context: Optional[Dict[str, Any]],
        failure_count: int
    ):
        """Add an item to the persistent DLQ."""
        items = self._load()

        item = {
            "key": key,
            "error": error,
            "context": context or {},
            "failure_count": failure_count,
            "dead_lettered_at": datetime.now().isoformat(),
        }

        items.append(item)

        # Trim to max size
        if len(items) > self.MAX_DLQ_SIZE:
            items = items[-self.MAX_DLQ_SIZE:]

        self._save(items)
        logger.warning(f"Dead-lettered after {failure_count} failures: {key} — {error}")

        # Alert owner via Telegram (SM-05 gap — RISK-O06)
        if self.telegram:
            import asyncio
            short_key = key[:80]
            short_error = error[:120]
            msg = (
                f"⚠️ *Dead Letter Queue alert*\n\n"
                f"A task was abandoned after {failure_count} failed attempts.\n\n"
                f"*Key:* `{short_key}`\n"
                f"*Error:* {short_error}\n\n"
                f"Check the DLQ to retry or discard it."
            )
            # Notify is async; schedule it safely whether we're in an event loop or not
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.telegram.notify(msg, level="warning"))
                else:
                    loop.run_until_complete(self.telegram.notify(msg, level="warning"))
            except Exception as notify_err:
                logger.warning(f"DLQ Telegram alert failed: {notify_err}")

    def get_items(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent DLQ items."""
        items = self._load()
        return items[-limit:]

    def clear(self):
        """Clear the DLQ."""
        self._save([])
        self._failure_counts.clear()
        logger.info("Dead letter queue cleared")

    def count(self) -> int:
        """Get number of items in DLQ."""
        return len(self._load())

    def _load(self) -> List[Dict[str, Any]]:
        if not self.dlq_file.exists():
            return []
        try:
            with open(self.dlq_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save(self, items: List[Dict[str, Any]]):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.dlq_file, 'w') as f:
            json.dump(items, f, indent=2, default=str)
