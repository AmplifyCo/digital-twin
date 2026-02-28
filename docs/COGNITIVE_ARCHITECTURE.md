# Cognitive Architecture — Nova's Intelligence Layer

Nova's intelligence is built as a cognitive architecture where Python orchestrates (the "prefrontal cortex") and LLMs do the heavy computation. This document covers the 6 cognitive capabilities added to close the gap between "prompt bot" and genuine cognitive agent.

## Overview

| Capability | What It Does | Latency | When It Fires |
|------------|-------------|---------|---------------|
| Planning Loop | Re-plans mid-task when things go wrong | ~1s | Background tasks with failures |
| Memory Query Tool | Agent queries its own memory mid-task | ~10ms | Agent decides when |
| Neuro-Symbolic Reasoning | Structured signals injected into LLM prompts | ~0ms | Every action task |
| Pre-Flight Reasoning | Think before acting (KNOW/NEED/APPROACH/RISK) | ~0.5-1s | Sonnet/quality tier only |
| Strategy Memory | Remember what worked, recall for similar tasks | ~10ms | Every action + after success |
| Importance-Weighted History | Keep decisions/corrections when pruning history | ~0ms | Every conversation turn |

Simple tasks (flash tier: greetings, reminders, clock) get **zero** additional latency.

---

## 1. Planning Loop (Observe-Plan-Act-Correct)

**Problem**: TaskRunner ran waves linearly. If wave 2 revealed the plan was wrong, waves 3-7 still ran as originally decomposed.

**Solution**: `_replan_between_waves()` in `task_runner.py`. After each wave completes, evaluates whether remaining steps still make sense. If not, calls GoalDecomposer with context of what worked/failed to revise the remaining plan.

**Key constraints**:
- Max 1 replan per task (flag prevents loops)
- Only triggers on wave boundaries with failures or 3+ completed results
- Fail-open: any error keeps original plan
- Uses Gemini Flash (~1s) for evaluation

**File**: `src/core/task_runner.py` — `_replan_between_waves()`

---

## 2. Memory Query Tool (Active Memory Reasoning)

**Problem**: Agent got memory context once at start (system prompt). During multi-turn tool execution, it couldn't query memory. Couldn't say "let me check what I know about this person" mid-task.

**Solution**: `MemoryQueryTool` — a tool the agent can call during execution. Four operations:

| Operation | What It Searches | Example Query |
|-----------|-----------------|---------------|
| `episodes` | Past events and outcomes | "what happened when I emailed John?" |
| `context` | Preferences, contacts, history | "what do I know about John?" |
| `style` | Communication patterns | "how does the principal write on LinkedIn?" |
| `failures` | Past tool errors | "what went wrong with web_search?" |

**Wiring**:
- Tool: `src/core/tools/memory_tool.py`
- Registration: `registry.py` → `_register_memory_tool()` + `set_memory_sources()`
- Risk: `policy_gate.py` → READ (always safe)
- Scoping: Added to `_SAFE_READONLY_TOOLS` (always available to agent)
- Init: `main.py` → `agent.tools.set_memory_sources(brain=digital_brain, episodic_memory=episodic_memory)`

---

## 3. Neuro-Symbolic Reasoning

**Problem**: ToneAnalyzer detected mood, PolicyGate classified risk, EpisodicMemory had tool stats — but the LLM never saw these signals. It didn't know WHY it was told "be brief" or that LinkedIn had 85% success rate.

**Solution**: `ReasoningContext` dataclass assembles all symbolic signals into a structured block, injected into the agent's task prompt. The LLM reasons WITH rules, not just constrained by them.

**Signals injected**:
- **Tone**: "urgent (urgency=0.9)" — from ToneAnalyzer
- **Risk**: "HIGH — linkedin post_text is irreversible" — from PolicyGate TOOL_RISK_MAP
- **Tool Reliability**: "linkedin: 85% success (20 uses)" — from EpisodicMemory
- **Constraints**: "Calibration: be more concise" — from WorkingMemory
- **Memory Confidence**: "strong context available" — from brain context length

**Files**:
- `src/core/brain/reasoning_context.py` — `ReasoningContext.build()` + `.to_prompt()`
- Injected in `conversation_manager.py` → `_build_execution_plan()`

**Latency**: Zero new LLM calls. Just string formatting.

---

## 4. Pre-Flight Reasoning (Cognitive Architecture)

**Problem**: Message goes straight to intent → agent.run() → response. No "think before acting" step. For complex tasks, the agent dives in without planning.

**Solution**: `_preflight_reasoning()` — a cheap Gemini Flash call that produces structured reasoning BEFORE agent.run():

```
1. KNOW: What do I already know from context?
2. NEED: What information am I missing?
3. APPROACH: Best sequence of actions? (3 max)
4. RISK: What could go wrong?
```

**Gate**: Only fires for sonnet/quality tier tasks. Flash/haiku (reminders, simple lookups) skip it entirely.

**File**: `src/core/conversation_manager.py` — `_preflight_reasoning()`
- Called in `_execute_with_primary_model()` action branch
- Passed to `_build_execution_plan(preflight=...)` and appended as "PRE-FLIGHT REASONING" block
- 3-second hard timeout, fail-open (returns "" on error)

