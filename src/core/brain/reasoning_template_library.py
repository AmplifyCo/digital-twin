"""Reasoning Template Library — stores and reuses successful task decompositions.

Inspired by arXiv:2507.02004 / STELLA (self-evolving agent).

When a background task completes with a good critic score (≥ 0.70), the
goal → subtask decomposition is stored as a "template" in LanceDB. On the next
similar task, GoalDecomposer queries this library first. If a sufficiently
similar template exists (similarity ≥ 0.85), it is injected into the Gemini
prompt as an example — guiding decomposition toward proven patterns.

Benefits:
  - Reuses strategies that worked well (reduces hallucination in planning)
  - Speeds up decomposition for repeated task types
  - Builds institutional memory of Nova's problem-solving approaches

Storage: LanceDB (same backend as EpisodicMemory, DigitalCloneBrain).
Schema:  text = goal (embedded), metadata = subtasks_json + critic_score + timestamp.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from .vector_db import VectorDatabase

logger = logging.getLogger(__name__)

_MIN_CRITIC_SCORE = 0.70    # Only store templates with quality above this threshold
_MIN_SIMILARITY = 0.85      # Only reuse templates this similar to the current goal


class ReasoningTemplateLibrary:
    """Stores successful goal→subtask decompositions for future reuse.

    Uses VectorDatabase (LanceDB) — same interface as EpisodicMemory.
    """

    def __init__(self, db_path: str = "./data/lancedb"):
        self.db = VectorDatabase(
            path=db_path,
            collection_name="reasoning_templates",
        )
        logger.info("ReasoningTemplateLibrary initialized")

    async def store(
        self,
        goal: str,
        subtasks: list,
        critic_score: float,
    ) -> bool:
        """Store a successful decomposition as a reusable template.

        Args:
            goal: The high-level task goal (embedded as the search key).
            subtasks: List of Subtask objects from GoalDecomposer.
            critic_score: Quality score from CriticAgent (0.0–1.0).

        Returns:
            True if stored, False if below quality threshold.
        """
        if critic_score < _MIN_CRITIC_SCORE:
            logger.debug(f"Template skipped (critic_score={critic_score:.2f} < {_MIN_CRITIC_SCORE})")
            return False

        # Serialize subtasks to JSON (strip internal state; store only description + tool_hints)
        subtask_dicts = []
        for st in subtasks:
            subtask_dicts.append({
                "description": getattr(st, "description", str(st)),
                "tool_hints": getattr(st, "tool_hints", []),
                "model_tier": getattr(st, "model_tier", "flash"),
            })

        try:
            await self.db.store(
                text=goal,
                metadata={
                    "type": "template",
                    "subtasks_json": json.dumps(subtask_dicts),
                    "critic_score": critic_score,
                    "num_subtasks": len(subtask_dicts),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            logger.info(
                f"ReasoningTemplateLibrary: stored template for goal '{goal[:60]}' "
                f"(score={critic_score:.2f}, {len(subtask_dicts)} steps)"
            )
            return True

        except Exception as e:
            logger.warning(f"ReasoningTemplateLibrary store error: {e}")
            return False

    async def query_similar(
        self,
        goal: str,
        top_k: int = 2,
        min_similarity: float = _MIN_SIMILARITY,
    ) -> Optional[List[dict]]:
        """Find decompositions from similar past goals.

        Args:
            goal: Current task goal to match against.
            top_k: Max templates to return.
            min_similarity: Minimum cosine similarity threshold (0.85 = high bar).

        Returns:
            List of template dicts with keys: goal_text, subtasks, critic_score, similarity.
            None if no sufficiently similar templates exist.
        """
        try:
            results = await self.db.search(
                query=goal,
                n_results=top_k,
                filter_metadata={"type": "template"},
            )
        except Exception as e:
            logger.warning(f"ReasoningTemplateLibrary query error: {e}")
            return None

        if not results:
            return None

        # Filter by similarity score
        templates = []
        for r in results:
            similarity = r.get("similarity", 0.0)
            if similarity < min_similarity:
                continue
            meta = r.get("metadata", {})
            try:
                subtasks = json.loads(meta.get("subtasks_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                subtasks = []
            templates.append({
                "goal_text": r.get("text", ""),
                "subtasks": subtasks,
                "critic_score": meta.get("critic_score", 0.0),
                "similarity": similarity,
            })

        if not templates:
            logger.debug(f"ReasoningTemplateLibrary: no templates above similarity={min_similarity} for '{goal[:60]}'")
            return None

        logger.info(
            f"ReasoningTemplateLibrary: found {len(templates)} similar template(s) "
            f"for '{goal[:60]}' (best similarity={templates[0]['similarity']:.2f})"
        )
        return templates

    def format_for_prompt(self, templates: List[dict]) -> str:
        """Format retrieved templates as prompt context for GoalDecomposer.

        Returns a multi-line string showing past decompositions as examples.
        GoalDecomposer prepends this to the Gemini prompt.
        """
        if not templates:
            return ""

        lines = ["SIMILAR PAST TASK DECOMPOSITIONS (use as inspiration, adapt as needed):"]
        for i, t in enumerate(templates, 1):
            goal_text = t.get("goal_text", "unknown goal")
            subtasks = t.get("subtasks", [])
            score = t.get("critic_score", 0.0)
            lines.append(f"\nExample {i} (quality score: {score:.2f}): \"{goal_text[:120]}\"")
            for j, st in enumerate(subtasks, 1):
                desc = st.get("description", "")
                tools = st.get("tool_hints", [])
                tools_str = f" [{', '.join(tools)}]" if tools else ""
                lines.append(f"  Step {j}: {desc[:120]}{tools_str}")

        return "\n".join(lines)
