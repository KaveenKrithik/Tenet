"""
fixtures/sample_a.py — base module with utility functions used by sample_b and sample_c.
"""


def add(x: int, y: int) -> int:
    """Return the sum of two integers."""
    return x + y


def multiply(x: int, y: int) -> int:
    """Return the product of two integers."""
    return x * y


def compute(x: int, y: int) -> int:
    """Compute a combined result using add and multiply."""
    s = add(x, y)
    p = multiply(x, y)
    return s + p


class BaseProcessor:
    """A simple base class for processing."""

    def process(self, value: int) -> int:
        return compute(value, value)
