"""Account takeover (ATO): a crew with leaked passwords logs into real, aged accounts and monetizes them.

Sequence per victim, all within 24 to 48 hours:
  login from a new device in a new country (sometimes minutes after the owner logged in at home:
  impossible travel) -> password_reset -> email_change -> payment_method_add -> high-value charge
The crew reuses a few devices and IPs across victims (credential stuffing infrastructure).

Legit lookalikes written with every campaign (rule 5):
  - traveler buys a new phone abroad: new device + new country, plausible speed, no account changes
  - forgot password, new job: reset -> email change -> new card, all from the owner's own laptop at home
  - new phone at home: new device in the home country, then a password reset on it
"""
from datetime import timedelta

import numpy as np

from src import config as C
from src.generate.attacks.common import (DAY, END_SEC, CampaignWriter, add_device,
                                         add_genuine_fraud_dispute, add_payment_method, add_txn, random_bin, random_ip, to_ts)
from src.generate.geo import haversine_km

HISTORY_WARMUP_DAYS = 14   # detection ignores logins before this, so attacks start after it
HIGH_VALUE_PURCHASES = [659.88, 479.88, 299.99, 199.99]   # annual All Apps, Stock credit packs, etc.
PLANE_KMH = 700


def inject_ato(con, seed: int, n_victims: int = 10, impossible_travel_rate: float = 0.5,
               monetize_rate: float = 0.8, n_devices: int = 2, start_day: float | None = None,
               with_lookalikes: bool = True) -> str:
    """Write one ATO campaign against n_victims real accounts (plus lookalikes). Returns its campaign_id."""
    rng = np.random.default_rng(seed)
    w = CampaignWriter(con, "ato")
    start = (start_day if start_day is not None else rng.uniform(HISTORY_WARMUP_DAYS + 2, C.WINDOW_DAYS - 10)) * DAY
    crew_country = str(rng.choice(["BR", "IN", "MX", "KR", "SG", "NL"]))
    crew_devices = [add_device(w, start, ("Windows", "Chrome")) for _ in range(n_devices)]
    crew_ips = [random_ip(rng) for _ in range(3)]

    for victim in _pick_accounts(w, rng, n_victims, exclude_country=crew_country, valuable=True):
        t = start + rng.uniform(0, 5 * DAY)
        device, ip = crew_devices[int(rng.integers(0, n_devices))], crew_ips[int(rng.integers(0, 3))]
        lat, lon = _jitter(rng, crew_country)

        for k in range(int(rng.integers(0, 4))):  # failed password guesses first
            _login(w, victim["user_id"], t - (k + 1) * rng.uniform(30, 300), ip, crew_country, lat, lon, device, False)
        if rng.random() < impossible_travel_rate:  # the real owner was at home minutes ago
            _login(w, victim["user_id"], t - rng.uniform(20, 90) * 60, victim["ip"], victim["country"],
                   victim["lat"], victim["lon"], victim["device_id"], True)
        _login(w, victim["user_id"], t, ip, crew_country, lat, lon, device, True)

        t_reset = t + rng.uniform(0.2, 6) * 3600
        t_email = t_reset + rng.uniform(0.1, 3) * 3600
        t_card = t_email + rng.uniform(0.5, 8) * 3600
        _event(w, victim["user_id"], t_reset, "password_reset", device, ip)
        _event(w, victim["user_id"], t_email, "email_change", device, ip)
        pm_id = add_payment_method(w, victim["user_id"], (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}"),
                                   t_card, w.campaign_id, card_country=crew_country)
        _event(w, victim["user_id"], t_card, "payment_method_add", device, ip)
        if rng.random() < monetize_rate:
            t_buy = t_card + rng.uniform(0.5, 12) * 3600
            _event(w, victim["user_id"], t_buy - 120, "plan_change", device, ip)
            txn_id = add_txn(w, victim["user_id"], pm_id, t_buy, float(rng.choice(HIGH_VALUE_PURCHASES)), "charge",
                             "approved", None, ip, device)
            w.truth("txn", txn_id, t_buy)
            add_genuine_fraud_dispute(w, rng, txn_id, t_buy, rate=0.7)  # owner sees the charge, disputes it
        w.truth("user", victim["user_id"], t)
    for device in crew_devices:
        w.truth("device", device, start)

    if with_lookalikes:
        for _ in range(3):
            _traveler_new_phone(w, rng)
            _forgot_password_new_job(w, rng)
            _new_phone_at_home(w, rng)
    return w.flush()


# ---------- helpers ----------
def _jitter(rng, country: str) -> tuple[float, float]:
    c = C.COUNTRIES[country]
    return round(c.lat + float(rng.normal(0, 1)), 4), round(c.lon + float(rng.normal(0, 1)), 4)


def _login(w, user_id, sec, ip, country, lat, lon, device_id, success):
    if 0 <= sec < END_SEC:
        w.add("logins", login_id=w.new_id("logins"), user_id=user_id, ts=to_ts(sec), ip=ip, country=country,
              lat=lat, lon=lon, device_id=device_id, success=success, mfa_used=False)


def _event(w, user_id, sec, event_type, device_id, ip):
    if 0 <= sec < END_SEC:
        w.add("account_events", event_id=w.new_id("account_events"), user_id=user_id, ts=to_ts(sec),
              event_type=event_type, device_id=device_id, ip=ip)


