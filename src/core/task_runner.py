"""Background Task Runner — Nova's autonomous execution engine.

Runs as a persistent asyncio loop (like ReminderScheduler).
Picks up tasks from TaskQueue, decomposes them via GoalDecomposer,
executes each subtask via agent.run(), and notifies the user when done.

Flow per task:
  1. Dequeue next pending task
  2. Decompose goal into subtasks (Gemini Flash)
  3. Execute each subtask sequentially via agent.run()
  4. Collect results, synthesize (last subtask writes the file)
  5. Notify user via WhatsApp + Telegram
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .task_queue import Task, TaskQueue
from .goal_decomposer import GoalDecomposer

logger = logging.getLogger(__name__)


class TaskRunner:
    """Background autonomous task executor.

    Runs every CHECK_INTERVAL seconds, picks up one task at a time,
    decomposes + executes it via the existing agent.run() ReAct loop.
    """

    CHECK_INTERVAL = 15  # seconds between queue polls
    MAX_SUBTASK_RETRIES = 3  # Increased retries for robustness

    def __init__(
        self,
        task_queue: TaskQueue,
        goal_decomposer: GoalDecomposer,
        agent,                       # AutonomousAgent
        telegram_notifier,           # TelegramNotifier
        brain=None,                  # DigitalCloneBrain (for storing results)
        whatsapp_channel=None,       # TwilioWhatsAppChannel (for WhatsApp notifications)
    ):
        self.task_queue = task_queue
        self.goal_decomposer = goal_decomposer
        self.agent = agent
        self.telegram = telegram_notifier
        self.brain = brain
        self.whatsapp_channel = whatsapp_channel
        self._running = False
        self._current_task_id: Optional[str] = None
        Path("./data/tasks").mkdir(parents=True, exist_ok=True)

    async def start(self):
        """Main background loop. Runs indefinitely."""
        self._running = True
        logger.info("🚀 TaskRunner background loop started")
        while self._running:
            try:
                await self._process_next_task()
            except Exception as e:
                logger.error(f"TaskRunner loop error: {e}", exc_info=True)
            await asyncio.sleep(self.CHECK_INTERVAL)

    def stop(self):
        self._running = False

    # ── Core execution ────────────────────────────────────────────────────────

    async def _process_next_task(self):
        """Pick up and execute the next pending task (if any)."""
        task = self.task_queue.dequeue_next()
        if not task:
            return

        self._current_task_id = task.id
        logger.info(f"TaskRunner picked up task {task.id}: {task.goal[:60]}")

        try:
            # Step 1: Decompose into subtasks
            available_tools = list(self.agent.tools.tools.keys()) if hasattr(self.agent, 'tools') else []
            subtasks = await self.goal_decomposer.decompose(
                goal=task.goal,
                task_id=task.id,
                available_tools=available_tools,
            )
            self.task_queue.set_subtasks(task.id, subtasks)
            task.subtasks = subtasks

            logger.info(f"Task {task.id}: decomposed into {len(subtasks)} subtasks")

            # Step 2: Execute each subtask sequentially
            all_results = []
            num_subtasks = len(subtasks)
            for idx, subtask in enumerate(subtasks):
                logger.info(f"Task {task.id}: executing subtask {idx+1}/{num_subtasks}: {subtask.description[:60]}")
                self.task_queue.update_subtask(task.id, idx, "running")

                result = await self._execute_subtask(task, subtask, idx, all_results)
                all_results.append(f"Step {idx+1}: {result}")

                if result.startswith("ERROR:") and idx < num_subtasks - 1:
                    # Non-synthesis step failed — continue (later steps may still work)
                    logger.warning(f"Subtask {idx+1} failed, continuing: {result}")
                    self.task_queue.update_subtask(task.id, idx, "failed", error=result)
                else:
                    self.task_queue.update_subtask(task.id, idx, "done", result=result[:500])

                # Send progress notification if multiple subtasks
                if num_subtasks > 1 and task.notify_on_complete:
                    await self._notify_progress(task, idx + 1, num_subtasks, all_results)

            # Step 3: Build summary from results
            summary = self._build_summary(task.goal, all_results)
            self.task_queue.mark_done(task.id, result=summary)

            # Step 4: Notify user
            if task.notify_on_complete:
                await self._notify_user(task, summary)

            logger.info(f"Task {task.id} completed successfully")

        except asyncio.CancelledError:
            logger.info(f"Task {task.id} cancelled")
            self.task_queue.mark_failed(task.id, "Task runner stopped during execution")
            raise
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}", exc_info=True)
            self.task_queue.mark_failed(task.id, str(e)[:300])
            # Still try to notify user about the failure
            if task.notify_on_complete:
                await self._notify_failure(task, str(e))
        finally:
            self._current_task_id = None

    async def _execute_subtask(self, task: Task, subtask, idx: int, prior_results: list) -> str:
        """Execute a single subtask via agent.run() and return the result string."""
        # Build an enriched subtask prompt that includes prior results as context
        context = ""
        if prior_results:
            # Only include last 3 results to avoid context bloat
            recent = prior_results[-3:]
            context = "\n\nPREVIOUS STEPS COMPLETED:\n" + "\n".join(recent) + "\n\n---\n"

        task_prompt = (
            f"{context}"
            f"BACKGROUND TASK (ID: {task.id})\n"
            f"Overall goal: {task.goal}\n\n"
            f"Current step ({idx+1}): {subtask.description}\n\n"
            f"Complete this step and report what you found/did. Be thorough."
        )

        # Add tool hints as guidance
        if subtask.tool_hints:
            task_prompt += f"\n\nSuggested tools for this step: {', '.join(subtask.tool_hints)}"

        # Use 'sonnet' tier for synthesis (last step), 'flash' for everything else
        model_tier = "sonnet"  # Use better model for all subtasks to reduce failures

        for attempt in range(self.MAX_SUBTASK_RETRIES):
            try:
                result = await self.agent.run(
                    task=task_prompt,
                    model_tier=model_tier,
                    max_iterations=8,  # generous for research tasks
                )
                return result or "Step completed (no output)"
            except Exception as e:
                error_str = str(e)
                if attempt < self.MAX_SUBTASK_RETRIES - 1 and ("429" in error_str or "rate_limit" in error_str):
                    logger.warning(f"Rate limited on subtask {idx+1}, retrying in 30s...")
                    await asyncio.sleep(30)
                    continue
                return f"ERROR: {error_str[:200]}"

        return "ERROR: Max retries exceeded"

    # ── Notification ──────────────────────────────────────────────────────────

    async def _notify_progress(self, task: Task, completed: int, total: int, results: list):
        """Notify progress on both Telegram and WhatsApp for multi-subtask tasks."""
        prog_msg = (
            f"🛠️ Task {task.id} progress: {completed}/{total} steps done\n"
            f"Goal: {task.goal[:100]}\n"
            f"Latest: {results[-1][:200] if results else 'Starting...'}"
        )

        # Telegram
        try:
            await self.telegram.notify(prog_msg, level="info")
        except Exception as e:
            logger.warning(f"Telegram progress failed: {e}")

        # WhatsApp (if configured)
        if self.whatsapp_channel and task.user_id:
            try:
                await self.whatsapp_channel.send_message(task.user_id, prog_msg)
            except Exception as e:
                logger.warning(f"WhatsApp progress failed: {e}")

    async def _notify_user(self, task: Task, summary: str):
        """Notify user via Telegram + WhatsApp when a task completes."""
        file_path = f"./data/tasks/{task.id}.txt"

        # Telegram notification (always)
        tg_msg = (
            f"✅ *Background task complete*\n\n"
            f"*Goal:* {task.goal[:100]}\n\n"
            f"{summary[:400]}\n\n"
            f"📄 Full report: `{file_path}`"
        )
        try:
            await self.telegram.notify(tg_msg, level="info")
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")

        # WhatsApp notification (always attempt if configured)
        if self.whatsapp_channel and task.user_id:
            wa_msg = (
                f"✅ Done! Here's what I found:\n\n"
                f"{summary[:600]}\n\n"
                f"Full report saved to: {file_path}"
            )
            try:
                await self.whatsapp_channel.send_message(task.user_id, wa_msg)
            except Exception as e:
                logger.error(f"WhatsApp channel send failed: {e} — falling back to outbound tool")
                # Fallback to WhatsAppOutboundTool
                try:
                    wa_tool = self.agent.tools.get_tool("whatsapp_outbound")
                    if wa_tool:
                        await wa_tool.execute(to_number=task.user_id, body=wa_msg)
                    else:
                        logger.warning("Outbound tool not available")
                except Exception as fallback_e:
                    logger.error(f"WhatsApp fallback failed: {fallback_e}")
                # Final fallback: notify via Telegram
                await self.telegram.notify(f"WhatsApp failed for task {task.id}: {str(e)[:100]} — Summary: {summary[:200]}", level="warning")
        elif not self.whatsapp_channel:
            logger.debug("WhatsApp channel not configured, skipping WhatsApp notification")

    async def _notify_failure(self, task: Task, error: str):
        """Notify user when a task fails on both Telegram and WhatsApp."""
        msg = (
            f"❌ *Background task failed*\n\n"
            f"*Goal:* {task.goal[:100]}\n"
            f"*Error:* {error[:200]}\n\n"
            f"Please try again or rephrase the request."
        )
        try:
            await self.telegram.notify(msg, level="warning")
        except Exception as e:
            logger.warning(f"Telegram failure notification failed: {e}")

        if self.whatsapp_channel and task.user_id:
            try:
                await self.whatsapp_channel.send_message(
                    task.user_id,
                    f"Sorry, I wasn't able to complete that task. Error: {error[:100]}"
                )
            except Exception as e:
                logger.warning(f"WhatsApp failure notification failed: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_summary(self, goal: str, results: list) -> str:
        """Build a compact summary from subtask results.

        The last subtask (synthesis) is expected to have written the file
        and produced a bullet-point summary. We extract that.
        """
        if not results:
            return "No results collected."

        # Use the last result (synthesis step) as the primary summary
        last = results[-1] if results else ""
        # Strip the "Step N:" prefix
        if ": " in last:
            last = last.split(": ", 1)[1]

        # Truncate for notification use (full content is in the file)
        if len(last) > 800:
            last = last[:800] + "..."

        return last

    def get_status(self) -> dict:
        """Return current runner status (for dashboard/health checks)."""
        return {
            "running": self._running,
            "current_task": self._current_task_id,
            "pending_tasks": self.task_queue.get_pending_count(),
        }
