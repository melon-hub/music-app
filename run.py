#!/usr/bin/env python3
"""
Quick launcher for Swim Sync.

Usage:
    python run.py
"""

import sys
from pathlib import Path

# Add src to path for development
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from swimsync.app import main

if __name__ == "__main__":
    main()
