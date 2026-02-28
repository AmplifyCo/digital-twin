"""
Watchdog service for the Digital Twin.
Acts as a supervisor process to ensure the main agent starts and stays running.
If the agent crashes at startup (ImportError, syntax error, etc.), the watchdog
attempts to auto-fix the issue using the AI AutoFixer.

When Nova is down, the watchdog activates a DevOps fallback: a minimal Telegram
polling loop that listens ONLY for /devops commands from the authorized user and
pipes them to Claude CLI. The watchdog NEVER uses Claude CLI autonomously.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

def setup_logging():
    # Configure logging for the watchdog itself
    Path("data/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - [WATCHDOG] - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("data/logs/watchdog.log")
        ]
    )
logger = logging.getLogger("watchdog")

# Constants
MAX_RESTARTS_PER_WINDOW = 5
WINDOW_SECONDS = 300  # 5 minutes
BACKOFF_START_SECONDS = 5

class DevOpsFallback:
    """Minimal Telegram polling loop for /devops commands when Nova is down.

    CRITICAL: This must NOT overlap with Nova's Telegram webhook.
    It uses getUpdates polling (not webhooks) and only activates
    when the main process has crashed.

    CRITICAL: The watchdog NEVER uses Claude CLI autonomously.
    It only forwards /devops commands explicitly sent by the user.
    """

    def __init__(self, bot_token: str, chat_id: str, project_root: Path):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.project_root = project_root
        self._active = False
        self._poll_offset = 0

    async def start(self):
        """Start polling for /devops commands."""
        try:
            import aiohttp
        except ImportError:
            logger.warning("[DEVOPS FALLBACK] aiohttp not installed — fallback disabled")
            return

        self._active = True
        logger.info("[DEVOPS FALLBACK] Polling started — listening for /devops commands only")

        # Delete webhook so getUpdates works (Nova re-registers on restart)
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{self.bot_token}/deleteWebhook"
                )
        except Exception as e:
            logger.warning(f"[DEVOPS FALLBACK] Could not delete webhook: {e}")

        while self._active:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error(f"[DEVOPS FALLBACK] Poll error: {e}")
            await asyncio.sleep(2)

    async def stop(self):
        """Stop polling (called before Nova restarts)."""
        self._active = False
        logger.info("[DEVOPS FALLBACK] Polling stopped")

    async def _poll_once(self):
        """Single poll cycle using Telegram getUpdates API."""
        import aiohttp

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {"offset": self._poll_offset, "timeout": 10}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()

        if not data.get("ok"):
            return

        for update in data.get("result", []):
            self._poll_offset = update["update_id"] + 1
            message = update.get("message", {})
            text = message.get("text", "")
            from_chat_id = str(message.get("chat", {}).get("id", ""))

            # Security: only authorized chat_id
            if from_chat_id != self.chat_id:
                continue

            # Only handle /devops commands
            if not text.strip().lower().startswith("/devops"):
                if text.strip():
                    await self._send_message(
                        "Nova is currently restarting. Only /devops commands are available in fallback mode."
                    )
                continue

            command = text.strip()[len("/devops"):].strip()
            if not command:
                await self._send_message(
                    "Nova is down — watchdog fallback active.\n\n"
                    "Usage: /devops <command>\n"
                    "Example: /devops check what crashed in the logs"
                )
                continue

            await self._send_message(f"[Watchdog] Processing: {command}...")
            result = await self._run_claude_cli(command)
            await self._send_message(result)

    async def _run_claude_cli(self, prompt: str) -> str:
        """Run Claude CLI with the given prompt. Returns output text."""
        claude_path = shutil.which("claude")
        if not claude_path:
            return "Error: Claude CLI not installed. Run: npm install -g @anthropic-ai/claude-code"

        try:
            process = await asyncio.create_subprocess_exec(
                claude_path, "-p", prompt, "--no-input",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_root),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=180
            )

            output = (stdout.decode("utf-8", errors="replace") if stdout else "").strip()
            err = (stderr.decode("utf-8", errors="replace") if stderr else "").strip()

            if process.returncode == 0:
                return output[:4000] or "(no output)"
            else:
                return f"Error (exit {process.returncode}):\n{err[:2000]}\n\nOutput:\n{output[:2000]}"

        except asyncio.TimeoutError:
            return "Claude CLI timed out after 3 minutes."
        except Exception as e:
            return f"Claude CLI error: {e}"

    async def _send_message(self, text: str):
        """Send a message to Telegram (plain text)."""
        import aiohttp

        if len(text) > 4000:
            text = text[:3990] + "\n...(truncated)"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text}

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=payload)
        except Exception as e:
            logger.error(f"[DEVOPS FALLBACK] Send failed: {e}")


class ServiceWatchdog:
    def __init__(self):
        self.restart_history = []
        self.project_root = Path(__file__).parent.parent
        self.main_script = self.project_root / "src/main.py"
        self.venv_python = self.project_root / "venv/bin/python"

        # Fallback to system python if venv not found (local dev)
        if not self.venv_python.exists():
            self.venv_python = Path(sys.executable)

        # DevOps fallback: polls Telegram for /devops commands when Nova is down
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self._devops_fallback = None
        self._devops_task = None
        if bot_token and chat_id:
            self._devops_fallback = DevOpsFallback(
                bot_token=bot_token,
                chat_id=chat_id,
                project_root=self.project_root,
            )

    async def start(self):
        """Start the watchdog loop."""
        logger.info("Starting Digital Twin Watchdog")
        logger.info(f"Target: {self.main_script}")

        while True:
            # Stop DevOps fallback before (re)starting Nova
            if self._devops_task and self._devops_fallback:
                await self._devops_fallback.stop()
                self._devops_task.cancel()
                try:
                    await self._devops_task
                except asyncio.CancelledError:
                    pass
                self._devops_task = None

            # Check for crash loop
            if self._is_crashing_too_often():
                logger.critical("Too many restarts in short period. Backing off for 5 minutes.")
                await asyncio.sleep(300)
                self.restart_history.clear() # Reset after backoff

            self.restart_history.append(datetime.now())

            # Start the service
            logger.info("Starting main service...")
            process = await asyncio.create_subprocess_exec(
                str(self.venv_python),
                str(self.main_script),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Stream logs (pass-through)
            stdout_task = asyncio.create_task(self._stream_output(process.stdout, "stdout"))
            stderr_task = asyncio.create_task(self._stream_output(process.stderr, "stderr"))

            # Wait for exit
            exit_code = await process.wait()
            await asyncio.gather(stdout_task, stderr_task)

            if exit_code == 0:
                logger.info("Service exited normally (0). Restarting immediately.")
                continue
            
            # Crash detected
            logger.error(f"Service crashed with exit code {exit_code}")

            # Start DevOps fallback so user can send /devops commands while Nova is down
            if self._devops_fallback and not self._devops_task:
                logger.info("Starting DevOps fallback (Nova is down — /devops available via watchdog)")
                self._devops_task = asyncio.create_task(self._devops_fallback.start())

            # Attempt Auto-Fix
            await self._handle_crash(exit_code)
            
            # Exponential backoff based on recent crash frequency
            wait_time = max(BACKOFF_START_SECONDS, len(self.restart_history) * 2)
            logger.info(f"Restarting in {wait_time} seconds...")
            await asyncio.sleep(wait_time)

    async def _stream_output(self, stream, origin):
        """Stream output from subprocess to watchdog logs."""
        output_buffer = []  # Keep last ~50 lines for crash analysis
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                if origin == "stderr":
                    # Check for log levels in the text to avoid false errors
                    level = logging.ERROR
                    upper_text = text.upper()
                    if "INFO" in upper_text or "INFO:" in upper_text:
                        level = logging.INFO
                    elif "WARNING" in upper_text or "WARN:" in upper_text:
                        level = logging.WARNING
                    elif "DEBUG" in upper_text:
                        level = logging.DEBUG
                        
                    logger.log(level, f"[AGENT] {text}")
                    # Capture for analysis
                    self._capture_crash_log(text)
                else:
                    logger.info(f"[AGENT] {text}")

    def _capture_crash_log(self, line):
        """Buffer stderr for analysis."""
        if not hasattr(self, '_crash_buffer'):
            self._crash_buffer = []
        self._crash_buffer.append(line)
        if len(self._crash_buffer) > 100:
            self._crash_buffer.pop(0)

    def _is_crashing_too_often(self):
        """Check if we are in a crash loop."""
        now = datetime.now()
        # Remove old history
        self.restart_history = [t for t in self.restart_history if (now - t).total_seconds() < WINDOW_SECONDS]
        return len(self.restart_history) >= MAX_RESTARTS_PER_WINDOW

    async def _handle_crash(self, exit_code):
        """Analyze crash and attempt auto-fix."""
        if not hasattr(self, '_crash_buffer') or not self._crash_buffer:
            logger.warning("No stderr output captured. Cannot analyze crash.")
            return

        error_context = "\n".join(self._crash_buffer[-20:]) # Last 20 lines
        logger.info("Analyzing crash context...")

        try:
            # Lazy import to avoid crash if these modules are broken
            # We need to add src to sys.path first
            sys.path.insert(0, str(self.project_root))
            
            from src.core.self_healing.auto_fixer import AutoFixer
            from src.core.self_healing.error_detector import DetectedError, ErrorType, ErrorSeverity
            from src.integrations.gemini_client import GeminiClient
            from src.core.config import load_config
            
            # Initialize minimal dependencies
            config = load_config()
            gemini_client = GeminiClient(
                api_key=os.getenv('GEMINI_API_KEY', ''),
                anthropic_api_key=config.api_key
            )
            fixer = AutoFixer(llm_client=gemini_client)
            
            # Create a synthetic detected error
            # We assume it's a SERVICE_CRASH or whatever we can infer
            # Ideally we parse it, but for now we create a generic high-severity error with context
            error = DetectedError(
                error_type=ErrorType.SERVICE_CRASH,
                severity=ErrorSeverity.CRITICAL,
                message=f"Service crashed with exit code {exit_code}",
                timestamp=datetime.now(),
                context=error_context,
                auto_fixable=True
            )
            
            # Attempt fix
            logger.info("Invoking AutoFixer...")
            result = await fixer.attempt_fix(error)
            
            if result.success:
                logger.info(f"Auto-fix successful: {result.action_taken}")
            else:
                logger.error(f"Auto-fix failed: {result.details}")
                
        except Exception as e:
            logger.error(f"Watchdog failed to auto-fix: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    try:
        # Load .env so TELEGRAM_BOT_TOKEN etc. are available for DevOps fallback
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent / ".env")
        except ImportError:
            pass  # dotenv not installed — env vars must come from systemd or shell

        # Ensure log dir exists and setup logging
        setup_logging()

        watchdog = ServiceWatchdog()
        logging.info("Watchdog initialized successfully")
        asyncio.run(watchdog.start())
    except KeyboardInterrupt:
        logger.info("Watchdog stopped by user")
    except Exception as e:
        # Critical failure in watchdog itself
        sys.stderr.write(f"CRITICAL WATCHDOG FAILURE: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
