"""Nightly backup of digital_clone_brain memory.

Security model:
- ONLY creates copies (shutil.copytree) — never reads or modifies the live brain
- ONLY deletes from data/backups/ subdirectories — never touches live data
- Backup directory is isolated from live data paths
- No content inspection: files are copied as-is, byte-for-byte
"""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Backup runs at this hour (24h clock, server local time)
_BACKUP_HOUR = 2   # 2am
_RETAIN_DAYS = 7


class MemoryBackup:
    """Nightly backup task for digital_clone_brain.

    Creates a dated snapshot of the brain directory each night and
    removes snapshots older than RETAIN_DAYS. Never reads, modifies,
    or deletes the live brain data.
    """

    def __init__(
        self,
        source_path: str,
        backup_root: str = "./data/backups",
        retain_days: int = _RETAIN_DAYS,
        backup_hour: int = _BACKUP_HOUR,
        telegram=None,
    ):
        self.source = Path(source_path)
        self.backup_root = Path(backup_root)
        self.retain_days = retain_days
        self.backup_hour = backup_hour
        self.telegram = telegram

    async def start(self):
        """Run the nightly backup loop."""
        logger.info(f"🗄️  Memory backup started — runs at {self.backup_hour:02d}:00, retains {self.retain_days} days")
        while True:
            await self._sleep_until_next_backup()
            await self._run_backup()

    async def _sleep_until_next_backup(self):
        """Sleep until the next backup window (2am)."""
        now = datetime.now()
        next_run = now.replace(hour=self.backup_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"🗄️  Next memory backup at {next_run.strftime('%Y-%m-%d %H:%M')}")
        await asyncio.sleep(wait_seconds)

    async def _run_backup(self):
        """Create a snapshot and purge old ones."""
        if not self.source.exists():
            logger.warning(f"Memory backup skipped — source not found: {self.source}")
            return

        datestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.backup_root / f"digital_clone_brain_{datestamp}"

        try:
            # CREATE: copy source to dated destination (read-only on source)
            self.backup_root.mkdir(parents=True, exist_ok=True)
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: shutil.copytree(str(self.source), str(dest))
            )
            logger.info(f"✅ Memory backup created: {dest.name}")

            # PURGE: remove backups older than retain_days
            # Safety: only deletes from backup_root, never from live data paths
            cutoff = datetime.now() - timedelta(days=self.retain_days)
            purged = []
            for entry in self.backup_root.iterdir():
                if not entry.is_dir():
                    continue
                if not entry.name.startswith("digital_clone_brain_"):
                    continue  # only touch our own backups
                try:
                    # Parse date from directory name
                    date_part = entry.name.replace("digital_clone_brain_", "")[:8]
                    entry_date = datetime.strptime(date_part, "%Y%m%d")
                    if entry_date < cutoff:
                        await asyncio.get_event_loop().run_in_executor(
                            None, lambda e=entry: shutil.rmtree(str(e))
                        )
                        purged.append(entry.name)
                except (ValueError, Exception):
                    pass  # skip entries we can't parse

            if purged:
                logger.info(f"🗑️  Purged {len(purged)} old backup(s): {', '.join(purged)}")

            if self.telegram:
                await self.telegram.notify(
                    f"🗄️ Memory backup complete\n`{dest.name}`"
                    + (f"\nPurged {len(purged)} old backup(s)" if purged else ""),
                    level="info"
                )

        except Exception as e:
            logger.error(f"Memory backup failed: {e}", exc_info=True)
            if self.telegram:
                await self.telegram.notify(f"⚠️ Memory backup failed: {e}", level="warning")