---

## 5. Strategy Memory (Scaling/Evolution)

**Problem**: Nova didn't get better at tasks it had done before. Template library cached decompositions but not the actual approach that worked (which tools, what order, what to avoid).

**Solution**: Two new methods on `EpisodicMemory`:

- **`record_strategy(goal, approach, tools_used, score)`** — stores winning approach after critic score >= 0.75. Only successful strategies recorded (prevents hallucination loops).
- **`recall_strategies(goal, n=2)`** — vector similarity search finds semantically similar strategies even if keywords differ.

**Key design**:
- Uses LanceDB vector search (OpenAI/HuggingFace embeddings) for semantic matching
- Only records on success (critic_score >= 0.75) — no failure loops
- Persists on disk — survives restarts
- Complementary to ReasoningTemplateLibrary: templates cache DECOMPOSITION, strategies cache APPROACH

**Wiring**:
- Record: `task_runner.py` — after critic validation + template storage
- Recall: `conversation_manager.py` → `_build_execution_plan()` — injected as "PROVEN STRATEGIES"

---

## 6. Importance-Weighted History

**Problem**: ContextThalamus used pure FIFO pruning. After 20 turns, old messages were summarized to topic words and dropped. Important context (decisions, corrections, names) got lost.

**Solution**: `_score_importance()` — keyword-based scoring, zero LLM calls:

| Signal | Score | Keywords |
|--------|-------|----------|
| Decisions | +3 | "let's do", "go with", "approved", "go ahead" |
| Corrections | +3 | "no,", "wrong", "change it", "actually", "i meant" |
| Preferences | +2 | "i prefer", "always", "never", "i like" |
| Proper nouns | +2 | Regex: `\b[A-Z][a-z]{2,}\b` |
| Action items | +2 | "remind me", "don't forget", "make sure" |
| Q&A | +1 | "?" in user msg + substantive answer |

**Pruning strategy** (replaces FIFO):
1. Always keep last 10 turns (recency)
2. From older turns, score each by importance
3. Keep top 5 important older turns
4. Summarize the rest

**Wiring**:
- `context_thalamus.py` — `manage_history()` called from conversation_manager at turn storage
- `_get_recent_history_for_intent()` reads from thalamus as primary source (deque as fallback)

---

## Data Flow

```
User Message
    │
    ▼
Intent Classification (Gemini Flash)
    │
    ├── Tone Analysis (rule-based, 0ms)
    ├── Tool Performance Stats (LanceDB, 10ms)
    ├── Strategy Recall (LanceDB vector search, 10ms)
    │
    ▼
Pre-Flight Reasoning (Gemini Flash, sonnet/quality only, ~1s)
    │
    ▼
Build Execution Plan
    ├── Episodic Recall (past events)
    ├── Style Examples (content_writer persona)
    ├── Research Directive (topic-based content)
    ├── Strategy Injection (proven approaches)
    ├── Reasoning Context (symbolic signals)
    └── Pre-Flight Plan (KNOW/NEED/APPROACH/RISK)
    │
    ▼
Agent.run() (ReAct loop)
    ├── Can call memory_query tool mid-execution
    ├── PolicyGate checks each tool call
    └── Tool results feed back into loop
    │
    ▼
Response
    ├── Content Reflection (critic, content_writer only)
    ├── Episode Recording (outcome tracking)
    ├── Importance-Weighted History Update
    └── Strategy Recording (background tasks, score >= 0.75)
```

## Files Modified

| File | Changes |
|------|---------|
| `src/core/task_runner.py` | `_replan_between_waves()`, while loop, strategy recording |
| `src/core/tools/memory_tool.py` | NEW — MemoryQueryTool |
| `src/core/tools/registry.py` | `_register_memory_tool()`, `set_memory_sources()` |
| `src/core/nervous_system/policy_gate.py` | `memory_query` → READ |
| `src/core/brain/reasoning_context.py` | NEW — ReasoningContext dataclass |
| `src/core/brain/episodic_memory.py` | `record_strategy()`, `recall_strategies()` |
| `src/core/context_thalamus.py` | `_score_importance()`, importance-weighted `manage_history()` |
| `src/core/conversation_manager.py` | `_preflight_reasoning()`, all injections, thalamus wiring |
| `src/main.py` | `set_memory_sources()` wiring |

## Verification

Test via Telegram after deploy:

1. **Planning Loop**: Queue a research task where a step will fail → check logs for "Adjusting plan"
2. **Memory Tool**: Ask "write a LinkedIn post about X" → check if agent calls `memory_query` for style
3. **Reasoning Context**: Ask to post on LinkedIn → check logs for "REASONING CONTEXT" block
4. **Pre-Flight**: Ask a complex question (sonnet tier) → check logs for "PRE-FLIGHT REASONING"
5. **Strategy Recall**: After 2-3 successful background tasks → check for "PROVEN STRATEGIES" in logs
6. **Importance Scoring**: 25+ turn conversation with decisions → verify important turns retained
