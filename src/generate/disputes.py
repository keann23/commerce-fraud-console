"""Chargeback lifecycle. Disputes arrive weeks after the charge, so recent weeks look
artificially clean (the label delay problem). Attack injectors reuse dispute_row()."""
from datetime import datetime, timedelta

import numpy as np

from src.config import WINDOW_END

LAG_MEDIAN_DAYS = 30      # most disputes land 2 to 8 weeks after purchase
LAG_SIGMA = 0.55          # lognormal spread gives the long right tail
LAG_MIN_DAYS, LAG_MAX_DAYS = 2, 120
DAYS_TO_RESOLVE = 21      # simplified: issuer decides ~3 weeks after filing
MERCHANT_WIN_RATE = {
    "canceled_subscription": 0.45,
    "not_as_described": 0.35,
    "duplicate": 0.60,
    "unauthorized": 0.25,
}

# Legit baseline dispute rates, per approved charge.
FORGOTTEN_RENEWAL_RATE = 0.005   # customer forgot to cancel, disputes the renewal (not fraud)
NOT_AS_DESCRIBED_RATE = 0.001
DUPLICATE_RATE = 0.0005


def sample_lag_days(rng: np.random.Generator) -> float:
    lag = rng.lognormal(np.log(LAG_MEDIAN_DAYS), LAG_SIGMA)
    return float(np.clip(lag, LAG_MIN_DAYS, LAG_MAX_DAYS))


def dispute_row(rng, dispute_id: str, txn_id: str, txn_ts: datetime, reason: str) -> dict | None:
    """Build one dispute, or None if it would only be filed after the window ends."""
    filed = txn_ts + timedelta(days=sample_lag_days(rng))
    if filed >= WINDOW_END:
        return None  # it will happen, but we cannot see it yet
    responded = filed + timedelta(days=float(rng.uniform(2, 7)))
    decided = filed + timedelta(days=DAYS_TO_RESOLVE)
    if decided < WINDOW_END:
        status = "closed"
        outcome = "won" if rng.random() < MERCHANT_WIN_RATE[reason] else "lost"
    else:
        status, outcome = "open", "pending"
    return {
        "dispute_id": dispute_id,
        "txn_id": txn_id,
        "filed_ts": filed,
        "reason_category": reason,
        "status": status,
        "responded_ts": responded if responded < WINDOW_END else None,
        "outcome": outcome,
    }


def baseline_disputes(rng, charges: list[tuple[str, datetime, bool]]) -> list[dict]:
    """charges: (txn_id, ts, is_renewal) for approved legit charges."""
    rows = []
    for txn_id, ts, is_renewal in charges:
        draw = rng.random()
        if is_renewal and draw < FORGOTTEN_RENEWAL_RATE:
            reason = "canceled_subscription"
        elif draw < FORGOTTEN_RENEWAL_RATE + NOT_AS_DESCRIBED_RATE:
            reason = "not_as_described"
        elif draw < FORGOTTEN_RENEWAL_RATE + NOT_AS_DESCRIBED_RATE + DUPLICATE_RATE:
            reason = "duplicate"
        else:
            continue
        row = dispute_row(rng, f"DP{len(rows) + 1:06d}", txn_id, ts, reason)
        if row:
            rows.append(row)
    return rows
