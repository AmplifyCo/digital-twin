"""Context Thalamus — active token budgeting and context window management.

Architecture: Heart component.
Prevents prompt bloat by enforcing token budgets per section
and summarizing long conversation histories before sending to the Brain.

Importance-weighted pruning: Instead of pure FIFO, scores each conversation
turn by decision/correction/preference signals and retains important turns
even when they fall outside the recency window. Zero LLM calls — pure
keyword scoring (~0ms per turn).
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class ContextThalamus:
    """Manages context window allocation and prevents token bloat.

    Token budgets (approximate, using ~4 chars per token):
    - System prompt (static): ~500 tokens
    - Intelligence principles: ~300 tokens
    - Security rules: ~100 tokens
    - Brain context (memories): ~400 tokens
    - Conversation history: ~2000 tokens
    - Tool definitions: ~800 tokens
    - Current message: unlimited
    Total target: ~4100 tokens of context (well within Claude's window)
    """

    # Token budgets per section (in characters, ~4 chars per token)
    BUDGET_BRAIN_CONTEXT = 1600      # ~400 tokens
    BUDGET_HISTORY = 8000            # ~2000 tokens
    BUDGET_PRINCIPLES = 1200         # ~300 tokens

    # Conversation history management
    MAX_HISTORY_TURNS = 20           # Keep last N turns in active session
    SUMMARIZE_AFTER_TURNS = 15      # Summarize older turns after this many

    def __init__(self):
        """Initialize the context thalamus."""
        self._conversation_histories: Dict[str, List[Dict[str, str]]] = {}

    def budget_brain_context(self, context: str) -> str:
        """Enforce token budget on brain context.

        Args:
            context: Raw brain context string

        Returns:
            Trimmed context within budget
        """
        if len(context) <= self.BUDGET_BRAIN_CONTEXT:
            return context

        # Truncate with indicator
        truncated = context[:self.BUDGET_BRAIN_CONTEXT - 20]
        # Cut at last complete line
        last_newline = truncated.rfind('\n')
        if last_newline > 0:
            truncated = truncated[:last_newline]

        return truncated + "\n[...truncated]"

    def budget_principles(self, principles: str) -> str:
        """Enforce token budget on intelligence principles.

        Args:
            principles: Raw principles string

        Returns:
            Trimmed principles within budget
        """
        if len(principles) <= self.BUDGET_PRINCIPLES:
            return principles

        return principles[:self.BUDGET_PRINCIPLES - 20] + "\n[...truncated]"

    # How many recent turns to always keep (recency bias)
    RECENT_TURNS_KEEP = 10
    # How many important older turns to retain
    IMPORTANT_TURNS_KEEP = 5

    def manage_history(
        self,
        session_id: str,
        new_user_msg: str,
        new_bot_msg: str
    ) -> List[Dict[str, str]]:
        """Add a turn and return managed conversation history.

        Uses importance-weighted pruning instead of pure FIFO:
        1. Always keep last RECENT_TURNS_KEEP turns (recency)
        2. From older turns, score each by importance
        3. Keep top IMPORTANT_TURNS_KEEP important older turns
        4. Summarize the rest (extractive, as before)

        Result: 15 turns max (10 recent + 5 important) instead of 20 FIFO.
        Important context (decisions, corrections, names) survives longer.

        Args:
            session_id: User/session identifier
            new_user_msg: New user message to add
            new_bot_msg: New bot response to add

        Returns:
            Managed conversation history within budget
        """
        if session_id not in self._conversation_histories:
            self._conversation_histories[session_id] = []

        history = self._conversation_histories[session_id]

        # Add new turn
        history.append({
            "role": "user",
            "content": new_user_msg
        })
        history.append({
            "role": "assistant",
            "content": new_bot_msg
        })

        # Prune if too many turns
        max_messages = self.MAX_HISTORY_TURNS * 2
        if len(history) > max_messages:
            recent_count = self.RECENT_TURNS_KEEP * 2  # user+assistant per turn
            recent_turns = history[-recent_count:]
            older_turns = history[:-recent_count]

            # Score older turns by importance and keep the top N
            scored: List[Tuple[int, int, List[Dict]]] = []  # (score, index, [user_msg, bot_msg])
            i = 0
            idx = 0
            while i < len(older_turns) - 1:
                user_msg = older_turns[i]
                bot_msg = older_turns[i + 1] if i + 1 < len(older_turns) else {"role": "assistant", "content": ""}
                if user_msg.get("role") == "user":
                    score = self._score_importance(
                        user_msg.get("content", ""),
                        bot_msg.get("content", ""),
                    )
                    scored.append((score, idx, [user_msg, bot_msg]))
                    i += 2
                else:
                    # Orphaned message — low importance
                    scored.append((0, idx, [older_turns[i]]))
                    i += 1
                idx += 1

            # Sort by importance (descending), then by position (ascending) for ties
            scored.sort(key=lambda x: (-x[0], x[1]))
            important = scored[:self.IMPORTANT_TURNS_KEEP]
            to_summarize = scored[self.IMPORTANT_TURNS_KEEP:]

            # Flatten the turns to summarize
            summary_turns = []
            for _, _, msgs in sorted(to_summarize, key=lambda x: x[1]):
                summary_turns.extend(msgs)

            summary = self._summarize_turns(summary_turns) if summary_turns else ""

            # Rebuild: summary + important (in original order) + recent
            important_sorted = sorted(important, key=lambda x: x[1])
            important_turns = []
            for _, _, msgs in important_sorted:
                important_turns.extend(msgs)

            rebuilt = []
            if summary:
                rebuilt.append({"role": "user", "content": f"[Previous conversation summary: {summary}]"})
            rebuilt.extend(important_turns)
            rebuilt.extend(recent_turns)

            self._conversation_histories[session_id] = rebuilt

        return self._conversation_histories[session_id]

    def _score_importance(self, user_msg: str, bot_msg: str) -> int:
        """Score a conversation turn by importance (0-10). Keyword-based, no LLM.

        Higher scores = more important to retain when pruning.
        Zero latency — pure string matching.
        """
        score = 0
        combined = (user_msg + " " + bot_msg).lower()

        # Decision signals (+3) — user made a choice
        if any(w in combined for w in ["let's do", "go with", "use this", "decided", "approved", "go ahead"]):
            score += 3
        # Correction signals (+3) — user corrected the bot
        if any(w in combined for w in ["no,", "wrong", "change it", "not what i", "actually", "i meant"]):
            score += 3
        # Preference signals (+2) — user stated a preference
        if any(w in combined for w in ["i prefer", "always", "never", "i like", "i don't like", "don't ever"]):
            score += 2
        # Name/contact mentions (+2) — proper nouns likely important
        if re.search(r'\b[A-Z][a-z]{2,}\b', user_msg):
            score += 2
        # Action items (+2) — user set a follow-up
        if any(w in combined for w in ["remind me", "don't forget", "make sure", "todo", "follow up"]):
            score += 2
        # Questions with substantive answers (+1)
        if "?" in user_msg and len(bot_msg) > 50:
            score += 1

        return min(score, 10)

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get current conversation history for a session."""
        return self._conversation_histories.get(session_id, [])

    def clear_history(self, session_id: str):
        """Clear conversation history for a session."""
        self._conversation_histories.pop(session_id, None)

    def _summarize_turns(self, turns: List[Dict[str, str]]) -> str:
        """Create a simple summary of conversation turns.

        This is a basic extractive summary. For production, this could
        call Haiku to generate a proper abstractive summary.

        Args:
            turns: Old conversation turns to summarize

        Returns:
            Brief summary string
        """
        topics = []
        for turn in turns:
            content = turn.get("content", "")
            if turn["role"] == "user" and len(content) > 10:
                # Take first 50 chars of each user message as topic hint
                topics.append(content[:50].strip())

        if not topics:
            return "Earlier conversation about various topics."

        # Keep up to 5 topic hints
        topic_hints = "; ".join(topics[:5])
        return f"Discussed: {topic_hints}"

    def get_stats(self) -> Dict[str, Any]:
        """Get thalamus statistics."""
        return {
            "active_sessions": len(self._conversation_histories),
            "total_messages": sum(
                len(h) for h in self._conversation_histories.values()
            )
        }