def _pick_accounts(w, rng, n, exclude_country=None, valuable=False) -> list[dict]:
    """Aged, active, untouched accounts. 'Valuable' ones have real usage and never used MFA."""
    con = w.con
    taken = {r["entity_id"] for r in w.rows.get("ground_truth", [])}  # picked earlier, not yet written
    rows = con.execute(f"""
        WITH used AS (SELECT DISTINCT entity_id FROM ground_truth WHERE entity_type = 'user'),
        usage AS (SELECT user_id, sum(minutes) AS minutes FROM usage_events GROUP BY 1),
        home AS (SELECT user_id, median(lat) AS lat, median(lon) AS lon FROM logins GROUP BY 1)
        SELECT u.user_id, u.country, u.signup_ip AS ip, u.signup_device_id AS device_id, h.lat, h.lon
        FROM users u
        JOIN subscriptions s USING (user_id)
        JOIN usage g USING (user_id)
        JOIN home h USING (user_id)
        WHERE u.signup_ts < ? AND s.status = 'active'
          AND u.user_id NOT IN (SELECT entity_id FROM used)
          AND u.country <> coalesce(?, '')
          {"AND g.minutes > 600 AND u.user_id NOT IN (SELECT user_id FROM logins WHERE mfa_used)" if valuable else ""}
        ORDER BY u.user_id""", [C.WINDOW_START, exclude_country]).fetchall()
    rows = [r for r in rows if r[0] not in taken]
    cols = ["user_id", "country", "ip", "device_id", "lat", "lon"]
    picks = rng.choice(len(rows), size=min(n, len(rows)), replace=False)
    return [dict(zip(cols, rows[int(i)])) for i in sorted(picks)]


def _quiet_gap(con, rng, user_id, min_days) -> tuple[float, float] | None:
    """A stretch with no logins for this user, so an injected trip can't create impossible travel."""
    gaps = con.execute("""
        SELECT epoch(ts - ?) AS a, epoch(nxt - ?) AS b FROM (
            SELECT ts, lead(ts) OVER (ORDER BY ts) AS nxt FROM logins WHERE user_id = ?)
        WHERE nxt - ts > to_days(CAST(? AS INTEGER)) AND ts > ? """,
                       [C.WINDOW_START, C.WINDOW_START, user_id, min_days,
                        C.WINDOW_START + timedelta(days=HISTORY_WARMUP_DAYS)]).fetchall()
    if not gaps:
        return None
    a, b = gaps[int(rng.integers(0, len(gaps)))]
    return float(a), float(b)


# ---------- legit lookalikes ----------
def _traveler_new_phone(w, rng):
    for user in _pick_accounts(w, rng, 5):
        gap = _quiet_gap(w.con, rng, user["user_id"], 6)
        if gap is None:
            continue
        dest = str(rng.choice([c for c in C.COUNTRIES if c != user["country"]]))
        lat, lon = _jitter(rng, dest)
        flight = (haversine_km(user["lat"], user["lon"], lat, lon) / PLANE_KMH + 3) * 3600
        arrive, leave = gap[0] + flight, gap[1] - flight
        if leave - arrive < DAY:
            continue
        phone = add_device(w, arrive, ("iOS", "Safari"))
        hotel_ip = random_ip(rng)
        for t in np.sort(rng.uniform(arrive, leave, int(rng.integers(2, 5)))):
            _login(w, user["user_id"], t, hotel_ip, dest, lat, lon, phone, True)
        w.truth("user", user["user_id"], arrive, label="lookalike")
        return


def _forgot_password_new_job(w, rng):
    user = _pick_accounts(w, rng, 1)[0]
    t = rng.uniform(HISTORY_WARMUP_DAYS + 1, C.WINDOW_DAYS - 3) * DAY
    _login(w, user["user_id"], t - 600, user["ip"], user["country"], user["lat"], user["lon"], user["device_id"], False)
    _event(w, user["user_id"], t, "password_reset", user["device_id"], user["ip"])
    _login(w, user["user_id"], t + 300, user["ip"], user["country"], user["lat"], user["lon"], user["device_id"], True)
    _event(w, user["user_id"], t + rng.uniform(1, 24) * 3600, "email_change", user["device_id"], user["ip"])
    t_card = t + rng.uniform(24, 47) * 3600
    add_payment_method(w, user["user_id"], (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}"), t_card,
                       f"{w.campaign_id}-newjob", card_country=user["country"])
    _event(w, user["user_id"], t_card, "payment_method_add", user["device_id"], user["ip"])
    w.truth("user", user["user_id"], t, label="lookalike")


def _new_phone_at_home(w, rng):
    user = _pick_accounts(w, rng, 1)[0]
    t = rng.uniform(HISTORY_WARMUP_DAYS + 1, C.WINDOW_DAYS - 2) * DAY
    phone = add_device(w, t, ("Android", "Chrome"))
    _login(w, user["user_id"], t, user["ip"], user["country"], user["lat"], user["lon"], phone, False)
    _event(w, user["user_id"], t + 120, "password_reset", phone, user["ip"])
    _login(w, user["user_id"], t + 400, user["ip"], user["country"], user["lat"], user["lon"], phone, True)
    w.truth("user", user["user_id"], t, label="lookalike")
