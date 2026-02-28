"""Claude CLI plugin — delegates complex devops tasks to Claude Code."""

import asyncio
import logging
import shutil
from pathlib import Path

from src.core.tools.base import BaseTool
from src.core.types import ToolResult

logger = logging.getLogger(__name__)

# Project root — Claude CLI operates in the novabot directory
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ClaudeCliTool(BaseTool):
    """Invoke Claude CLI (claude) for complex devops analysis and fixes."""

    name = "claude_cli"
    description = (
        "Delegate a complex devops task to Claude CLI. "
        "Use for: deep debugging, multi-file analysis, log correlation, "
        "architecture-level fixes, package installation. "
        "Do NOT use for simple commands that bash can handle directly. "
        "Input: a natural language prompt describing what to investigate or fix."
    )
    parameters = {
        "prompt": {
            "type": "string",
            "description": "Natural language task for Claude CLI to execute",
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default 120, max 300)",
        },
    }

    async def execute(self, prompt: str = "", timeout: int = 120, **kwargs) -> ToolResult:
        if not prompt.strip():
            return ToolResult(success=False, error="No prompt provided")

        timeout = min(max(timeout, 30), 300)

        claude_path = shutil.which("claude")
        if not claude_path:
            return ToolResult(
                success=False,
                error="Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
            )

        cmd = [claude_path, "-p", prompt, "--no-input"]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_PROJECT_ROOT),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            stdout_str = (stdout.decode("utf-8", errors="replace") if stdout else "").strip()
            stderr_str = (stderr.decode("utf-8", errors="replace") if stderr else "").strip()

            if process.returncode == 0:
                return ToolResult(
                    success=True,
                    output=stdout_str or "(no output)",
                    metadata={"return_code": 0},
                )
            else:
                return ToolResult(
                    success=False,
                    output=stdout_str,
                    error=stderr_str or f"Claude CLI exited with code {process.returncode}",
                    metadata={"return_code": process.returncode},
                )

        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Claude CLI timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=f"Claude CLI error: {e}")
