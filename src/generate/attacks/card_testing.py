"""Card testing: a fraudster validates a batch of stolen cards with tiny auths in a fast burst,
then uses the few cards that work for real purchases days later ("cash-out").

Legit lookalikes written with every campaign (rule 5):
  - campus workshop: 20 to 40 students on one campus IP start $1 trial auths within ~45 minutes
    (same IP, many distinct cards, tiny amounts, burst) but almost nothing is declined
  - frustrated customer: one person retries their own card 4 to 7 times in a few minutes
    (high decline rate, burst) but it is one card at the full plan price
"""
import numpy as np
from faker import Faker

from src import config as C
from src.generate.attacks.common import (DAY, END_SEC, CampaignWriter, add_device, add_payment_method,
                                         add_genuine_fraud_dispute, add_txn, random_bin, random_ip,
                                         stable_hash, to_ts)

ATTACK_DECLINE_REASONS = ["do_not_honor", "invalid_card", "stolen_card", "incorrect_cvc", "insufficient_funds"]
CARD_PATTERNS = ["same_bin", "sequential_last4", "random"]
CARD_REUSE_RATE = 0.10   # testers occasionally retry a card
CASHOUT_RATE = 0.5       # share of validated cards later used for a real purchase


def inject_card_testing(con, seed: int, attempts: int = 250, duration_minutes: int = 15, n_ips: int = 1,
                        n_devices: int = 2, decline_rate: float = 0.8, card_pattern: str = "same_bin",
                        start_day: float | None = None, with_lookalikes: bool = True) -> str:
    """Write one card testing campaign (plus lookalikes) into the warehouse. Returns its campaign_id."""
    rng = np.random.default_rng(seed)
    w = CampaignWriter(con, "card_testing")
    start = (start_day if start_day is not None else rng.uniform(1, C.WINDOW_DAYS - 7)) * DAY

    ips = [random_ip(rng) for _ in range(n_ips)]
    devices = [add_device(w, start, ("Linux", "Chrome")) for _ in range(n_devices)]
    accounts = [_fraud_account(w, rng, start, ips[0], devices[0]) for _ in range(int(rng.integers(1, 4)))]
    cards = _stolen_cards(rng, attempts, card_pattern)

    pm_by_card: dict[tuple, str] = {}
    approved_cards: list[tuple[str, str]] = []   # (account, pm_id)
    times = np.sort(start + rng.uniform(0, duration_minutes * 60, attempts))
    for i, t in enumerate(times):
        account = accounts[i % len(accounts)]
        card = cards[i]
        key = (account, card)
        if key not in pm_by_card:
            pm_by_card[key] = add_payment_method(w, account, card, t, w.campaign_id)
        declined = rng.random() < decline_rate
        add_txn(w, account, pm_by_card[key], t, round(float(rng.uniform(0.5, 2.0)), 2), "auth",
             "declined" if declined else "approved",
             str(rng.choice(ATTACK_DECLINE_REASONS)) if declined else None,
             ips[int(rng.integers(0, n_ips))], devices[int(rng.integers(0, n_devices))])
        if not declined and (account, pm_by_card[key]) not in approved_cards:
            approved_cards.append((account, pm_by_card[key]))

    burst_end = float(times[-1])
    cashout_ip = random_ip(rng)  # residential proxy: a different IP from the burst
    for account, pm_id in approved_cards:
        cashout_at = burst_end + rng.uniform(1, 5) * DAY
        if rng.random() < CASHOUT_RATE and cashout_at < END_SEC:
            txn_id = add_txn(w, account, pm_id, cashout_at, C.PLAN_PRICES["all_apps"], "charge", "approved",
                          None, cashout_ip, devices[0])
            w.truth("txn", txn_id, cashout_at)
            add_genuine_fraud_dispute(w, rng, txn_id, cashout_at, rate=0.6)  # real cardholder notices

    for ip in ips:
        w.truth("ip", ip, start)
    for device_id in devices:
        w.truth("device", device_id, start)
    for user_id in accounts:
        w.truth("user", user_id, start)

    if with_lookalikes:
        fake = Faker()
        fake.seed_instance(seed)
        _campus_workshop(w, rng, fake, start)
        _frustrated_customer(w, rng, start)
    return w.flush()


# ---------- attack pieces ----------
def _stolen_cards(rng, attempts: int, pattern: str) -> list[tuple[str, str]]:
    """One (bin, last4) per attempt. Stolen card lists often share a BIN or run in sequence."""
    main_bin = random_bin(rng)
    next_last4 = int(rng.integers(0, 9_000))
    cards: list[tuple[str, str]] = []
    for _ in range(attempts):
        if cards and rng.random() < CARD_REUSE_RATE:
            cards.append(cards[-1])
            continue
        if pattern == "same_bin":
            bin_ = main_bin if rng.random() < 0.8 else random_bin(rng)
            last4 = int(rng.integers(0, 10_000))
        elif pattern == "sequential_last4":
            bin_, last4 = main_bin, next_last4 % 10_000
            next_last4 += 1
        else:
            bin_, last4 = random_bin(rng), int(rng.integers(0, 10_000))
        cards.append((bin_, f"{last4:04d}"))
    return cards


