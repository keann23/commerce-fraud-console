"""Trial abuse: one person creates many trial accounts to use the product for free, cancelling
each one before it converts to paid.

Tricks modeled: Gmail dot variants, plus tags, disposable domains, brand-new inboxes, a shared
device or two, and one to three virtual cards reused across accounts. The student variant signs up
for the discounted Student plan with non-.edu or plus-tagged .edu addresses.

Legit lookalikes written with every campaign (rule 5):
  - family: 2 to 4 people start trials on one laptop with the family card; at least one converts
  - library kiosk: 6 to 10 unrelated people trial on a shared public computer; about half convert
  - returning student: trials, cancels, comes back weeks later with a plus-tagged email and converts
  - work + personal: kean@gmail.com and kean+work@gmail.com, both paid
"""
from datetime import timedelta

import numpy as np
from faker import Faker

from src import config as C
from src.generate.attacks.common import (DAY, END_SEC, CampaignWriter, add_device, add_payment_method,
                                         add_txn, random_bin, random_ip, to_ts)

DISPOSABLE = ["mailinator.com", "yopmail.com", "guerrillamail.com", "10minutemail.com", "trashmail.com"]
EMAIL_TRICKS = (["dots", "plus", "dots_plus", "disposable", "fresh_inbox"], [0.30, 0.25, 0.15, 0.15, 0.15])


