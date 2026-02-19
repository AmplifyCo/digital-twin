"""Self-healing monitoring service that runs periodically."""

import asyncio
import logging
from typing import Optional
from datetime import datetime

from .error_detector import ErrorDetector, ErrorSeverity
from .auto_fixer import AutoFixer

logger = logging.getLogger(__name__)


class SelfHealingMonitor:
    """Background monitoring service for error detection and auto-fix."""

    def __init__(
        self,
        telegram_notifier=None,
        check_interval: int = 43200,  # 12 hours
        log_file: str = "./data/logs/agent.log",
        auto_fix_enabled: bool = True
    ):
        """Initialize self-healing monitor.

        Args:
            telegram_notifier: Optional Telegram chat for notifications
            check_interval: Seconds between health checks
            log_file: Path to log file to monitor
            auto_fix_enabled: Whether to attempt auto-fixes
        """
        self.telegram = telegram_notifier
        self.check_interval = check_interval
        self.auto_fix_enabled = auto_fix_enabled

        self.detector = ErrorDetector(log_file=log_file)
        self.fixer = AutoFixer(telegram_notifier=telegram_notifier)

        self.is_running = False
        self.last_check = None
        self.startup_time = None
        self.total_errors_detected = 0
        self.total_fixes_attempted = 0

        logger.info(f"SelfHealingMonitor initialized (check every {check_interval}s)")

    async def start(self):
        """Start the monitoring service."""
        if self.is_running:
            logger.warning("Monitor already running")
            return

        self.is_running = True
        self.startup_time = datetime.now()
        logger.info("🩺 Self-healing monitor started")

        # Run monitoring loop
        while self.is_running:
            try:
                await self._run_health_check()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)  # Continue despite errors

    async def stop(self):
        """Stop the monitoring service."""
        self.is_running = False
        logger.info("Self-healing monitor stopped")

    async def _run_health_check(self):
        """Run a health check cycle."""
        self.last_check = datetime.now()
        logger.info("Running health check...")

        # Scan for recent errors (never before startup — avoids re-detecting pre-restart errors)
        errors = self.detector.scan_recent_logs(
            minutes=self.check_interval // 60,
            not_before=self.startup_time
        )

        if not errors:
            logger.info("✅ No errors detected")
            return

        logger.warning(f"⚠️ Detected {len(errors)} errors")
        self.total_errors_detected += len(errors)

        # Categorize errors
        critical_errors = [e for e in errors if e.severity == ErrorSeverity.CRITICAL]
        high_errors = [e for e in errors if e.severity == ErrorSeverity.HIGH]
        auto_fixable_errors = [e for e in errors if e.auto_fixable]

        # Notify about critical errors immediately
        if critical_errors:
            await self._notify_critical_errors(critical_errors)

        # Attempt auto-fix for fixable errors
        if self.auto_fix_enabled and auto_fixable_errors:
            logger.info(f"Attempting to auto-fix {len(auto_fixable_errors)} errors")
            await self._attempt_fixes(auto_fixable_errors)

        # Send summary for high-severity errors
        elif high_errors:
            await self._notify_high_severity_errors(high_errors)

    async def _attempt_fixes(self, errors):
        """Attempt to fix detected errors.

        Args:
            errors: List of DetectedError objects
        """
        fixes_successful = 0
        fixes_failed = 0
        needs_restart = False

        for error in errors:
            self.total_fixes_attempted += 1

            result = await self.fixer.attempt_fix(error)

            if result.success:
                fixes_successful += 1
                logger.info(f"✅ Fixed: {error.error_type.value}")

                if result.requires_restart:
                    needs_restart = True

                # Purge the error log so fixed errors don't get re-detected
                self._purge_error_log()
            else:
                fixes_failed += 1
                logger.warning(f"❌ Failed to fix: {error.error_type.value}")

        # Send summary
        if self.telegram:
            message = f"""🔧 **Auto-Fix Summary**

**Attempted:** {len(errors)}
**Successful:** {fixes_successful} ✅
**Failed:** {fixes_failed} ❌
"""
            if needs_restart:
                message += "\n⚠️ **Service restart recommended**\nSend: 'restart' to apply fixes"

            await self.telegram.notify(message)

    async def _notify_critical_errors(self, errors):
        """Notify about critical errors.

        Args:
            errors: List of critical errors
        """
        if not self.telegram:
            return

        message = f"""🚨 **CRITICAL ERRORS DETECTED**

**Count:** {len(errors)}

**Recent:**
"""
        for error in errors[:3]:  # Show first 3
            message += f"• {error.error_type.value}: {error.message[:80]}...\n"

        message += "\n⚠️ **Immediate attention required!**"

        await self.telegram.notify(message)

    async def _notify_high_severity_errors(self, errors):
        """Notify about high-severity errors that aren't auto-fixable.

        Args:
            errors: List of high-severity errors
        """
        if not self.telegram:
            return

        message = f"""⚠️ **High-Severity Errors Detected**

**Count:** {len(errors)}
**Auto-fixable:** {sum(1 for e in errors if e.auto_fixable)}

Monitoring and will attempt auto-fix if possible.
"""
        await self.telegram.notify(message)

    def _purge_error_log(self):
        """Clear the error log file after a successful fix so old errors aren't re-detected."""
        try:
            log_path = self.detector.log_file
            if log_path.exists():
                with open(log_path, 'w') as f:
                    f.write(f"# Log purged after successful auto-fix at {datetime.now().isoformat()}\n")
                # Reset startup_time so the fresh log is scanned from now
                self.startup_time = datetime.now()
                self.detector.detected_errors.clear()
                self.detector.error_history.clear()
                logger.info("🗑️ Error log purged after successful fix")
        except Exception as e:
            logger.warning(f"Could not purge error log: {e}")

    async def get_status(self) -> dict:
        """Get monitor status.

        Returns:
            Status dict
        """
        return {
            "running": self.is_running,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "check_interval_seconds": self.check_interval,
            "auto_fix_enabled": self.auto_fix_enabled,
            "total_errors_detected": self.total_errors_detected,
            "total_fixes_attempted": self.total_fixes_attempted,
            "error_summary": self.detector.get_error_summary(),
            "fix_summary": self.fixer.get_fix_summary()
        }

    async def run_manual_check(self) -> dict:
        """Run a manual health check (for Telegram command).

        Returns:
            Check results dict
        """
        logger.info("Running manual health check...")

        errors = self.detector.scan_recent_logs(minutes=30)  # Last 30 minutes

        result = {
            "errors_detected": len(errors),
            "auto_fixable": sum(1 for e in errors if e.auto_fixable),
            "by_severity": {},
            "recent_errors": []
        }

        # Count by severity
        for error in errors:
            severity = error.severity.value
            result["by_severity"][severity] = result["by_severity"].get(severity, 0) + 1

        # Recent errors (last 5)
        for error in errors[-5:]:
            result["recent_errors"].append({
                "type": error.error_type.value,
                "severity": error.severity.value,
                "message": error.message[:100],
                "auto_fixable": error.auto_fixable
            })

        return result
