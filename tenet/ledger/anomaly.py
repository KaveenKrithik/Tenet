"""
ledger/anomaly.py — rolling-average spike detector.

Flags requests whose token count is >N× the rolling average for the same
module, indicating an unexpectedly large context being sent to a backend.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def check_anomaly(
    new_request_tokens: int,
    module: str,
    ledger_store,   # LedgerStore, typed loosely to avoid circular imports
    anomaly_multiplier: float = 3.0,
    last_n: int = 20,
) -> bool:
    """Detect token-count anomalies against a rolling average.

    Args:
        new_request_tokens: Token count for the incoming request.
        module: Module attribution string (e.g., "myapp.auth").
        ledger_store: LedgerStore instance to query history from.
        anomaly_multiplier: Flag if new_request_tokens > avg * multiplier.
        last_n: Number of recent requests to include in the rolling average.

    Returns:
        True if the request is anomalous, False otherwise.
    """
    avg = ledger_store.get_module_rolling_average(module, last_n)

    if avg is None or avg == 0:
        # No history → can't detect anomaly, treat as normal
        logger.debug("anomaly: no history for module=%s, skipping", module)
        return False

    threshold = avg * anomaly_multiplier
    is_anomalous = new_request_tokens > threshold

    if is_anomalous:
        logger.info(
            "anomaly: FLAGGED module=%s tokens=%d > %.1f × avg(%.1f)",
            module, new_request_tokens, anomaly_multiplier, avg,
        )
    else:
        logger.debug(
            "anomaly: OK module=%s tokens=%d, avg=%.1f", module, new_request_tokens, avg
        )

    return is_anomalous
