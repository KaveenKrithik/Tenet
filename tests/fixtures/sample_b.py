"""
fixtures/sample_b.py — imports from sample_a, extends BaseProcessor.
"""
from sample_a import add, BaseProcessor


class AdvancedProcessor(BaseProcessor):
    """Extends BaseProcessor with additional logic."""

    def process(self, value: int) -> int:
        return add(value, 10)

    def double_process(self, value: int) -> int:
        return self.process(value) * 2
