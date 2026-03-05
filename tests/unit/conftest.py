"""Unit test configuration — add DHS source to Python path."""

import sys
from pathlib import Path

# Add apps/dhs to path so we can import modules directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "dhs"))
