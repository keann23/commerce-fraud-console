"""Friendly fraud: a real, long-standing customer makes a purchase, keeps using the product, then
tells their bank the charge was "unauthorized" to get the money back.

Two variants: disputing an ordinary renewal, or disputing a big one-off purchase (an annual plan).
Either way the purchase came from the customer's own device and home IP, and usage continues after it.

Legit lookalike written with every campaign (rule 5): genuine third-party fraud. A stranger opens an
account and buys with a stolen card, and the real cardholder files an honest "unauthorized" dispute.
(Card testing cash-outs and ATO charges also produce honest unauthorized disputes in their injectors.)
"""
from datetime import timedelta

import numpy as np

from src import config as C
from src.generate.attacks.common import (DAY, END_SEC, CampaignWriter, add_device, add_dispute,
                                         add_payment_method, add_txn, random_bin, random_ip, to_ts)

ANNUAL_PLAN_PRICES = [659.88, 263.88, 239.88]


def inject_friendly_fraud(con, seed: int, n_customers: int = 15, big_purchase_rate: float = 0.5,
                          with_lookalikes: bool = True) -> str:
    """Write one batch of friendly fraud disputes (plus genuine-fraud lookalikes). Returns its campaign_id."""
    rng = np.random.default_rng(seed)
    w = CampaignWriter(con, "friendly_fraud")
    for customer in _loyal_customers(w, rng, n_customers):
        if rng.random() < big_purchase_rate:
            t = rng.uniform(20, C.WINDOW_DAYS - 25) * DAY
            txn_id = add_txn(w, customer["user_id"], customer["pm_id"], t, float(rng.choice(ANNUAL_PLAN_PRICES)),
                             "charge", "approved", None, customer["ip"], customer["device_id"])
        else:
            txn_id, t = customer["renewal_txn"], customer["renewal_sec"]
        dispute_id = add_dispute(w, rng, txn_id, t, "unauthorized", force_visible=True)
        if dispute_id is None:
            continue
        _keep_using(w, rng, customer, t)
        w.truth("dispute", dispute_id, t)
        w.truth("user", customer["user_id"], t)

    if with_lookalikes:
        for _ in range(max(2, n_customers // 5)):
            _stolen_card_purchase(w, rng)
    return w.flush()


def _loyal_customers(w, rng, n) -> list[dict]:
    taken = {r["entity_id"] for r in w.rows.get("ground_truth", [])}
    rows = w.con.execute("""
        WITH renewals AS (
            SELECT user_id, txn_id, epoch(ts - ?) AS sec, pm_id,
                   row_number() OVER (PARTITION BY user_id ORDER BY ts DESC) AS rn
            FROM transactions
            WHERE txn_type = 'charge' AND result = 'approved' AND ts < ? - INTERVAL 20 DAY AND ts > ? + INTERVAL 10 DAY
        )
        , home AS (SELECT user_id, median(lat) AS lat, median(lon) AS lon FROM logins GROUP BY 1)
        SELECT u.user_id, u.signup_ip, u.signup_device_id, r.pm_id, r.txn_id, r.sec, u.country, h.lat, h.lon
        FROM users u
        JOIN renewals r USING (user_id)
        JOIN home h USING (user_id)
        JOIN subscriptions s USING (user_id)
        WHERE r.rn = 1 AND u.account_age_days > 365 AND s.status = 'active'
          AND u.user_id NOT IN (SELECT entity_id FROM ground_truth WHERE entity_type = 'user')
          AND u.user_id NOT IN (SELECT t.user_id FROM disputes d JOIN transactions t USING (txn_id))
        ORDER BY u.user_id""", [C.WINDOW_START, C.WINDOW_END, C.WINDOW_START]).fetchall()
    rows = [r for r in rows if r[0] not in taken]
    picks = sorted(rng.choice(len(rows), size=min(n, len(rows)), replace=False))
    return [dict(user_id=r[0], ip=r[1], device_id=r[2], pm_id=r[3], renewal_txn=r[4], renewal_sec=float(r[5]),
                 country=r[6], lat=r[7], lon=r[8])
            for r in (rows[int(i)] for i in picks)]


def _keep_using(w, rng, customer, purchase_sec):
    """Heavy usage and logins from the same device after the purchase: the evidence they will deny."""
    first_day = int(purchase_sec // DAY) + 1
    for d in range(first_day, min(first_day + 21, C.WINDOW_DAYS)):
        if rng.random() < 0.8:
            sessions = 2 + int(rng.poisson(2))
            w.add("usage_events", user_id=customer["user_id"], date=(C.WINDOW_START + timedelta(days=d)).date(),
                  app=str(rng.choice(["Photoshop", "Premiere", "Illustrator"])), sessions=sessions,
                  minutes=int(sessions * rng.gamma(2.0, 25.0)) + 5)
    for k in range(int(rng.integers(2, 6))):
        t = purchase_sec + rng.uniform(0.5, 20) * DAY
        if t < END_SEC:
            w.add("logins", login_id=w.new_id("logins"), user_id=customer["user_id"], ts=to_ts(t),
                  ip=customer["ip"], country=customer["country"], lat=customer["lat"], lon=customer["lon"],
                  device_id=customer["device_id"],
                  success=True, mfa_used=False)


def _stolen_card_purchase(w, rng):
    """Honest 'unauthorized' dispute: a stranger used someone else's card on a fresh account."""
    t = rng.uniform(10, C.WINDOW_DAYS - 25) * DAY
    country = str(rng.choice(list(C.COUNTRIES)))
    device = add_device(w, t, ("Windows", "Chrome"))
    ip = random_ip(rng)
    user_id = w.new_id("users")
    w.add("users", user_id=user_id, email=f"buyer{user_id.lower()}@outlook.com", signup_ts=to_ts(t - 1800),
          country=country, signup_ip=ip, signup_device_id=device, account_age_days=int((END_SEC - t) // DAY))
    pm_id = add_payment_method(w, user_id, (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}"), t - 600,
                               f"{w.campaign_id}-stolen", card_country=str(rng.choice(["US", "GB", "DE"])))
    txn_id = add_txn(w, user_id, pm_id, t, float(rng.choice(ANNUAL_PLAN_PRICES)), "charge", "approved", None,
                     ip, device)
    dispute_id = add_dispute(w, rng, txn_id, t, "unauthorized", force_visible=True)
    if dispute_id:
        w.truth("dispute", dispute_id, t, label="lookalike")
