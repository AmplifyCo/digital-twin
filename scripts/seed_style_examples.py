"""One-time script to seed style examples from user's existing posts.

Usage:
    python scripts/seed_style_examples.py --manual FILE
    python scripts/seed_style_examples.py --manual FILE --platform linkedin
    python scripts/seed_style_examples.py --manual FILE --platform x

The FILE should contain posts separated by blank lines (double newline).
Each block becomes one style example stored in DigitalCloneBrain.identity.

Example file format:
    This is my first LinkedIn post about AI agents.
    They are changing how we work.

    This is my second post.
    It talks about something else entirely.

    Third post here...
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.brain.digital_clone_brain import DigitalCloneBrain

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def seed_from_file(file_path: str, platform: str = "general"):
    """Read posts from file and store as style examples."""
    path = Path(file_path)
    if not path.exists():
        logger.error(f"File not found: {file_path}")
        return

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        logger.error("File is empty")
        return

    # Split on double newlines (blank line between posts)
    blocks = [b.strip() for b in text.split("\n\n\n") if b.strip()]

    # If triple-newline split gives only 1 block, try double-newline
    if len(blocks) <= 1:
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]

    # Filter out very short blocks (likely headers or noise)
    posts = [b for b in blocks if len(b) > 30]

    if not posts:
        logger.error("No posts found (blocks must be >30 chars). Check file format.")
        return

    logger.info(f"Found {len(posts)} posts in {file_path}")

    # Initialize brain
    brain = DigitalCloneBrain()
    stored = 0

    for i, post in enumerate(posts):
        try:
            await brain.learn_communication_style(
                sample=post[:1000],  # Cap at 1000 chars per example
                context=platform,
            )
            stored += 1
            logger.info(f"  [{i+1}/{len(posts)}] Stored ({len(post)} chars): {post[:60]}...")
        except Exception as e:
            logger.warning(f"  [{i+1}/{len(posts)}] Failed: {e}")

    logger.info(f"\nDone: {stored}/{len(posts)} posts stored as {platform} style examples")
    logger.info(f"These will be injected as few-shot examples when Nova composes {platform} content.")


def main():
    parser = argparse.ArgumentParser(
        description="Seed style examples from existing posts"
    )
    parser.add_argument(
        "--manual", required=True,
        help="Path to text file with posts (separated by blank lines)"
    )
    parser.add_argument(
        "--platform", default="general",
        choices=["general", "linkedin", "x", "email"],
        help="Platform these posts are from (default: general)"
    )

    args = parser.parse_args()
    asyncio.run(seed_from_file(args.manual, args.platform))


if __name__ == "__main__":
    main()
