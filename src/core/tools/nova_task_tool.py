"""Nova Task Tool — lets Nova queue goals for autonomous background execution.

This is Nova's self-direction mechanism: when the agent recognizes a task
is too complex for one shot (multi-source research, multi-step workflows),
it calls this tool to enqueue the goal. The TaskRunner picks it up and
executes it autonomously, then notifies the user when done.
"""

import logging
from typing import Optional

from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class NovaTaskTool(BaseTool):
    """Tool to queue goals for Nova's background autonomous execution.

    Use when: task requires 3+ steps, multi-source research, compiling a
    report, or will take significant time. Nova executes it in the background
    and sends a WhatsApp + Telegram notification when done.

    Do NOT use for: simple lookups, quick questions, single-tool actions.
    """

    name = "nova_task"
    description = (
        "Queue a goal for background autonomous execution (runs independently, notifies when done). "
        "ONLY use when the task genuinely requires 3+ steps AND multiple tools — e.g., multi-source "
        "research then compiling a report, or monitoring something over time. "
        "NEVER use for: checking status of something, simple questions, single-tool lookups, "
        "quick answers, or anything the user expects an immediate reply to. "
        "If in doubt, answer directly — don't queue it."
    )
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'enqueue' to add a new background task, 'list' to see pending tasks, 'status' to check a specific task, 'cancel' to cancel a task",
            "enum": ["enqueue", "list", "status", "cancel"]
        },
        "goal": {
            "type": "string",
            "description": "The high-level goal to accomplish in the background (for 'enqueue')"
        },
        "task_id": {
            "type": "string",
            "description": "Task ID to check status or cancel (for 'status' and 'cancel')"
        },
        "priority": {
            "type": "string",
            "description": "Task priority: 'normal' (default) or 'high' (runs before other pending tasks)",
            "enum": ["normal", "high"]
        }
    }

    def __init__(self, task_queue=None):
        """
        Args:
            task_queue: TaskQueue instance (injected by ConversationManager or main.py).
                        If None, operations return a helpful error.
        """
        self.task_queue = task_queue
        # These are set by ConversationManager so the tool knows the current context
        self._current_channel: str = "telegram"
        self._current_user_id: str = ""

    def set_context(self, channel: str, user_id: str):
        """Update current channel/user context (called by ConversationManager)."""
        self._current_channel = channel
        self._current_user_id = user_id

    async def execute(
        self,
        operation: str,
        goal: Optional[str] = None,
        task_id: Optional[str] = None,
        priority: str = "normal",
        **kwargs
    ) -> ToolResult:
        if not self.task_queue:
            return ToolResult(
                success=False,
                error="Task queue not initialized. Background tasks are not available."
            )

        try:
            if operation == "enqueue":
                return await self._enqueue(goal, priority)
            elif operation == "list":
                return await self._list_tasks()
            elif operation == "status":
                return await self._get_status(task_id)
            elif operation == "cancel":
                return await self._cancel(task_id)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as e:
            logger.error(f"NovaTaskTool error: {e}", exc_info=True)
            return ToolResult(success=False, error=f"Task operation failed: {e}")

    async def _enqueue(self, goal: Optional[str], priority: str) -> ToolResult:
        if not goal or not goal.strip():
            return ToolResult(success=False, error="'goal' is required for enqueue")

        task_id = self.task_queue.enqueue(
            goal=goal.strip(),
            channel=self._current_channel,
            user_id=self._current_user_id,
            notify_on_complete=True,
        )

        pending = self.task_queue.get_pending_count()
        return ToolResult(
            success=True,
            output=(
                f"Task queued (ID: {task_id}). "
                f"Nova will work on it autonomously — you'll get a WhatsApp notification when done. "
                f"({pending} task(s) now pending)"
            ),
            metadata={"task_id": task_id, "pending_count": pending}
        )

    async def _list_tasks(self) -> ToolResult:
        tasks = self.task_queue.get_active_and_recent_tasks(completed_hours=2)
        if not tasks:
            return ToolResult(success=True, output="No active tasks and nothing completed in the last 2 hours.")

        active = [t for t in tasks if t.status in ("pending", "decomposing", "running")]
        recent = [t for t in tasks if t.status in ("done", "failed")]

        lines = []
        if active:
            lines.append("Active tasks:")
            for t in active:
                done_subtasks = sum(1 for st in t.subtasks if st.status == "done") if t.subtasks else 0
                total_subtasks = len(t.subtasks)
                progress = f" [{done_subtasks}/{total_subtasks} steps]" if total_subtasks else ""
                lines.append(f"  • [{t.status.upper()}]{progress} {t.goal[:80]}")
        if recent:
            lines.append("Completed in last 2 hours:")
            for t in recent:
                done_subtasks = sum(1 for st in t.subtasks if st.status == "done") if t.subtasks else 0
                total_subtasks = len(t.subtasks)
                progress = f" [{done_subtasks}/{total_subtasks} steps]" if total_subtasks else ""
                lines.append(f"  • [{t.status.upper()}]{progress} {t.goal[:80]}")
        if not lines:
            return ToolResult(success=True, output="No active tasks and nothing completed in the last 2 hours.")
        return ToolResult(success=True, output="\n".join(lines))

    async def _get_status(self, task_id: Optional[str]) -> ToolResult:
        if not task_id:
            return ToolResult(success=False, error="'task_id' is required for status")
        task = self.task_queue.get_task(task_id)
        if not task:
            return ToolResult(success=False, error=f"Task {task_id} not found")

        lines = [f"Task {task.id}: {task.status.upper()}", f"Goal: {task.goal}"]
        if task.subtasks:
            lines.append("Steps:")
            for i, st in enumerate(task.subtasks):
                icon = {"done": "✅", "running": "⏳", "failed": "❌", "pending": "⬜", "skipped": "⏭️"}.get(st.status, "•")
                lines.append(f"  {icon} {i+1}. {st.description[:70]}")
        if task.result:
            lines.append(f"Result: {task.result[:200]}")
        if task.error:
            lines.append(f"Error: {task.error[:200]}")
        return ToolResult(success=True, output="\n".join(lines))

    async def _cancel(self, task_id: Optional[str]) -> ToolResult:
        if not task_id:
            return ToolResult(success=False, error="'task_id' is required for cancel")
        task = self.task_queue.get_task(task_id)
        if not task:
            return ToolResult(success=False, error=f"Task {task_id} not found")
        if task.status in ("done", "failed"):
            return ToolResult(success=False, error=f"Task {task_id} is already {task.status}")
        self.task_queue.cancel(task_id)
        return ToolResult(success=True, output=f"Task {task_id} cancelled.")
