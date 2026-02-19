#!/usr/bin/env python3
"""Initial setup script for the autonomous agent."""

import os
import sys
from pathlib import Path


def setup():
    """Perform initial setup."""

    print("🔧 Setting up Autonomous Claude Agent...")
    print()

    # 1. Create directory structure
    dirs = [
        "data/lancedb",
        "data/core_brain",
        "data/digital_clone_brain",
        "data/memory",
        "data/logs",
        "credentials",
    ]

    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)

    print("✓ Created directory structure")

    # 2. Check for .env file
    if not Path(".env").exists():
        if Path(".env.example").exists():
            import shutil
            shutil.copy(".env.example", ".env")
            print("✓ Created .env from .env.example")
            print()
            print("⚠️  IMPORTANT: Edit .env file with your ANTHROPIC_API_KEY")
            print("   nano .env")
        else:
            print("⚠️  .env.example not found")
    else:
        print("✓ .env file exists")

    # 3. Check dependencies
    print()
    print("Checking dependencies...")
    try:
        import anthropic
        import lancedb
        import yaml
        import aiofiles
        print("✓ All dependencies installed")
    except ImportError as e:
        print(f"⚠️  Missing dependency: {e}")
        print("   Run: pip install -r requirements.txt")

    print()
    print("✅ Setup complete!")
    print()
    print("Next steps:")
    print("1. Edit .env: nano .env")
    print("2. Add your ANTHROPIC_API_KEY")
    print("3. Run agent: python src/main.py")
    print()


if __name__ == "__main__":
    setup()
