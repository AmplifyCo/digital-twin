"""Calendar tool - Sync, create, check appointments using CalDAV (works with Google, Outlook, iCloud)"""

import caldav
from caldav import DAVClient
from datetime import datetime, timedelta
from icalendar import Calendar, Event as iCalEvent
import pytz
import logging
from typing import Optional, List, Dict, Any
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class CalendarTool(BaseTool):
    """Tool for managing calendar events via CalDAV.

    Works with:
    - Google Calendar (https://apidata.googleusercontent.com/caldav/v2/)
    - Outlook/Office365 (https://outlook.office365.com/)
    - iCloud (https://caldav.icloud.com/)
    - Any CalDAV-compatible calendar
    """

    name = "calendar"
    description = "Create, read, update calendar events. Check appointments, schedule meetings, get reminders."
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'list_events', 'create_event', 'check_today', 'check_week', 'update_event', 'delete_event'",
            "enum": ["list_events", "create_event", "check_today", "check_week", "update_event", "delete_event"]
        },
        "title": {
            "type": "string",
            "description": "Event title/summary (for create_event, update_event)"
        },
        "start_time": {
            "type": "string",
            "description": "Start time in ISO format (YYYY-MM-DD HH:MM) or natural language"
        },
        "end_time": {
            "type": "string",
            "description": "End time in ISO format (YYYY-MM-DD HH:MM) or natural language"
        },
        "description": {
            "type": "string",
            "description": "Event description/details"
        },
        "location": {
            "type": "string",
            "description": "Event location"
        },
        "event_id": {
            "type": "string",
            "description": "Event ID for update/delete operations"
        },
        "days_ahead": {
            "type": "integer",
            "description": "Number of days ahead to check (default: 7)",
            "default": 7
        }
    }

    def __init__(
        self,
        caldav_url: str,
        username: str,
        password: str,
        calendar_name: Optional[str] = None
    ):
        """Initialize Calendar tool.

        Args:
            caldav_url: CalDAV server URL
                - Google: https://apidata.googleusercontent.com/caldav/v2/YOUR_EMAIL/events
                - Outlook: https://outlook.office365.com/
                - iCloud: https://caldav.icloud.com/
            username: Email address
            password: Password or app-specific password
            calendar_name: Specific calendar name (optional, uses primary if not specified)
        """
        self.caldav_url = caldav_url
        self.username = username
        self.password = password
        self.calendar_name = calendar_name
        self.timezone = pytz.timezone('America/New_York')  # TODO: Make configurable

    def _get_client(self) -> DAVClient:
        """Get CalDAV client."""
        return DAVClient(
            url=self.caldav_url,
            username=self.username,
            password=self.password
        )

    def _get_calendar(self):
        """Get calendar object."""
        client = self._get_client()
        principal = client.principal()

        calendars = principal.calendars()

        if not calendars:
            raise Exception("No calendars found")

        # Use specific calendar if provided, otherwise use first calendar
        if self.calendar_name:
            for cal in calendars:
                if cal.name == self.calendar_name:
                    return cal
            raise Exception(f"Calendar '{self.calendar_name}' not found")

        return calendars[0]

    async def execute(
        self,
        operation: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        event_id: Optional[str] = None,
        days_ahead: int = 7
    ) -> ToolResult:
        """Execute calendar operation.

        Args:
            operation: Operation to perform
            title: Event title
            start_time: Start time
            end_time: End time
            description: Event description
            location: Event location
            event_id: Event ID for update/delete
            days_ahead: Days to look ahead

        Returns:
            ToolResult with operation result
        """
        try:
            if operation == "list_events":
                return await self._list_events(days_ahead)
            elif operation == "create_event":
                return await self._create_event(title, start_time, end_time, description, location)
            elif operation == "check_today":
                return await self._check_today()
            elif operation == "check_week":
                return await self._check_week()
            elif operation == "update_event":
                return await self._update_event(event_id, title, start_time, end_time, description)
            elif operation == "delete_event":
                return await self._delete_event(event_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown operation: {operation}"
                )

        except Exception as e:
            logger.error(f"Calendar operation error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"Calendar operation failed: {str(e)}"
            )

    async def _list_events(self, days_ahead: int) -> ToolResult:
        """List upcoming events."""
        try:
            calendar = self._get_calendar()

            # Get events from now to N days ahead
            start = datetime.now(self.timezone)
            end = start + timedelta(days=days_ahead)

            events = calendar.date_search(start=start, end=end, expand=True)

            if not events:
                return ToolResult(
                    success=True,
                    output=f"📅 No events in the next {days_ahead} days"
                )

            # Parse and format events
            event_list = []
            for event in events:
                try:
                    cal = Calendar.from_ical(event.data)
                    for component in cal.walk():
                        if component.name == "VEVENT":
                            event_data = {
                                'title': str(component.get('summary', 'No title')),
                                'start': component.get('dtstart').dt,
                                'end': component.get('dtend').dt if component.get('dtend') else None,
                                'location': str(component.get('location', '')),
                                'description': str(component.get('description', ''))
                            }
                            event_list.append(event_data)
                except Exception as e:
                    logger.debug(f"Error parsing event: {e}")
                    continue

            # Sort by start time
            event_list.sort(key=lambda x: x['start'])

            # Format output
            output = f"📅 Upcoming events (next {days_ahead} days):\n\n"
            for i, evt in enumerate(event_list, 1):
                start_str = evt['start'].strftime('%Y-%m-%d %H:%M') if isinstance(evt['start'], datetime) else str(evt['start'])
                output += f"{i}. **{evt['title']}**\n"
                output += f"   📍 {start_str}\n"
                if evt['location']:
                    output += f"   🏢 {evt['location']}\n"
                if evt['description']:
                    output += f"   📝 {evt['description']}\n"
                output += "\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error(f"Error listing events: {e}")
            return ToolResult(success=False, error=str(e))

    async def _create_event(
        self,
        title: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> ToolResult:
        """Create a new calendar event."""
        try:
            if not title or not start_time:
                return ToolResult(
                    success=False,
                    error="title and start_time required"
                )

            calendar = self._get_calendar()

            # Parse start and end times
            start_dt = self._parse_datetime(start_time)
            end_dt = self._parse_datetime(end_time) if end_time else (start_dt + timedelta(hours=1))

            # Create iCalendar event
            cal = Calendar()
            event = iCalEvent()
            event.add('summary', title)
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)

            if description:
                event.add('description', description)
            if location:
                event.add('location', location)

            event.add('dtstamp', datetime.now(self.timezone))
            event.add('uid', f"{datetime.now().timestamp()}@novabot")

            cal.add_component(event)

            # Add event to calendar
            calendar.add_event(cal.to_ical().decode('utf-8'))

            output = f"✅ Event created:\n"
            output += f"**{title}**\n"
            output += f"📍 {start_dt.strftime('%Y-%m-%d %H:%M')}"
            if location:
                output += f"\n🏢 {location}"

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error(f"Error creating event: {e}")
            return ToolResult(success=False, error=str(e))

    async def _check_today(self) -> ToolResult:
        """Check today's appointments."""
        try:
            calendar = self._get_calendar()

            # Get today's events
            start = datetime.now(self.timezone).replace(hour=0, minute=0, second=0)
            end = start + timedelta(days=1)

            events = calendar.date_search(start=start, end=end, expand=True)

            if not events:
                return ToolResult(
                    success=True,
                    output="📅 No events scheduled for today"
                )

            # Parse events
            event_list = []
            for event in events:
                try:
                    cal = Calendar.from_ical(event.data)
                    for component in cal.walk():
                        if component.name == "VEVENT":
                            event_data = {
                                'title': str(component.get('summary', 'No title')),
                                'start': component.get('dtstart').dt,
                                'location': str(component.get('location', ''))
                            }
                            event_list.append(event_data)
                except:
                    continue

            event_list.sort(key=lambda x: x['start'])

            output = f"📅 Today's Schedule ({start.strftime('%Y-%m-%d')}):\n\n"
            for i, evt in enumerate(event_list, 1):
                start_str = evt['start'].strftime('%H:%M') if isinstance(evt['start'], datetime) else str(evt['start'])
                output += f"{i}. {start_str} - **{evt['title']}**\n"
                if evt['location']:
                    output += f"   🏢 {evt['location']}\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error(f"Error checking today: {e}")
            return ToolResult(success=False, error=str(e))

    async def _check_week(self) -> ToolResult:
        """Check this week's appointments."""
        return await self._list_events(7)

    async def _update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None
    ) -> ToolResult:
        """Update an existing event."""
        # TODO: Implement update functionality
        return ToolResult(
            success=False,
            error="Update event not yet implemented"
        )

    async def _delete_event(self, event_id: str) -> ToolResult:
        """Delete an event."""
        # TODO: Implement delete functionality
        return ToolResult(
            success=False,
            error="Delete event not yet implemented"
        )

    def _parse_datetime(self, time_str: str) -> datetime:
        """Parse datetime string to datetime object."""
        try:
            # Try ISO format first: YYYY-MM-DD HH:MM
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
            return self.timezone.localize(dt)
        except ValueError:
            try:
                # Try date only: YYYY-MM-DD
                dt = datetime.strptime(time_str, '%Y-%m-%d')
                return self.timezone.localize(dt)
            except ValueError:
                # TODO: Add natural language parsing
                raise ValueError(f"Cannot parse datetime: {time_str}. Use format: YYYY-MM-DD HH:MM")
