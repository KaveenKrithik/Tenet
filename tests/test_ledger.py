"""
test_ledger.py — Stage 6 tests for LedgerStore and anomaly detection.
"""
from __future__ import annotations

import pytest

from tenet.ledger.anomaly import check_anomaly
from tenet.ledger.store import LedgerStore


@pytest.fixture()
def ledger(tmp_path) -> LedgerStore:
    return LedgerStore(str(tmp_path / "test_ledger.sqlite"))


def _insert_rows(ledger: LedgerStore, rows):
    """Helper: insert multiple request rows."""
    for r in rows:
        ledger.log_request(**r)


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

class TestLedgerStore:
    def test_log_and_retrieve(self, ledger):
        rid = ledger.log_request(
            prompt_summary="test prompt",
            stage_reached="cache_hit",
            scope_node_count=3,
            estimated_tokens_naive=2400,
            estimated_tokens_actual=0,
            module_attribution="myapp.auth",
        )
        assert rid >= 1
        rows = ledger.get_recent_requests(limit=10)
        assert len(rows) == 1
        assert rows[0]["stage_reached"] == "cache_hit"

    def test_get_totals_counts_stages(self, ledger):
        _insert_rows(ledger, [
            dict(prompt_summary="p1", stage_reached="cache_hit",    estimated_tokens_naive=1000, estimated_tokens_actual=0,   module_attribution="m"),
            dict(prompt_summary="p2", stage_reached="local_success", estimated_tokens_naive=2000, estimated_tokens_actual=500, module_attribution="m"),
            dict(prompt_summary="p3", stage_reached="escalated",     estimated_tokens_naive=5000, estimated_tokens_actual=4000, module_attribution="m"),
        ])
        totals = ledger.get_totals()
        assert totals.total_requests == 3
        assert totals.cache_hits == 1
        assert totals.local_successes == 1
        assert totals.escalations == 1

    def test_tokens_saved_computation(self, ledger):
        _insert_rows(ledger, [
            dict(prompt_summary="p1", stage_reached="cache_hit",    estimated_tokens_naive=8000, estimated_tokens_actual=0, module_attribution="mod"),
            dict(prompt_summary="p2", stage_reached="local_success", estimated_tokens_naive=4000, estimated_tokens_actual=1000, module_attribution="mod"),
        ])
        totals = ledger.get_totals()
        assert totals.tokens_naive_total == 12000
        assert totals.tokens_actual_total == 1000
        assert totals.tokens_saved == 11000

    def test_cache_hit_rate(self, ledger):
        _insert_rows(ledger, [
            dict(prompt_summary="p1", stage_reached="cache_hit", estimated_tokens_naive=0, estimated_tokens_actual=0, module_attribution="m"),
            dict(prompt_summary="p2", stage_reached="cache_hit", estimated_tokens_naive=0, estimated_tokens_actual=0, module_attribution="m"),
            dict(prompt_summary="p3", stage_reached="escalated", estimated_tokens_naive=0, estimated_tokens_actual=0, module_attribution="m"),
            dict(prompt_summary="p4", stage_reached="escalated", estimated_tokens_naive=0, estimated_tokens_actual=0, module_attribution="m"),
        ])
        totals = ledger.get_totals()
        assert abs(totals.cache_hit_rate - 0.5) < 0.001

    def test_spend_by_module(self, ledger):
        _insert_rows(ledger, [
            dict(prompt_summary="p", stage_reached="escalated", estimated_tokens_naive=0, estimated_tokens_actual=500, module_attribution="auth"),
            dict(prompt_summary="p", stage_reached="escalated", estimated_tokens_naive=0, estimated_tokens_actual=300, module_attribution="auth"),
            dict(prompt_summary="p", stage_reached="escalated", estimated_tokens_naive=0, estimated_tokens_actual=1000, module_attribution="billing"),
        ])
        spend = ledger.get_spend_by_module()
        assert spend.get("auth", 0) == 800
        assert spend.get("billing", 0) == 1000

    def test_totals_empty_ledger(self, ledger):
        totals = ledger.get_totals()
        assert totals.total_requests == 0
        assert totals.tokens_saved == 0
        assert totals.cache_hit_rate == 0.0

    def test_rolling_average(self, ledger):
        for tok in [100, 200, 300, 400, 500]:
            ledger.log_request(
                prompt_summary="p", stage_reached="escalated",
                estimated_tokens_naive=0, estimated_tokens_actual=tok,
                module_attribution="mymod",
            )
        avg = ledger.get_module_rolling_average("mymod", last_n=5)
        assert avg is not None
        assert abs(avg - 300.0) < 0.001

    def test_rolling_average_no_history(self, ledger):
        avg = ledger.get_module_rolling_average("nonexistent_module")
        assert avg is None


# ---------------------------------------------------------------------------
# Anomaly detection tests
# ---------------------------------------------------------------------------

class TestAnomalyDetection:
    def test_normal_request_not_flagged(self, ledger):
        for tok in [100, 150, 120, 130, 110]:
            ledger.log_request(
                prompt_summary="p", stage_reached="escalated",
                estimated_tokens_naive=0, estimated_tokens_actual=tok,
                module_attribution="mymod",
            )
        # 200 is ~1.5x average (~123), well below 3× threshold
        assert not check_anomaly(200, "mymod", ledger, anomaly_multiplier=3.0)

    def test_spike_request_flagged(self, ledger):
        for tok in [100, 100, 100, 100, 100]:
            ledger.log_request(
                prompt_summary="p", stage_reached="escalated",
                estimated_tokens_naive=0, estimated_tokens_actual=tok,
                module_attribution="mymod",
            )
        # 500 = 5× average (100), exceeds 3× threshold
        assert check_anomaly(500, "mymod", ledger, anomaly_multiplier=3.0)

    def test_no_history_not_flagged(self, ledger):
        """No prior history → conservative, don't flag."""
        assert not check_anomaly(99999, "brand_new_module", ledger)

    def test_different_modules_independent(self, ledger):
        """Anomaly detection is per-module, not cross-module."""
        for tok in [1000, 1000, 1000]:
            ledger.log_request(
                prompt_summary="p", stage_reached="escalated",
                estimated_tokens_naive=0, estimated_tokens_actual=tok,
                module_attribution="heavy_module",
            )
        # "light_module" has no history → not flagged even though value is large
        result = check_anomaly(5000, "light_module", ledger)
        assert not result

    def test_anomaly_multiplier_respected(self, ledger):
        """A 2× spike should only be flagged with a multiplier of 1.5, not 3."""
        for tok in [100, 100, 100]:
            ledger.log_request(
                prompt_summary="p", stage_reached="escalated",
                estimated_tokens_naive=0, estimated_tokens_actual=tok,
                module_attribution="mymod",
            )
        assert check_anomaly(250, "mymod", ledger, anomaly_multiplier=2.0)   # 2.5× > 2
        assert not check_anomaly(250, "mymod", ledger, anomaly_multiplier=3.0)  # 2.5× < 3
