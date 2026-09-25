"""
fixtures/sample_c.py — standalone helpers, no cross-fixture imports.
"""


def greet(name: str) -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"


def shout(name: str) -> str:
    """Return an uppercase greeting."""
    return greet(name).upper()
