"""Capability fixer sub-agent that implements missing tool capabilities.

When the ResponseInterceptor detects a capability gap (e.g., "unable to
retrieve tweets"), this module reads the relevant tool's source code,
asks an LLM to generate the missing method(s), and applies the patch
via the existing AutoFixer pipeline.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from .auto_fixer import AutoFixer, FixResult
from .error_detector import DetectedError, ErrorType, ErrorSeverity

logger = logging.getLogger(__name__)


class CapabilityFixer:
    """Sub-agent that analyzes tool source code and adds missing capabilities."""

    def __init__(self, auto_fixer: AutoFixer, llm_client=None):
        """Initialize capability fixer.

        Args:
            auto_fixer: AutoFixer instance for applying patches
            llm_client: LLM client for code generation
        """
        self.auto_fixer = auto_fixer
        self.llm_client = llm_client or auto_fixer.llm_client

        logger.info("CapabilityFixer initialized")

    async def fix(
        self,
        gap_description: str,
        tool_name: str,
        tool_file_path: str
    ) -> FixResult:
        """Analyze a tool and implement the missing capability.

        Args:
            gap_description: What capability is missing
            tool_name: Name of the tool (e.g., "x_post")
            tool_file_path: Absolute path to the tool's source file

        Returns:
            FixResult indicating success/failure
        """
        logger.info(f"CapabilityFixer: fixing '{gap_description}' in {tool_name}")

        if not self.llm_client:
            return FixResult(
                success=False,
                error_type=ErrorType.MISSING_FEATURE,
                action_taken="No LLM client available",
                details="Cannot generate code without an LLM client"
            )

        # 1. Read tool source code
        try:
            with open(tool_file_path, 'r') as f:
                source_code = f.read()
        except Exception as e:
            return FixResult(
                success=False,
                error_type=ErrorType.MISSING_FEATURE,
                action_taken="Could not read tool file",
                details=str(e)
            )

        # 2. Generate fix via LLM
        try:
            fix_diff = await self._generate_capability_fix(
                gap_description=gap_description,
                tool_name=tool_name,
                source_code=source_code,
                file_path=tool_file_path
            )
        except Exception as e:
            return FixResult(
                success=False,
                error_type=ErrorType.MISSING_FEATURE,
                action_taken="LLM code generation failed",
                details=str(e)
            )

        if not fix_diff:
            return FixResult(
                success=False,
                error_type=ErrorType.MISSING_FEATURE,
                action_taken="LLM declined to generate fix",
                details="The LLM could not produce a valid diff"
            )

        # 3. Create a DetectedError to pass through AutoFixer pipeline
        #    This reuses the existing security check → apply → git branch flow
        error = DetectedError(
            error_type=ErrorType.MISSING_FEATURE,
            severity=ErrorSeverity.MEDIUM,
            message=f"Missing capability: {gap_description}",
            timestamp=datetime.now(),
            context=f'Tool: {tool_name}\nFile "{tool_file_path}", line 1',
            auto_fixable=True
        )

        # 4. Delegate to AutoFixer's code fix pipeline
        #    We override _generate_ai_fix to use our pre-generated diff
        original_generate = self.auto_fixer._generate_ai_fix

        async def _use_pregenerated_fix(err, fp, code):
            return fix_diff

        try:
            self.auto_fixer._generate_ai_fix = _use_pregenerated_fix
            result = await self.auto_fixer._fix_code_error(error)
        finally:
            self.auto_fixer._generate_ai_fix = original_generate

        if result.success:
            logger.info(f"✨ CapabilityFixer: successfully added '{gap_description}' to {tool_name}")
        else:
            logger.warning(f"CapabilityFixer: failed to add '{gap_description}': {result.details}")

        return result

    async def _generate_capability_fix(
        self,
        gap_description: str,
        tool_name: str,
        source_code: str,
        file_path: str
    ) -> Optional[str]:
        """Generate a unified diff that adds the missing capability.

        Args:
            gap_description: What capability to add
            tool_name: Tool name
            source_code: Current tool source code
            file_path: Absolute path to the tool file

        Returns:
            Unified diff string, or None if LLM cannot generate one
        """
        prompt = f"""You are a Python code expert. A tool is missing a capability that needs to be added.

TOOL NAME: {tool_name}
FILE PATH: {file_path}
MISSING CAPABILITY: {gap_description}

CURRENT SOURCE CODE:
```python
{source_code}
```

INSTRUCTIONS:
1. Read the existing code carefully to understand the patterns used (class structure, async methods, OAuth, error handling, etc.)
2. Add the missing capability by:
   a. Adding a new async method following the existing patterns (error handling, OAuth, asyncio.run_in_executor, etc.)
   b. Adding to the `execute()` method's dispatch (the if/elif chain)
   c. Adding to the `parameters` dict if there's a new parameter or enum value
3. Generate a unified diff (--- a/file, +++ b/file format)
4. Make sure the patch is minimal — only add what's needed, don't modify existing working code
5. Follow the exact code style of the existing file

CRITICAL:
- Use the EXACT file path in the diff header
- The diff must be a valid unified diff that can be applied with `patch -p0`
- Do NOT remove or modify any existing methods
- Make the new method async and use run_in_executor for blocking HTTP calls (matching existing patterns)

Reply with ONLY the unified diff, no explanation or markdown fences."""

        try:
            response = await self.llm_client.create_message(
                model="anthropic/claude-sonnet-4-20250514",
                messages=[{"role": "user", "content": prompt}],
                system="You are a code generation expert. Output only valid unified diffs.",
                max_tokens=4096
            )

            # Extract diff text
            diff_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    diff_text += block.text

            # Strip markdown fences if present
            diff_text = re.sub(r"```diff?\s*\n?", "", diff_text)
            diff_text = re.sub(r"\n?```\s*$", "", diff_text)
            diff_text = diff_text.strip()

            # Validate it looks like a unified diff
            if not diff_text or "---" not in diff_text or "+++" not in diff_text:
                logger.warning("LLM output doesn't look like a valid diff")
                return None

            return diff_text

        except Exception as e:
            logger.error(f"Failed to generate capability fix: {e}")
            return None
