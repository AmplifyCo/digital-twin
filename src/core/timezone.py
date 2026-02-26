"""Central timezone configuration for the digital twin system.

All user-facing time operations should use `now()` from this module
instead of `datetime.now()` to ensure consistent PST timezone.

The user's default timezone is US/Pacific (PST/PDT).
This can be overridden by setting USER_TIMEZONE env var, or at runtime
via set_override() when the user is traveling.
"""

import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

# Default timezone — can be overridden by env var
_tz_name = os.getenv("USER_TIMEZONE", "America/Los_Angeles")
USER_TZ = ZoneInfo(_tz_name)

# Runtime override (set when user says "I'm in New York this week")
_override_tz: Optional[ZoneInfo] = None


def set_override(tz_name: str):
    """Set a runtime timezone override (e.g., user traveling)."""
    global _override_tz
    _override_tz = ZoneInfo(tz_name)


def clear_override():
    """Clear the runtime timezone override (user back home)."""
    global _override_tz
    _override_tz = None


def effective_tz() -> ZoneInfo:
    """Return the currently active timezone (override or default)."""
    return _override_tz if _override_tz else USER_TZ


def now() -> datetime:
    """Get current time in user's effective timezone."""
    return datetime.now(effective_tz())


def format_time(dt: datetime = None) -> str:
    """Format a datetime for user display."""
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=effective_tz())
    return dt.strftime("%Y-%m-%d %H:%M %Z")


def current_time_context() -> str:
    """Return a string describing current time for system prompt injection."""
    t = now()
    tz = effective_tz()
    return f"Current time: {t.strftime('%Y-%m-%d %H:%M %Z')} ({t.strftime('%A')}) [tz: {tz}]"
