"""Core autonomous agent with self-contained execution loop."""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path
import json
import yaml

from .config import AgentConfig
from .types import ToolResult, Message
from .tools.registry import ToolRegistry
from .brain.core_brain import CoreBrain
from .brain.digital_clone_brain import DigitalCloneBrain
from ..integrations.anthropic_client import AnthropicClient
from .nervous_system.state_machine import AgentStateMachine, AgentState
from .self_healing.auto_fixer import AutoFixer
from .self_healing.error_detector import DetectedError, ErrorType, ErrorSeverity

logger = logging.getLogger(__name__)


class AutonomousAgent:
    # ── Model tier constants (LiteLLM model strings) ────────────────
    MODEL_GEMINI_FLASH = "gemini/gemini-2.0-flash"
    MODEL_GEMINI_PRO = "gemini/gemini-2.5-pro"
    MODEL_CLAUDE_SONNET = "anthropic/claude-sonnet-4-5"
    MODEL_CLAUDE_HAIKU = "anthropic/claude-haiku-4-5"
    """Main autonomous agent with self-contained execution loop."""

    def __init__(
        self,
        config: AgentConfig,
        brain: Union[CoreBrain, DigitalCloneBrain] = None,
        gemini_client=None,
        grok_client=None
    ):
        """Initialize the autonomous agent.

        Args:
            config: Agent configuration
            brain: Brain instance (CoreBrain or DigitalCloneBrain)
            gemini_client: Optional GeminiClient for fallback when Claude fails
        """
        self.config = config
        self.api_client = AnthropicClient(config.api_key)
        self.gemini_client = gemini_client
        self.grok_client = grok_client

        # Load YAML config for tool registry
        yaml_config = {}
        config_path = Path("config/agent.yaml")
        if config_path.exists():
            with open(config_path, 'r') as f:
                yaml_config = yaml.safe_load(f) or {}

        # Initialize tools with safety configuration
        tool_config = yaml_config.get("agent", {})
        self.tools = ToolRegistry(config=tool_config)
        self.brain = brain

        # Nervous System: state machine for tracking execution state + cancellation
        self.state_machine = AgentStateMachine()

        # Token budget tracking — reset at the start of each run() call
        self._run_tokens: int = 0

        # Self-Improvement System
        # Temporarily paused as per user request
        # self.auto_fixer = AutoFixer(llm_client=self.gemini_client or self.api_client)
        fallback = "+ Gemini fallback" if gemini_client else ""
        fallback += " + Grok fallback" if grok_client else ""
        logger.info(f"Initialized AutonomousAgent with {config.default_model} {fallback}")

    async def run(
        self,
        task: str,
        max_iterations: Optional[int] = None,
        system_prompt: Optional[str] = None,
        pii_map: Optional[Dict[str, str]] = None,
        model_tier: str = "sonnet",
        allowed_tools: Optional[List[str]] = None,
    ) -> str:
        """Execute task autonomously until completion.

        Args:
            task: Task description to execute
            max_iterations: Maximum iterations (defaults to config)
            system_prompt: Optional custom system prompt
            pii_map: Optional PII token mapping for de-tokenization
            model_tier: Model routing tier:
                - "flash": Gemini Flash (simple tools — reminders, contacts, clock)
                - "sonnet": Claude Sonnet (default — complex tasks, questions)
                - "quality": Claude Sonnet with retry, fallback to Gemini Pro (email compose)
            allowed_tools: Optional list of tool names to scope this run to.
                           None = all tools available. Used by TaskRunner for
                           just-in-time tool access per subtask.

        Returns:
            Final result as string
        """
        max_iterations = max_iterations or self.config.max_iterations

        # Store current task for semantic validation (Layer 11)
        self._current_task = task
        self._model_tier = model_tier
        self._run_tokens = 0  # reset per-run token counter

        # Reset state machine + policy gate for new run
        self.state_machine.reset()
        self.tools.policy_gate.reset_run_counts()
        self.state_machine.transition(AgentState.THINKING, task[:80])

        tier_label = {"flash": "⚡ Gemini Flash", "sonnet": "🧠 Claude Sonnet", "quality": "✍️ Claude Quality"}.get(model_tier, model_tier)
        logger.info(f"Starting autonomous execution [{tier_label}]: {task}")
        logger.info(f"Max iterations: {max_iterations}")

        # Load context from brain if available
        context = ""
        if self.brain:
            if hasattr(self.brain, 'get_relevant_context'):
                context = await self.brain.get_relevant_context(task)
                logger.debug(f"Loaded context from brain ({len(context)} chars)")

        # Build system prompt
        if not system_prompt:
            system_prompt = self._build_system_prompt(context)

        # Initialize conversation with task
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": task}
        ]

        # Autonomous execution loop
        iteration = 0
        final_result = None

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"Iteration {iteration}/{max_iterations}")

            try:
                # Check for cancellation
                if self.state_machine.is_cancelled():
                    logger.info("Task cancelled by user")
                    self.state_machine.reset()
                    return "Task cancelled."

                # Call LLM — all calls go through LiteLLM
                # Use scoped tool definitions if allowed_tools was specified (#1)
                self.state_machine.transition(AgentState.THINKING)
                tool_defs = self.tools.get_scoped_definitions(allowed_tools)
                response = await self._call_llm(
                    messages=messages,
                    tools=tool_defs,
                    system_prompt=system_prompt,
                    max_tokens=4096,
                    model_tier=model_tier
                )

                # Accumulate token usage for budget monitoring
                try:
                    if hasattr(response, "usage") and response.usage:
                        self._run_tokens += getattr(response.usage, "input_tokens", 0)
                        self._run_tokens += getattr(response.usage, "output_tokens", 0)
                except Exception:
                    pass

                # Process response
                if response.stop_reason == "end_turn":
                    # Task complete
                    final_result = self._extract_text_from_response(response)
                    logger.info("Task completed (end_turn)")
                    break

                elif response.stop_reason == "tool_use":
                    # Execute tools
                    self.state_machine.transition(AgentState.EXECUTING)
                    logger.info("Executing tool calls...")

                    # Add assistant message
                    messages.append({
                        "role": "assistant",
                        "content": response.content
                    })

                    # Execute all tool calls
                    tool_results = await self._execute_tool_calls(response.content, pii_map)

                    # Add tool results as user message
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })

                elif response.stop_reason == "max_tokens":
                    # Continue with more tokens
                    logger.warning("Hit max tokens, continuing...")
                    messages.append({
                        "role": "assistant",
                        "content": response.content
                    })
                    continue

                else:
                    # Unknown stop reason
                    logger.warning(f"Unknown stop reason: {response.stop_reason}")
                    final_result = self._extract_text_from_response(response)
                    break

                # Store interaction in brain
                if self.brain and hasattr(self.brain, 'memory'):
                    await self._store_interaction(task, response)

            except Exception as e:
                error_str = str(e)
                logger.error(f"Error in iteration {iteration}: {e}", exc_info=True)

                # Rate limit — wait and retry instead of crashing
                if "429" in error_str or "rate_limit" in error_str:
                    wait_time = min(60 * (2 ** (iteration - 1)), 300)
                    logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    continue

                # Other errors — retry with limit
                if iteration < self.config.retry_attempts:
                    logger.info(f"Retrying... (attempt {iteration + 1})")
                    continue
                else:
                    raise

            # Space out requests to avoid rate limits
            await asyncio.sleep(1.0)

        # Handle max iterations reached — try Gemini summary
        if iteration >= max_iterations and not final_result:
            logger.warning(f"Reached max iterations ({max_iterations})")
            final_result = await self._summarize_with_fallback(messages, system_prompt)

        logger.info(f"Execution complete after {iteration} iterations")
        self.state_machine.transition(AgentState.RESPONDING)
        self.state_machine.reset()
        return final_result or "Task completed"

    # ── Model tier constants (LiteLLM model strings) ────────────────
    MODEL_GEMINI_FLASH = "gemini/gemini-2.0-flash"
    MODEL_GEMINI_PRO = "gemini/gemini-2.5-pro"
    MODEL_CLAUDE_SONNET = "anthropic/claude-sonnet-4-5"
    MODEL_CLAUDE_HAIKU = "anthropic/claude-haiku-4-5"

    @property
    def last_run_tokens(self) -> int:
        """Total tokens consumed by the most recent run() call.

        Accumulated from every _call_llm() iteration within that run.
        Used by TaskRunner to enforce per-task token budgets.
        """
        return self._run_tokens

    async def _call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: str,
        max_tokens: int = 4096,
        model_tier: str = "sonnet"
    ):
        """Route LLM call through LiteLLM based on model tier.

        ALL calls go through LiteLLM for unified provider management.
        Every tier has cross-provider fallback (Gemini ↔ Claude).

        Tiers:
            flash:   Gemini Flash → Claude Sonnet fallback
            haiku:   Gemini Flash → Claude Haiku fallback
            sonnet:  Gemini Flash → Claude Sonnet fallback
            quality: Claude Sonnet → retry on 429 → Gemini Pro fallback
        """
        has_litellm = self.gemini_client and self.gemini_client.enabled

        if not has_litellm:
            # No LiteLLM — use direct Anthropic client with a Claude model
            # (config.default_model may be a Gemini string, so use a safe Claude model)
            claude_model = "claude-sonnet-4-5"
            logger.info(f"🧠 Direct Anthropic → {claude_model} (no LiteLLM)")
            return await self.api_client.create_message(
                model=claude_model,
                messages=messages, tools=tools,
                system=system_prompt, max_tokens=max_tokens
            )

        if model_tier == "flash":
            # ── Gemini Flash primary → Claude Sonnet fallback ──
            try:
                logger.info("⚡ LiteLLM → Gemini Flash")
                return await self.gemini_client.create_message(
                    model=self.MODEL_GEMINI_FLASH,
                    messages=messages, tools=tools,
                    system=system_prompt, max_tokens=max_tokens
                )
            except Exception as e:
                logger.warning(f"Gemini Flash failed ({str(e)[:60]}), falling back to Claude Sonnet...")
                try:
                    return await self.gemini_client.create_message(
                        model=self.MODEL_CLAUDE_SONNET,
                        messages=messages, tools=tools,
                        system=system_prompt, max_tokens=max_tokens
                    )
                except Exception as claude_err:
                    if self.grok_client and self.config.grok_enabled:
                        logger.warning(f"Claude Sonnet failed ({str(claude_err)[:60]}), falling back to Grok...")
                        try:
                            return await self.grok_client.create_message(
                                model=self.config.grok_models["flash"],
                                messages=messages, tools=tools,
                                system=system_prompt, max_tokens=max_tokens
                            )
                        except Exception as grok_err:
                            logger.error(f"Grok also failed: {grok_err}")
                            raise claude_err
                    else:
                        logger.error(f"Claude Sonnet failed: {claude_err}")
                        raise claude_err

        elif model_tier == "haiku":
            # ── Gemini Flash primary → Claude Haiku fallback ──
            try:
                logger.info("⚡ LiteLLM → Gemini Flash (haiku tier)")
                return await self.gemini_client.create_message(
                    model=self.MODEL_GEMINI_FLASH,
                    messages=messages, tools=tools,
                    system=system_prompt, max_tokens=max_tokens
                )
            except Exception as e:
                logger.warning(f"Gemini Flash failed ({str(e)[:60]}), falling back to Claude Haiku...")
                try:
                    return await self.gemini_client.create_message(
                        model=self.MODEL_CLAUDE_HAIKU,
                        messages=messages, tools=tools,
                        system=system_prompt, max_tokens=max_tokens
                    )
                except Exception as claude_err:
                    if self.grok_client and self.config.grok_enabled:
                        logger.warning(f"Claude Haiku failed ({str(claude_err)[:60]}), falling back to Grok...")
                        try:
                            return await self.grok_client.create_message(
                                model=self.config.grok_models["haiku"],
                                messages=messages, tools=tools,
                                system=system_prompt, max_tokens=max_tokens
                            )
                        except Exception as grok_err:
                            logger.error(f"Grok also failed: {grok_err}")
                            raise claude_err
                    else:
                        logger.error(f"Claude Haiku failed: {claude_err}")
                        raise claude_err

        elif model_tier == "quality":
            # ── Claude Sonnet primary → retry on 429 → Gemini Pro fallback ──
            for attempt in range(2):
                try:
                    logger.info(f"✍️ LiteLLM → Claude Sonnet (quality, attempt {attempt + 1})")
                    return await self.gemini_client.create_message(
                        model=self.MODEL_CLAUDE_SONNET,
                        messages=messages, tools=tools,
                        system=system_prompt, max_tokens=max_tokens
                    )
                except Exception as e:
                    error_str = str(e)
                    if attempt == 0 and ("429" in error_str or "rate_limit" in error_str or "overloaded" in error_str):
                        logger.warning(f"Claude rate-limited, waiting 30s before retry...")
                        await asyncio.sleep(30)
                        continue
                    # Final attempt failed — fall back to Gemini Pro
                    logger.warning(f"Claude failed after retry ({error_str[:60]}), using Gemini Pro...")
                    try:
                        return await self.gemini_client.create_message(
                            model=self.MODEL_GEMINI_PRO,
                            messages=messages, tools=tools,
                            system=system_prompt, max_tokens=max_tokens
                        )
                    except Exception as pro_error:
                        if self.grok_client and self.config.grok_enabled:
                            logger.warning(f"Gemini Pro failed ({str(pro_error)[:60]}), falling back to Grok...")
                            try:
                                return await self.grok_client.create_message(
                                    model=self.config.grok_models["quality"],
                                    messages=messages, tools=tools,
                                    system=system_prompt, max_tokens=max_tokens
                                )
                            except Exception as grok_err:
                                logger.error(f"Grok also failed: {grok_err}")
                                raise pro_error
                        else:
                            logger.error(f"Gemini Pro failed: {pro_error}")
                            raise pro_error

        else:
            # ── Standard/Sonnet: Gemini Flash primary → Claude Sonnet fallback ──
            try:
                logger.info(f"🧠 LiteLLM → Gemini Flash (sonnet tier)")
                return await self.gemini_client.create_message(
                    model=self.MODEL_GEMINI_FLASH,
                    messages=messages, tools=tools,
                    system=system_prompt, max_tokens=max_tokens
                )
            except Exception as e:
                logger.warning(f"Gemini Flash failed ({str(e)[:60]}), falling back to Claude Sonnet...")
                try:
                    return await self.gemini_client.create_message(
                        model=self.MODEL_CLAUDE_SONNET,
                        messages=messages, tools=tools,
                        system=system_prompt, max_tokens=max_tokens
                    )
                except Exception as claude_err:
                    if self.grok_client and self.config.grok_enabled:
                        logger.warning(f"Claude Sonnet failed ({str(claude_err)[:60]}), falling back to Grok...")
                        try:
                            return await self.grok_client.create_message(
                                model=self.config.grok_models["sonnet"],
                                messages=messages, tools=tools,
                                system=system_prompt, max_tokens=max_tokens
                            )
                        except Exception as grok_err:
                            logger.error(f"Grok also failed: {grok_err}")
                            raise claude_err
                    else:
                        logger.error(f"Claude Sonnet failed: {claude_err}")
                        raise claude_err

    async def _summarize_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str
    ) -> str:
        """When max iterations reached, try to generate a final response.

        Uses Gemini Flash first, falls back to Claude Sonnet via LiteLLM.
        """
        summary_messages = messages + [{
            "role": "user",
            "content": "You have reached the maximum number of tool-use iterations. Based on all the tool results above, please provide a final, complete response to the user's original question. Do NOT call any more tools."
        }]

        if self.gemini_client and self.gemini_client.enabled:
            # Try Gemini Flash first (cheaper, less likely rate-limited)
            try:
                logger.info("⚡ Max iterations — summarizing via Gemini Flash")
                response = await self.gemini_client.create_message(
                    model=self.MODEL_GEMINI_FLASH,
                    messages=summary_messages,
                    system=system_prompt,
                    max_tokens=2048
                )
                text = self._extract_text_from_response(response)
                if text:
                    return text
            except Exception as e:
                logger.warning(f"Gemini summary failed: {e}")

            # Fallback: Claude Sonnet via LiteLLM
            try:
                logger.info("Max iterations — summarizing via Claude Sonnet (LiteLLM)")
                response = await self.gemini_client.create_message(
                    model=self.MODEL_CLAUDE_SONNET,
                    messages=summary_messages,
                    system=system_prompt,
                    max_tokens=2048
                )
                text = self._extract_text_from_response(response)
                if text:
                    return text
            except Exception as e:
                logger.warning(f"Claude summary also failed: {e}")
        else:
            # No LiteLLM — direct Anthropic
            try:
                logger.info("Max iterations — summarizing via direct Claude")
                response = await self.api_client.create_message(
                    model="claude-sonnet-4-5",
                    messages=summary_messages,
                    system=system_prompt,
                    max_tokens=2048
                )
                text = self._extract_text_from_response(response)
                if text:
                    return text
            except Exception as e:
                logger.warning(f"Direct Claude summary failed: {e}")

        return "I gathered some information but couldn't complete the full analysis. Please try again."

    async def _execute_tool_calls(
        self,
        content: List[Any],
        pii_map: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """Execute tool calls from Claude's response (parallel when safe).

        Args:
            content: Response content blocks

        Returns:
            List of tool result content blocks
        """
        # Collect all tool_use blocks
        tool_blocks = [b for b in content if b.type == "tool_use"]

        if not tool_blocks:
            return []

        # Execute all tool calls in parallel
        async def _run_single_tool(block):
            tool_name = block.name
            tool_input = block.input
            tool_use_id = block.id

            # De-tokenize PII in tool inputs if map provided
            if pii_map:
                # Recursive de-tokenization for nested dicts/lists
                def detokenize_value(val):
                    if isinstance(val, str):
                        for placeholder, original in pii_map.items():
                            val = val.replace(placeholder, original)
                        return val
                    elif isinstance(val, dict):
                        return {k: detokenize_value(v) for k, v in val.items()}
                    elif isinstance(val, list):
                        return [detokenize_value(v) for v in val]
                    return val

                try:
                    tool_input = detokenize_value(tool_input)
                    logger.debug(f"De-tokenized tool input for {tool_name}")
                except Exception as e:
                    logger.warning(f"Failed to de-tokenize tool input: {e}")

            logger.info(f"Executing tool: {tool_name}")
            logger.debug(f"Tool input: {tool_input}")

            result = await self.tools.execute_tool(
                tool_name,
                user_message=getattr(self, '_current_task', ''),
                llm_client=self.api_client,
                **tool_input
            )

            if result.success and result.content_blocks is not None:
                content = result.content_blocks
            elif result.success:
                content = result.output or ""
            else:
                content = f"Error: {result.error}"

                # ── SELF-IMPROVEMENT LOOP ──
                # Check for "Missing Feature" errors (e.g. "Unknown operation")
                if getattr(self, 'auto_fixer', None):
                    is_missing_feature = any(
                        p in result.error for p in ["Unknown operation", "Tool not found", "operation not supported"]
                    )
                    if is_missing_feature:
                        logger.info(f"💡 Detected missing feature in tool {tool_name}: {result.error}")
                        
                        # Find source file
                        file_path = self.tools.get_tool_file_path(tool_name)
                        if file_path:
                            # Create error context with file path (critical for _fix_code_error)
                            error_context = f"Tool: {tool_name}\nError: {result.error}\nFile \"{file_path}\", line 1"
                            
                            detected_error = DetectedError(
                                error_type=ErrorType.MISSING_FEATURE,
                                severity=ErrorSeverity.MEDIUM,
                                message=result.error,
                                timestamp=datetime.now(),
                                context=error_context,
                                auto_fixable=True
                            )
                            
                            # Attempt auto-fix (write code)
                            fix_result = await self.auto_fixer.attempt_fix(detected_error)
                            
                            if fix_result.success:
                                content += f"\n\n✨ I have automatically implemented this feature in `{Path(file_path).name}`.\n" \
                                           f"Please RESTART the service to use it:\n" \
                                           f"```bash\nsudo systemctl restart novabot\n```"
                                logger.info(f"Auto-implemented feature for {tool_name}")

            tool_result = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }

            if not result.success:
                tool_result["is_error"] = True

            logger.info(f"Tool {tool_name}: {'Success' if result.success else 'Failed'}")
            return tool_result

        # Single tool: run directly. Multiple tools: run in parallel.
        if len(tool_blocks) == 1:
            return [await _run_single_tool(tool_blocks[0])]

        logger.info(f"Running {len(tool_blocks)} tool calls in parallel")
        results = await asyncio.gather(
            *[_run_single_tool(b) for b in tool_blocks],
            return_exceptions=True
        )

        # Handle any exceptions from gather
        tool_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Tool {tool_blocks[i].name} raised exception: {result}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_blocks[i].id,
                    "content": f"Error: {str(result)}",
                    "is_error": True
                })
            else:
                tool_results.append(result)

        return tool_results

    def _extract_text_from_response(self, response) -> str:
        """Extract text content from Claude response.

        Args:
            response: API response

        Returns:
            Extracted text
        """
        text_parts = []

        for block in response.content:
            if hasattr(block, 'text'):
                text_parts.append(block.text)

        return "\n".join(text_parts) if text_parts else ""

    def _build_system_prompt(self, context: str = "") -> str:
        """Build system prompt for the agent.

        Args:
            context: Optional context from brain

        Returns:
            System prompt string
        """
        prompt = """You are an autonomous AI agent with the ability to execute tasks independently.

You have access to tools for:
- Executing bash commands
- Reading and writing files
- Fetching web content

Your goal is to complete the given task autonomously. Work methodically:
1. Analyze the task
2. Break it into steps
3. Use available tools to accomplish each step
4. Verify your work
5. Report completion

Be thorough, check for errors, and only report completion when the task is truly done.

COMMUNICATION STYLE:
- Be EXTREMELY concise — 1-2 sentences for confirmations, short paragraphs only when needed
- Never add filler, preambles, or unsolicited tips ("Here's what I did...", "You can now...")
- Use natural, conversational language
- Just confirm the action or answer the question, nothing more

CRITICAL REQUIREMENTS:
- NEVER hallucinate or provide synthetic/made-up information
- Only provide factual information based on actual data from tools
- If you don't know something, say so clearly rather than guessing
- Base all responses on verified information from tool outputs
- NEVER wrap your response in XML tags (no <result>, <attemptcompletion>, <analysis>, etc.)
- Respond in plain text or Markdown only"""

        if context:
            prompt += f"\n\nRelevant context:\n{context}"

        return prompt

    async def _store_interaction(self, task: str, response):
        """Store interaction in brain for future reference.

        Args:
            task: Original task
            response: API response
        """
        try:
            # Extract key information
            text = self._extract_text_from_response(response)

            # Store in brain's memory
            await self.brain.memory.store(
                text=f"Task: {task}\nResponse: {text}",
                metadata={
                    "type": "interaction",
                    "task": task,
                    "timestamp": datetime.now().isoformat(),
                    "stop_reason": response.stop_reason
                }
            )

            logger.debug("Stored interaction in brain")

        except Exception as e:
            logger.warning(f"Failed to store interaction in brain: {e}")

    @classmethod
    def from_config(cls, config_path: str = ".env"):
        """Create agent from configuration file.

        Args:
            config_path: Path to .env file

        Returns:
            AutonomousAgent instance
        """
        from .config import load_config

        config = load_config(config_path)

        # Initialize appropriate brain
        if config.self_build_mode:
            brain = CoreBrain(config.core_brain_path)
        else:
            brain = DigitalCloneBrain(config.digital_clone_brain_path)

        return cls(config, brain)
