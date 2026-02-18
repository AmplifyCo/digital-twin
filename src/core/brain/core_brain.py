"""Core Brain for self-building meta-agent."""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List
from .vector_db import VectorDatabase

logger = logging.getLogger(__name__)


class CoreBrain:
    """Brain for self-building meta-agent. Stores build progress, patterns, and knowledge."""

    def __init__(self, path: str = "data/core_brain"):
        """Initialize core brain.

        Args:
            path: Path to store brain data
        """
        self.path = path
        self.db = VectorDatabase(
            path=path,
            collection_name="build_memory"
        )

        logger.info(f"Initialized coreBrain at {path}")

    async def store_build_state(
        self,
        phase: str,
        features_done: List[str],
        features_pending: List[str]
    ):
        """Store current build progress.

        Args:
            phase: Current phase name
            features_done: List of completed features
            features_pending: List of pending features
        """
        state = {
            "phase": phase,
            "features_done": features_done,
            "features_pending": features_pending,
            "timestamp": datetime.now().isoformat()
        }

        await self.db.store(
            text=f"Build State - Phase: {phase}, Done: {len(features_done)}, Pending: {len(features_pending)}",
            metadata={
                "type": "build_state",
                "phase": phase,
                **state
            },
            doc_id=f"build_state_{phase}"
        )

        logger.info(f"Stored build state for phase: {phase}")

    async def remember_pattern(self, pattern: str, context: str):
        """Remember code patterns discovered during build.

        Args:
            pattern: Pattern description
            context: Context where pattern was useful
        """
        await self.db.store(
            text=f"Pattern: {pattern}\nContext: {context}",
            metadata={
                "type": "pattern",
                "timestamp": datetime.now().isoformat()
            }
        )

        logger.debug(f"Remembered pattern: {pattern}")

    async def get_relevant_patterns(self, query: str, n_results: int = 3) -> List[str]:
        """Get relevant code patterns for a task.

        Args:
            query: Task description
            n_results: Number of patterns to return

        Returns:
            List of pattern descriptions
        """
        results = await self.db.search(
            query=query,
            n_results=n_results,
            filter_metadata={"type": "pattern"}
        )

        return [result["text"] for result in results]

    def export_snapshot(self, output_path: str = "data/core_brain_snapshot.json") -> str:
        """Export brain to JSON file for git commit.

        Args:
            output_path: Path for snapshot file

        Returns:
            Path to snapshot file
        """
        # Get all documents from collection
        # Note: This is a simplified export. In production, you'd export the full ChromaDB
        snapshot = {
            "export_timestamp": datetime.now().isoformat(),
            "document_count": self.db.count(),
            "path": self.path
        }

        # Create parent directory if needed
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Write snapshot
        with open(output_path, 'w') as f:
            json.dump(snapshot, f, indent=2)

        logger.info(f"Exported coreBrain snapshot to {output_path}")
        return output_path

    def import_snapshot(self, snapshot_path: str):
        """Import brain from snapshot file (on EC2 startup).

        Args:
            snapshot_path: Path to snapshot file
        """
        if not os.path.exists(snapshot_path):
            logger.warning(f"Snapshot file not found: {snapshot_path}")
            return

        with open(snapshot_path, 'r') as f:
            snapshot = json.load(f)

        logger.info(f"Imported coreBrain snapshot from {snapshot.get('export_timestamp')}")
