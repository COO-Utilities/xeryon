"""Make this directory importable as the `xeryon` package during tests.

The package modules import each other relatively, so the tests need the
parent directory on the path rather than the repository root itself.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