def _fraud_account(w, rng, start: float, ip: str, device_id: str) -> str:
    user_id = w.new_id("users")
    signup = start - rng.uniform(600, 7200)
    domain = str(rng.choice(["mailinator.com", "yopmail.com", "gmail.com", "outlook.com"]))
    country = str(rng.choice(list(C.COUNTRIES)))
    w.add("users", user_id=user_id, email=f"{stable_hash(user_id, w.campaign_id)[:10]}@{domain}",
          signup_ts=to_ts(signup), country=country, signup_ip=ip,
          signup_device_id=device_id, account_age_days=int((END_SEC - signup) // DAY))
    w.add("logins", login_id=w.new_id("logins"), user_id=user_id, ts=to_ts(signup), ip=ip, country=country,
          lat=C.COUNTRIES[country].lat, lon=C.COUNTRIES[country].lon, device_id=device_id, success=True,
          mfa_used=False)
    return user_id


# ---------- legit lookalikes ----------
def _campus_workshop(w, rng, fake, attack_start: float):
    """A class signs up for student trials together on the campus network."""
    begin = (attack_start + rng.uniform(1, 3) * DAY) % (END_SEC - 9 * DAY)
    campus_ip = random_ip(rng)
    country = str(rng.choice(["US", "GB", "CA", "AU"]))
    edu = str(rng.choice(C.EDU_DOMAINS))
    c = C.COUNTRIES[country]
    w.truth("ip", campus_ip, begin, label="lookalike")
    for k in range(int(rng.integers(20, 41))):
        t = begin + rng.uniform(0, 45 * 60)
        user_id = w.new_id("users")
        device_id = add_device(w, t, ("macOS", "Chrome") if rng.random() < 0.6 else ("Windows", "Edge"))
        first, last = fake.first_name().lower(), fake.last_name().lower()
        w.add("users", user_id=user_id, email=f"{first}.{last}.{user_id.lower()}@{edu}", signup_ts=to_ts(t),
              country=country, signup_ip=campus_ip, signup_device_id=device_id,
              account_age_days=int((END_SEC - t) // DAY))
        w.add("logins", login_id=w.new_id("logins"), user_id=user_id, ts=to_ts(t), ip=campus_ip,
              country=country, lat=c.lat, lon=c.lon, device_id=device_id, success=True, mfa_used=False)
        pm_id = add_payment_method(w, user_id, (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}"), t,
                                user_id, card_country=country)
        declined = rng.random() < 0.03
        add_txn(w, user_id, pm_id, t + 30, 1.00, "auth", "declined" if declined else "approved",
             "insufficient_funds" if declined else None, campus_ip, device_id)
        trial_end = t + C.TRIAL_DAYS * DAY
        converted = bool(rng.random() < 0.55)
        if converted:
            add_txn(w, user_id, pm_id, trial_end, C.PLAN_PRICES["student"] * c.price_multiplier, "charge",
                 "approved", None, campus_ip, device_id)
        w.add("subscriptions", sub_id=w.new_id("subscriptions"), user_id=user_id, plan="student",
              price_tier_country=country, is_trial=True, trial_start_ts=to_ts(t), trial_end_ts=to_ts(trial_end),
              converted=converted, status="active" if converted else "canceled",
              canceled_ts=None if converted else to_ts(t + rng.uniform(1, 6.9) * DAY))
        w.truth("device", device_id, t, label="lookalike")


def _frustrated_customer(w, rng, attack_start: float):
    """A real subscriber whose card keeps failing retries it several times in a few minutes."""
    customers = w.con.execute("""
        SELECT u.user_id, u.signup_ip, u.signup_device_id, p.pm_id, s.plan, s.price_tier_country
        FROM users u JOIN payment_methods p USING (user_id) JOIN subscriptions s USING (user_id)
        WHERE u.signup_ts < ?
          AND u.user_id NOT IN (SELECT entity_id FROM ground_truth WHERE entity_type = 'user')
        ORDER BY u.user_id, p.pm_id""", [C.WINDOW_START]).fetchall()
    user_id, ip, device_id, pm_id, plan, country = customers[int(rng.integers(0, len(customers)))]
    amount = C.PLAN_PRICES[plan] * C.COUNTRIES[country].price_multiplier
    t = (attack_start + rng.uniform(1, 5) * DAY) % (END_SEC - DAY)
    n_tries = int(rng.integers(4, 8))
    for k in range(n_tries):
        last = k == n_tries - 1
        ok = last and rng.random() < 0.5
        add_txn(w, user_id, pm_id, t + k * rng.uniform(40, 120), amount, "charge",
             "approved" if ok else "declined", None if ok else "insufficient_funds", ip, device_id)
    w.truth("ip", ip, t, label="lookalike")
    w.truth("device", device_id, t, label="lookalike")