def inject_trial_abuse(con, seed: int, n_accounts: int = 20, duration_days: int = 30, n_devices: int = 2,
                       n_virtual_cards: int = 2, fresh_card_rate: float = 0.15, student_variant: bool = False,
                       start_day: float | None = None, with_lookalikes: bool = True) -> str:
    """Write one trial abuse ring (plus lookalikes). Returns its campaign_id."""
    rng = np.random.default_rng(seed)
    fake = Faker()
    fake.seed_instance(seed)
    w = CampaignWriter(con, "trial_abuse")
    latest_start = C.WINDOW_DAYS - duration_days - C.TRIAL_DAYS - 1
    start = (start_day if start_day is not None else rng.uniform(1, max(latest_start, 2))) * DAY
    country = str(rng.choice(list(C.COUNTRIES)))

    base_local = f"{_clean(fake.first_name())}{_clean(fake.last_name())}{int(rng.integers(100, 999))}"
    edu = str(rng.choice(C.EDU_DOMAINS))
    devices = [add_device(w, start, ("Windows", "Chrome")) for _ in range(n_devices)]
    home_ips = [random_ip(rng) for _ in range(2)]
    cards = [(random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}") for _ in range(n_virtual_cards)]
    used_emails: set[str] = set()

    for k in range(n_accounts):
        t = start + rng.uniform(0, duration_days * DAY)
        email = _abuser_email(rng, base_local, edu if student_variant else "gmail.com", used_emails)
        device = devices[int(rng.integers(0, n_devices))] if rng.random() < 0.85 else add_device(
            w, t, ("Windows", "Chrome"))
        ip = home_ips[int(rng.integers(0, 2))] if rng.random() < 0.7 else random_ip(rng)  # sometimes a VPN
        if rng.random() < fresh_card_rate:
            card = (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}")
        else:
            card = cards[int(rng.integers(0, n_virtual_cards))]
        user_id = add_trial_account(w, rng, t, email, country, device, ip, card, card_salt=w.campaign_id,
                                    is_virtual=True, converted=False, plan="student" if student_variant
                                    else str(rng.choice(["all_apps", "single_app", "photography"])),
                                    cancel_after_days=rng.uniform(4.5, 6.9), engagement=0.9)
        w.truth("user", user_id, t)

    if with_lookalikes:
        _family(w, rng, fake, start)
        _library_kiosk(w, rng, fake, start)
        _returning_student(w, rng, fake, start)
        _work_and_personal(w, rng, fake, start)
    return w.flush()


# ---------- shared account builder ----------
def add_trial_account(w, rng, t, email, country, device_id, ip, card, card_salt, is_virtual, converted,
                      plan, cancel_after_days=None, engagement=0.6) -> str:
    """A complete trial customer: user, login, card, $1 auth, subscription, charges, usage, events."""
    c = C.COUNTRIES[country]
    user_id = w.new_id("users")
    w.add("users", user_id=user_id, email=email, signup_ts=to_ts(t), country=country, signup_ip=ip,
          signup_device_id=device_id, account_age_days=int((END_SEC - t) // DAY))
    pm_id = add_payment_method(w, user_id, card, t + 60, card_salt, card_country=country, is_virtual=is_virtual)
    _event(w, user_id, t + 60, "payment_method_add", device_id, ip)
    add_txn(w, user_id, pm_id, t + 90, 1.00, "auth", "approved", None, ip, device_id)

    trial_end = t + C.TRIAL_DAYS * DAY
    canceled = None
    if converted is False:
        canceled = t + (cancel_after_days if cancel_after_days is not None else rng.uniform(1, 6.9)) * DAY
        if canceled >= END_SEC:
            canceled, converted = None, None   # still mid-trial when the window ends
        else:
            _event(w, user_id, canceled, "cancel", device_id, ip)
    elif trial_end >= END_SEC:
        converted = None
    w.add("subscriptions", sub_id=w.new_id("subscriptions"), user_id=user_id, plan=plan, price_tier_country=country,
          is_trial=True, trial_start_ts=to_ts(t), trial_end_ts=to_ts(trial_end), converted=converted,
          status={True: "active", False: "canceled", None: "trialing"}[converted],
          canceled_ts=to_ts(canceled) if canceled is not None else None)

    if converted:
        charge_at = trial_end
        while charge_at < END_SEC:
            add_txn(w, user_id, pm_id, charge_at, C.PLAN_PRICES[plan] * c.price_multiplier, "charge", "approved",
                    None, ip, device_id)
            charge_at += C.BILLING_CYCLE_DAYS * DAY

    use_until = canceled if canceled is not None else END_SEC
    login_times = [t] + list(np.sort(rng.uniform(t, use_until, int(rng.integers(2, 6)))))
    for lt in login_times:
        w.add("logins", login_id=w.new_id("logins"), user_id=user_id, ts=to_ts(lt), ip=ip, country=country,
              lat=round(c.lat + 0.5, 4), lon=round(c.lon + 0.5, 4), device_id=device_id, success=True,
              mfa_used=False)
    first_day, last_day = int(t // DAY), int(min(use_until, END_SEC - 1) // DAY)
    for d in range(first_day, last_day + 1):
        if rng.random() < engagement:
            sessions = 1 + int(rng.poisson(1.5))
            w.add("usage_events", user_id=user_id, date=(C.WINDOW_START + timedelta(days=d)).date(),
                  app=str(rng.choice(C.APPS)), sessions=sessions, minutes=int(sessions * rng.gamma(2.0, 20.0)) + 1)
    return user_id


def _event(w, user_id, sec, event_type, device_id, ip):
    if sec < END_SEC:
        w.add("account_events", event_id=w.new_id("account_events"), user_id=user_id, ts=to_ts(sec),
              event_type=event_type, device_id=device_id, ip=ip)


def _clean(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalpha())


def _abuser_email(rng, base: str, domain: str, used: set) -> str:
    while True:
        trick = rng.choice(EMAIL_TRICKS[0], p=EMAIL_TRICKS[1])
        local = base
        if trick in ("dots", "dots_plus") and domain == "gmail.com":
            positions = sorted(rng.choice(range(1, len(base)), size=int(rng.integers(1, 4)), replace=False))
            local = "".join(ch + ("." if i + 1 in positions else "") for i, ch in enumerate(base))
        if trick in ("plus", "dots_plus") or (trick == "dots" and domain != "gmail.com"):
            local = f"{local}+{int(rng.integers(1, 999))}"
        if trick == "disposable":
            email = f"{base[:5]}{int(rng.integers(1000, 99999))}@{rng.choice(DISPOSABLE)}"
        elif trick == "fresh_inbox":
            email = f"{base[::-1][:6]}{int(rng.integers(1000, 99999))}@gmail.com"
        else:
            email = f"{local}@{domain}"
        if email not in used:
            used.add(email)
            return email


# ---------- legit lookalikes ----------
def _lookalike_time(rng, attack_start, span_days=0.0):
    return (attack_start + rng.uniform(2, 20) * DAY) % (END_SEC - (span_days + C.TRIAL_DAYS + 2) * DAY)


def _person_email(fake, rng, user_hint):
    return f"{_clean(fake.first_name())}.{_clean(fake.last_name())}{int(rng.integers(10, 99))}{user_hint}@" + \
        str(rng.choice(["gmail.com", "outlook.com", "icloud.com", "yahoo.com"]))


def _family(w, rng, fake, attack_start):
    t0 = _lookalike_time(rng, attack_start)
    country = str(rng.choice(list(C.COUNTRIES)))
    laptop = add_device(w, t0, ("macOS", "Safari"))
    ip = random_ip(rng)
    family_card = (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}")
    size = int(rng.integers(2, 5))
    converts = set(rng.choice(size, size=int(rng.integers(1, size + 1)), replace=False).tolist())
    for k in range(size):
        t = t0 + rng.uniform(0, 3 * DAY)
        user_id = add_trial_account(w, rng, t, _person_email(fake, rng, k), country, laptop, ip, family_card,
                                    card_salt=f"{w.campaign_id}-family", is_virtual=False,
                                    converted=k in converts, plan=str(rng.choice(["photography", "single_app"])))
        w.truth("user", user_id, t, label="lookalike")


def _library_kiosk(w, rng, fake, attack_start):
    t0 = _lookalike_time(rng, attack_start, span_days=14)
    country = str(rng.choice(list(C.COUNTRIES)))
    kiosk = add_device(w, t0, ("Windows", "Edge"))
    library_ip = random_ip(rng)
    n = int(rng.integers(6, 11))
    converts = set(rng.choice(n, size=max(2, int(round(n * 0.55))), replace=False).tolist())
    for k in range(n):
        t = t0 + rng.uniform(0, 14 * DAY)
        card = (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}")
        user_id = add_trial_account(w, rng, t, _person_email(fake, rng, k), country, kiosk, library_ip, card,
                                    card_salt=f"{w.campaign_id}-kiosk-{k}", is_virtual=False,
                                    converted=k in converts, plan=str(rng.choice(["single_app", "all_apps"])))
        w.truth("user", user_id, t, label="lookalike")


def _returning_student(w, rng, fake, attack_start):
    t1 = _lookalike_time(rng, attack_start, span_days=45)
    t2 = t1 + rng.uniform(30, 45) * DAY
    country = str(rng.choice(["US", "GB", "CA"]))
    laptop = add_device(w, t1, ("macOS", "Chrome"))
    ip = random_ip(rng)
    local = f"{_clean(fake.first_name())}.{_clean(fake.last_name())}{int(rng.integers(10, 99))}"
    edu = str(rng.choice(C.EDU_DOMAINS))
    card = (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}")
    for t, email, converted in [(t1, f"{local}@{edu}", False), (t2, f"{local}+adobe@{edu}", True)]:
        user_id = add_trial_account(w, rng, t, email, country, laptop, ip, card,
                                    card_salt=f"{w.campaign_id}-student", is_virtual=False, converted=converted,
                                    plan="student")
        w.truth("user", user_id, t, label="lookalike")


def _work_and_personal(w, rng, fake, attack_start):
    t1 = _lookalike_time(rng, attack_start, span_days=10)
    country = str(rng.choice(list(C.COUNTRIES)))
    local = f"{_clean(fake.first_name())}{_clean(fake.last_name())}{int(rng.integers(10, 99))}"
    laptop = add_device(w, t1, ("macOS", "Safari"))
    ip = random_ip(rng)
    for k, email in enumerate([f"{local}@gmail.com", f"{local}+work@gmail.com"]):
        t = t1 + k * rng.uniform(2, 10) * DAY
        card = (random_bin(rng), f"{int(rng.integers(0, 10_000)):04d}")  # personal card, then company card
        user_id = add_trial_account(w, rng, t, email, country, laptop, ip, card,
                                    card_salt=f"{w.campaign_id}-work-{k}", is_virtual=False, converted=True,
                                    plan=str(rng.choice(["all_apps", "single_app"])))
        w.truth("user", user_id, t, label="lookalike")
