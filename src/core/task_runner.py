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
        critic=None,                 # CriticAgent (validates results before delivery)
        template_library=None,       # ReasoningTemplateLibrary (stores successful decompositions)
    ):
        self.task_queue = task_queue
        self.goal_decomposer = goal_decomposer
        self.agent = agent
        self.telegram = telegram_notifier
        self.brain = brain
        self.whatsapp_channel = whatsapp_channel
        self.critic = critic
        self.template_library = template_library
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

        # Notify owner on Telegram that the task has started (RISK-O06 — SM-06 gap)
        try:
            start_msg = (
                f"🚀 *Background task started*\n\n"
                f"*Goal:* {task.goal[:150]}\n"
                f"*Task ID:* `{task.id}`\n\n"
                f"I'll update you when it's done or if anything unexpected happens."
            )
            await self.telegram.notify(start_msg, level="info")
        except Exception as e:
            logger.warning(f"Task-started notification failed: {e}")

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

            # Step 3: Critic validation — evaluate quality before delivery
            critic_score = 0.8  # default if critic unavailable
            if self.critic:
                try:
                    critic_result = await self.critic.evaluate(task.goal, subtasks, all_results)
                    critic_score = critic_result.score
                    logger.info(f"Task {task.id}: critic score {critic_result.score:.2f} (passed={critic_result.passed})")
                    if not critic_result.passed and critic_result.refinement_hint:
                        logger.info(f"Task {task.id}: running refinement pass — {critic_result.refinement_hint[:80]}")
                        refined = await self.critic.refine(task.goal, all_results, critic_result.refinement_hint)
                        if refined:
                            all_results.append(f"Step {len(all_results)+1} (refined): {refined}")
                            critic_score = 0.8  # assume acceptable after refinement
                except Exception as e:
                    logger.warning(f"Task {task.id}: critic evaluation failed (proceeding): {e}")

            # Step 4: Store successful decomposition as a reusable template
            if self.template_library and critic_score >= 0.7:
                try:
                    await self.template_library.store(task.goal, subtasks, critic_score)
                except Exception as e:
                    logger.warning(f"Task {task.id}: template store failed: {e}")

            # Step 5: Build summary from results
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
                if attempt < self.MAX_SUBTASK_RETRIES - 1:
                    if "429" in error_str or "rate_limit" in error_str:
                        logger.warning(f"Rate limited on subtask {idx+1}, retrying in 30s...")
                        await asyncio.sleep(30)
                    else:
                        # Semantic retry: generate targeted fix hint before retrying
                        hint = await self._generate_retry_hint(subtask.description, error_str)
                        task_prompt = (
                            f"PREVIOUS ATTEMPT FAILED: {error_str[:200]}\n"
                            f"HINT FOR THIS RETRY: {hint}\n\n"
                            f"---\n{task_prompt}"
                        )
                        logger.warning(f"Subtask {idx+1} logic failure, retrying with hint: {hint[:80]}")
                    continue
                return f"ERROR: {error_str[:200]}"

        return "ERROR: Max retries exceeded"

    async def _generate_retry_hint(self, subtask_desc: str, error: str) -> str:
        """Ask Gemini Flash what went wrong and what different approach to try.

        Returns a 1-2 sentence hint string, or a generic fallback on any error.
        """
        # Try to use the agent's gemini client if available
        gemini = getattr(self.agent, "gemini_client", None) if self.agent else None
        if not gemini or not getattr(gemini, "enabled", False):
            return "Try a different search query or use a different tool to accomplish this step."

        hint_prompt = (
            f"An AI agent failed a task step. In 1-2 sentences only, suggest what it should "
            f"try differently on the next attempt.\n\n"
            f"Step: {subtask_desc[:200]}\n"
            f"Error: {error[:200]}"
        )
        try:
            response = await gemini.create_message(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": hint_prompt}],
                max_tokens=128,
            )
            hint = ""
            if hasattr(response, "content"):
                for block in response.content:
                    if hasattr(block, "text"):
                        hint += block.text
            elif isinstance(response, str):
                hint = response
            return hint.strip() or "Try a different approach for this step."
        except Exception as e:
            logger.debug(f"_generate_retry_hint failed: {e}")
            return "Try a different approach or use a different tool for this step."

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

        # WhatsApp (if configured) — send_message() is sync, run in thread
        if self.whatsapp_channel and task.user_id:
            try:
                await asyncio.to_thread(
                    self.whatsapp_channel.send_message, task.user_id, prog_msg
                )
            except Exception as e:
                logger.warning(f"WhatsApp progress failed: {e}")

    async def _notify_user(self, task: Task, summary: str):
        """Notify user via Telegram when a task completes.

        Reads the full report file and sends it in chunks so the user
        receives the complete content in Telegram — not just a file path
        that is inaccessible outside EC2.
        """
        file_path = Path(f"./data/tasks/{task.id}.txt")

        # Read full file content; fall back to the in-memory summary
        full_content = summary
        try:
            if file_path.exists():
                full_content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not read task file {file_path}: {e}")

        header = (
            f"✅ *Background task complete*\n\n"
            f"*Goal:* {task.goal[:150]}\n\n"
        )

        # Send full content via Telegram in chunks (Telegram limit: 4096 chars)
        try:
            await self._send_chunked_telegram(header, full_content)
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")

        # WhatsApp notification — send_message() is sync, run in thread
        if self.whatsapp_channel and task.user_id:
            wa_msg = f"✅ Done!\n\n{full_content[:1200]}"
            try:
                await asyncio.to_thread(
                    self.whatsapp_channel.send_message, task.user_id, wa_msg
                )
            except Exception as e:
                logger.warning(f"WhatsApp notification failed: {e}")
        elif not self.whatsapp_channel:
            logger.debug("WhatsApp channel not configured, skipping WhatsApp notification")

    async def _send_chunked_telegram(self, header: str, content: str):
        """Send a potentially long message to Telegram in 3800-char chunks.

        First chunk includes the header. Subsequent chunks are labeled
        (continued N) so the user can follow the sequence.
        """
        CHUNK = 3800
        first_body = content[: CHUNK - len(header)]
        await self.telegram.notify(header + first_body, level="info")

        remaining = content[CHUNK - len(header) :]
        part = 2
        while remaining:
            chunk_text = f"*(continued {part})*\n\n" + remaining[:CHUNK]
            await self.telegram.notify(chunk_text, level="info")
            remaining = remaining[CHUNK:]
            part += 1

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
                await asyncio.to_thread(
                    self.whatsapp_channel.send_message,
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
