"""
conftest.py — shared pytest fixtures and path setup.
"""
import sys
from pathlib import Path

# Ensure the project root is importable when running tests from any directory
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
