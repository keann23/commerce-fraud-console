"""Legitimate customers of a simulated Adobe-style subscription business.

Besides normal behaviour, this module deliberately creates the legit noise from the PRD,
because those are the customers a careless rule would block:
  - households sharing one device, home IP and sometimes one card
  - travelers logging in from another country at plausible speeds
  - students with plus-addressed emails, and natural Gmail dot collisions
  - a few legit virtual/prepaid cards
  - password reset followed by an email change from a known device
  - normal declines (insufficient funds, expired card) with retries
  - customers who forget a renewal and dispute it as canceled_subscription
"""
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from src import config as C
from src.generate import disputes
from src.generate.attacks.common import DAY, END_SEC, random_ip, stable_hash, to_ts
from src.generate.geo import haversine_km

HOUSEHOLD_SHARE = 0.04        # users living in multi-person households
HOUSEHOLD_CARD_SHARE = 0.40   # households where members pay with the same physical card
TRAVELER_SHARE = 0.06
STUDENT_SHARE = 0.08
FREE_USER_SHARE = 0.15
PLUS_TAG_SHARE = 0.03         # non-students who use plus tags for filtering mail
VIRTUAL_CARD_SHARE = 0.04
MFA_SHARE = 0.25
DECLINE_RATE = 0.05
RETRY_SUCCESS = 0.75
REFUND_RATE = 0.01
TRAVEL_SPEED_KMH = 750        # planes, with airport time added on top

OS_BROWSERS = [("Windows", "Chrome"), ("Windows", "Edge"), ("macOS", "Safari"), ("macOS", "Chrome"),
               ("iOS", "Safari"), ("Android", "Chrome"), ("iPadOS", "Safari")]
DECLINE_REASONS = (["insufficient_funds", "expired_card", "do_not_honor"], [0.5, 0.25, 0.25])
SINGLE_APP_CHOICES = ["Photoshop", "Illustrator", "Premiere", "Acrobat"]


class BaselineWorld:
    def __init__(self, seed: int = C.SEED, n_users: int = C.N_USERS):
        self.seed = seed
        self.n = n_users
        self.rng = np.random.default_rng(seed)
        self.fake = Faker()
        self.fake.seed_instance(seed)
        self.rows = {name: [] for name in [
            "users", "devices", "logins", "account_events", "payment_methods",
            "subscriptions", "transactions", "usage_events"]}
        self.approved_charges: list[tuple[str, datetime, bool]] = []

    # ---------- identity ----------
    def make_profiles(self):
        rng, n = self.rng, self.n
        codes = list(C.COUNTRIES)
        weights = np.array([C.COUNTRIES[c].weight for c in codes])
        self.country = rng.choice(codes, size=n, p=weights / weights.sum()).astype(object)
        self.preexisting = rng.random(n) < 0.70
        self.signup_sec = np.where(self.preexisting,
                                   -rng.uniform(1, 1500, n) * DAY,
                                   rng.uniform(0, (C.WINDOW_DAYS - 1) * DAY, n))
        self.home_lat = np.array([C.COUNTRIES[c].lat for c in self.country]) + rng.normal(0, 1.5, n)
        self.home_lon = np.array([C.COUNTRIES[c].lon for c in self.country]) + rng.normal(0, 1.5, n)
        self.is_student = rng.random(n) < STUDENT_SHARE
        self.has_sub = self.is_student | (rng.random(n) >= FREE_USER_SHARE)
        self.engagement = rng.beta(2, 3, n)
        self.mfa = rng.random(n) < MFA_SHARE
        self.home_ip = [random_ip(rng) for _ in range(n)]
        self._make_households()

    def _make_households(self):
        rng = self.rng
        members = rng.choice(self.n, size=int(self.n * HOUSEHOLD_SHARE), replace=False)
        self.household_head = np.full(self.n, -1)
        i = 0
        while i < len(members) - 1:
            size = int(rng.integers(2, 5))
            group = members[i:i + size]
            head = group[0]
            for m in group:
                self.household_head[m] = head
                self.country[m] = self.country[head]
                self.home_lat[m], self.home_lon[m] = self.home_lat[head], self.home_lon[head]
                self.home_ip[m] = self.home_ip[head]
            i += size

    def _email(self, is_student: bool, seen: set) -> str:
        rng, fake = self.rng, self.fake
        first = re.sub(r"[^a-z]", "", fake.first_name().lower()) or "user"
        last = re.sub(r"[^a-z]", "", fake.last_name().lower()) or "name"
        local = [f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}",
                 f"{first}.{last}{int(rng.integers(1, 99))}"][int(rng.integers(0, 4))]
        if is_student:
            if rng.random() < 0.65:
                domain = C.EDU_DOMAINS[int(rng.integers(0, len(C.EDU_DOMAINS)))]
            else:  # legit student who files school mail with a plus tag
                domain, local = "gmail.com", f"{local}+{rng.choice(['school', 'uni', 'adobe'])}"
        else:
            domains = list(C.EMAIL_DOMAINS)
            domain = rng.choice(domains, p=np.array(list(C.EMAIL_DOMAINS.values())))
            if rng.random() < PLUS_TAG_SHARE:
                local = f"{local}+{rng.choice(['shopping', 'adobe', 'subs'])}"
        # Two real people can't own the same inbox, so dedupe on the inbox, not the raw string
        # (john.smith@gmail.com and johnsmith@gmail.com are one Gmail account).
        base, _, tag = local.partition("+")
        suffix = f"+{tag}" if tag else ""
        candidate, k = base, 2
        while self._inbox(candidate, domain) in seen:
            candidate, k = f"{base}{k}", k + 1
        seen.add(self._inbox(candidate, domain))
        return f"{candidate}{suffix}@{domain}"

    @staticmethod
    def _inbox(base_local: str, domain: str) -> str:
        return (base_local.replace(".", "") if domain == "gmail.com" else base_local) + "@" + domain

    def make_users_and_devices(self):
        rng = self.rng
        self.devices = []          # per user: list of (device_id, first_seen_sec)
        seen_emails: set = set()
        device_counter = 0
        for u in range(self.n):
            k = min(1 + int(rng.poisson(0.6)), 3)
            own = []
            for j in range(k):
                device_counter += 1
                device_id = f"D{device_counter:07d}"
                first_seen = self.signup_sec[u] if j == 0 else rng.uniform(self.signup_sec[u], END_SEC - DAY)
                os_, browser = OS_BROWSERS[int(rng.integers(0, len(OS_BROWSERS)))]
                self.rows["devices"].append((device_id, stable_hash(self.seed, device_id), os_, browser,
                                             to_ts(first_seen)))
                own.append((device_id, first_seen))
            self.devices.append(own)
        # Household members also use the head's primary device (the family laptop).
        self.signup_device = [d[0][0] for d in self.devices]
        for u in range(self.n):
            head = self.household_head[u]
            if head >= 0 and head != u:
                shared_id = self.devices[head][0][0]
                self.devices[u].append((shared_id, max(self.signup_sec[u], self.signup_sec[head])))
                if rng.random() < 0.5:
                    self.signup_device[u] = shared_id
        for u in range(self.n):
            age_days = int((END_SEC - self.signup_sec[u]) // DAY)
            self.rows["users"].append((f"U{u + 1:06d}", self._email(self.is_student[u], seen_emails),
                                       to_ts(self.signup_sec[u]), self.country[u], self.home_ip[u],
                                       self.signup_device[u], age_days))

    # ---------- logins ----------
    def _pick_devices(self, u: int, times: np.ndarray) -> list[str]:
        devs = self.devices[u]
        out = []
        for t in times:
            usable = [d for d, first_seen in devs if first_seen <= t] or [devs[0][0]]
            primary_bias = self.rng.random() < 0.7
            out.append(usable[0] if primary_bias else usable[int(self.rng.integers(0, len(usable)))])
        return out

    def make_logins(self):
        rng = self.rng
        codes = list(C.COUNTRIES)
        login_counter = 0
        for u in range(self.n):
            start = max(self.signup_sec[u], 0.0)
            active_days = (END_SEC - start) / DAY
            rate = (0.1 + 0.6 * self.engagement[u]) * (1.0 if self.has_sub[u] else 0.3)
            times = np.sort(rng.uniform(start, END_SEC, int(rng.poisson(rate * active_days))))
            if self.signup_sec[u] >= 0:
                times = np.concatenate([[self.signup_sec[u]], times])
            n_log = len(times)
            country = np.full(n_log, self.country[u], dtype=object)
            lat = self.home_lat[u] + rng.normal(0, 0.03, n_log)
            lon = self.home_lon[u] + rng.normal(0, 0.03, n_log)
            ip = np.array([self.home_ip[u] if rng.random() < 0.85 else random_ip(rng) for _ in range(n_log)],
                          dtype=object)

            if active_days >= 20 and rng.random() < TRAVELER_SHARE:
                times, country, lat, lon, ip = self._add_trip(u, codes, start, times, country, lat, lon, ip)

            devices = self._pick_devices(u, times)
            success = rng.random(len(times)) < 0.96
            for i in range(len(times)):
                login_counter += 1
                self.rows["logins"].append((
                    f"L{login_counter:08d}", f"U{u + 1:06d}", to_ts(times[i]), ip[i], country[i],
                    round(float(lat[i]), 4), round(float(lon[i]), 4), devices[i],
                    bool(success[i]), bool(success[i] and self.mfa[u])))

    def _add_trip(self, u, codes, start, times, country, lat, lon, ip):
        """A real traveler: leaves, flies at plausible speed, logs in abroad, comes home."""
        rng = self.rng
        dest = rng.choice([c for c in codes if c != self.country[u]])
        dest_lat = C.COUNTRIES[dest].lat + rng.normal(0, 1.0)
        dest_lon = C.COUNTRIES[dest].lon + rng.normal(0, 1.0)
        dist = haversine_km(self.home_lat[u], self.home_lon[u], dest_lat, dest_lon)
        flight = (dist / TRAVEL_SPEED_KMH + 2) * 3600
        trip_start = rng.uniform(start + 2 * DAY, END_SEC - 12 * DAY)
        trip_end = trip_start + rng.uniform(3, 10) * DAY
        arrive = trip_start + flight

        extra = rng.uniform(arrive, trip_end, int(rng.integers(2, 6)))
        in_flight = ((times > trip_start) & (times < arrive)) | ((times > trip_end) & (times < trip_end + flight))
        keep = ~in_flight
        times = np.concatenate([times[keep], extra])
        country = np.concatenate([country[keep], np.full(len(extra), self.country[u], dtype=object)])
        lat = np.concatenate([lat[keep], np.zeros(len(extra))])
        lon = np.concatenate([lon[keep], np.zeros(len(extra))])
        ip = np.concatenate([ip[keep], np.full(len(extra), "", dtype=object)])
        order = np.argsort(times, kind="stable")
        times, country, lat, lon, ip = times[order], country[order], lat[order], lon[order], ip[order]

        abroad = (times >= arrive) & (times <= trip_end)
        hotel_ip = random_ip(rng)
        country[abroad] = dest
        lat[abroad] = dest_lat + rng.normal(0, 0.03, abroad.sum())
        lon[abroad] = dest_lon + rng.normal(0, 0.03, abroad.sum())
        ip[abroad] = hotel_ip
        return times, country, lat, lon, ip

    # ---------- payments ----------
    def make_payment_methods(self):
        rng = self.rng
        codes = list(C.COUNTRIES)
        bin_pool = {c: [str(int(rng.choice([4, 5]))) + f"{int(rng.integers(0, 100_000)):05d}" for _ in range(20)]
                    for c in codes}
        card = {}
        for u in np.flatnonzero(self.has_sub):
            card_country = self.country[u] if rng.random() < 0.95 else rng.choice(codes)
            card[u] = dict(card_fingerprint=stable_hash(self.seed, "card", u),
                           bin=bin_pool[card_country][int(rng.integers(0, 20))],
                           last4=f"{int(rng.integers(0, 10_000)):04d}", card_country=card_country,
                           is_virtual_or_prepaid=bool(rng.random() < VIRTUAL_CARD_SHARE))
        heads = sorted({int(h) for h in self.household_head if h >= 0})
        sharing_heads = {h for h in heads if rng.random() < HOUSEHOLD_CARD_SHARE}
        for u in card:
            head = self.household_head[u]
            if head in sharing_heads and head in card and head != u:
                card[u] = dict(card[head])  # same physical card, separate pm row per account

        self.primary_pm, self.second_pm = {}, {}
        pm_counter = 0
        for u, info in card.items():
            pm_counter += 1
            pm_id = f"PM{pm_counter:06d}"
            added = self.signup_sec[u] + rng.uniform(30, 600)
            self.rows["payment_methods"].append((pm_id, f"U{u + 1:06d}", info["card_fingerprint"], info["bin"],
                                                 info["last4"], info["card_country"],
                                                 info["is_virtual_or_prepaid"], to_ts(added)))
            self.primary_pm[u] = pm_id
            if rng.random() < 0.12 and max(added, 0) + 2 * DAY < END_SEC:  # legit customer adds a new card
                pm_counter += 1
                pm2 = f"PM{pm_counter:06d}"
                added2 = rng.uniform(max(added, 0) + DAY, END_SEC - DAY)
                self.rows["payment_methods"].append((
                    pm2, f"U{u + 1:06d}", stable_hash(self.seed, "card2", u), info["bin"],
                    f"{int(rng.integers(0, 10_000)):04d}", info["card_country"], False, to_ts(added2)))
                self.second_pm[u] = (pm2, added2)
                self._event(u, added2, "payment_method_add")
            if added >= 0:
                self._event(u, added, "payment_method_add")

    def _event(self, u: int, sec: float, event_type: str):
        if 0 <= sec < END_SEC:
            self.rows["account_events"].append([None, f"U{u + 1:06d}", to_ts(sec), event_type,
                                                self.signup_device[u], self.home_ip[u]])

    def _txn(self, u, pm_id, sec, amount, txn_type, result, reason=None) -> str:
        txn_id = f"T{len(self.rows['transactions']) + 1:08d}"
        self.rows["transactions"].append((txn_id, f"U{u + 1:06d}", pm_id, to_ts(sec), round(amount, 2), "USD",
                                          txn_type, result, reason, self.home_ip[u], self.signup_device[u]))
        return txn_id

    def _pm_at(self, u, sec):
        second = self.second_pm.get(u)
        return second[0] if second and sec >= second[1] else self.primary_pm[u]

    def _charge(self, u, sec, amount, is_renewal) -> float | None:
        """Charge with realistic declines and one retry. Returns the cancel time on involuntary churn."""
        rng = self.rng
        if rng.random() >= DECLINE_RATE:
            txn = self._txn(u, self._pm_at(u, sec), sec, amount, "charge", "approved")
            self._after_approval(u, txn, sec, amount, is_renewal)
            return None
        reason = rng.choice(DECLINE_REASONS[0], p=DECLINE_REASONS[1])
        self._txn(u, self._pm_at(u, sec), sec, amount, "charge", "declined", reason)
        retry = sec + rng.uniform(1, 3) * DAY
        if retry >= END_SEC:
            return None
        if rng.random() < RETRY_SUCCESS:
            txn = self._txn(u, self._pm_at(u, retry), retry, amount, "charge", "approved")
            self._after_approval(u, txn, retry, amount, is_renewal)
            return None
        self._txn(u, self._pm_at(u, retry), retry, amount, "charge", "declined", reason)
        return retry

    def _after_approval(self, u, txn_id, sec, amount, is_renewal):
        self.approved_charges.append((txn_id, to_ts(sec), is_renewal))
        if self.rng.random() < REFUND_RATE:
            refund_at = sec + self.rng.uniform(1, 14) * DAY
            if refund_at < END_SEC:
                self._txn(u, self._pm_at(u, refund_at), refund_at, amount, "refund", "approved")

    # ---------- subscriptions, billing, usage ----------
    def make_subscriptions(self):
        rng = self.rng
        self.usage_window = {}
        for u in np.flatnonzero(self.has_sub):
            plan = "student" if self.is_student[u] else rng.choice(["single_app", "photography", "all_apps"],
                                                                  p=[0.45, 0.30, 0.25])
            mult = C.COUNTRIES[self.country[u]].price_multiplier
            is_trial, trial_start, trial_end, converted, canceled = False, None, None, True, None
            status = "active"
            if self.preexisting[u]:
                first_charge = rng.uniform(0, C.BILLING_CYCLE_DAYS) * DAY
                use_start = 0.0
            elif rng.random() < 0.6:
                is_trial = True
                trial_start = self.signup_sec[u] + rng.uniform(60, 3600)
                trial_end = trial_start + C.TRIAL_DAYS * DAY
                use_start = trial_start
                self._txn(u, self.primary_pm[u], trial_start, 1.00, "auth",
                          *(("approved",) if rng.random() < 0.97 else ("declined", "do_not_honor")))
                if trial_end >= END_SEC:
                    converted, status, first_charge = None, "trialing", None
                elif rng.random() < 0.55:
                    first_charge = trial_end
                else:
                    converted, status, first_charge = False, "canceled", None
                    canceled = trial_start + rng.uniform(0.5, 6.9) * DAY
            else:
                first_charge = self.signup_sec[u] + 60
                use_start = first_charge

            if first_charge is not None and rng.random() < 0.08:  # voluntary churn
                if first_charge + DAY < END_SEC - DAY:
                    canceled = rng.uniform(first_charge + DAY, END_SEC - DAY)

            new_plan, change_at = plan, None
            if first_charge is not None and plan != "student" and rng.random() < 0.04:
                new_plan = rng.choice([p for p in ["single_app", "photography", "all_apps"] if p != plan])
                change_at = rng.uniform(max(first_charge, 0), END_SEC)
                self._event(u, change_at, "plan_change")

            t, is_renewal = first_charge, bool(self.preexisting[u])
            while t is not None and t < END_SEC and (canceled is None or t < canceled):
                current = new_plan if change_at is not None and t >= change_at else plan
                failed_at = self._charge(u, t, C.PLAN_PRICES[current] * mult, is_renewal)
                if failed_at is not None:
                    canceled = failed_at
                    break
                t, is_renewal = t + C.BILLING_CYCLE_DAYS * DAY, True

            if canceled is not None:
                status = "canceled"
                self._event(u, canceled, "cancel")
            self.rows["subscriptions"].append((
                f"S{u + 1:06d}", f"U{u + 1:06d}", new_plan, self.country[u], is_trial,
                to_ts(trial_start) if trial_start is not None else None,
                to_ts(trial_end) if trial_end is not None else None,
                converted, status, to_ts(canceled) if canceled is not None else None))
            self.usage_window[u] = (new_plan, use_start, canceled if canceled is not None else END_SEC)

    def make_usage(self):
        rng = self.rng
        for u in range(self.n):
            if u in self.usage_window:
                plan, start, end = self.usage_window[u]
                p = 0.15 + 0.7 * self.engagement[u]
            else:
                plan, start, end = "free", max(self.signup_sec[u], 0.0), END_SEC
                p = 0.1 * self.engagement[u]
            days = np.arange(int(max(start, 0) // DAY), int(np.ceil(end / DAY)))
            active = days[rng.random(len(days)) < p]
            favourite = SINGLE_APP_CHOICES[int(rng.integers(0, 4))]
            for d in active:
                for app in self._apps_for_day(plan, favourite):
                    sessions = 1 + int(rng.poisson(1.0))
                    minutes = int(sessions * rng.gamma(2.0, 15.0)) + 1
                    self.rows["usage_events"].append((f"U{u + 1:06d}", (C.WINDOW_START + timedelta(days=int(d))).date(),
                                                      app, sessions, minutes))

    def _apps_for_day(self, plan: str, favourite: str) -> list[str]:
        rng = self.rng
        if plan == "free":
            return ["Acrobat"]
        if plan == "single_app":
            return [favourite]
        if plan == "photography":
            return ["Lightroom"] if rng.random() < 0.7 else ["Photoshop"]
        k = 1 if rng.random() < 0.6 else 2
        return list(rng.choice(C.APPS, size=k, replace=False))

    def make_security_events(self):
        """Legit resets and email changes. A few are reset -> email change from the owner's own device."""
        rng = self.rng
        for u in range(self.n):
            start = max(self.signup_sec[u], 0.0)
            if start >= END_SEC - 2 * DAY:
                continue
            draw = rng.random()
            t = rng.uniform(start, END_SEC - 2 * DAY)
            if draw < 0.004:
                self._event(u, t, "password_reset")
                self._event(u, t + rng.uniform(1, 24) * 3600, "email_change")
            elif draw < 0.034:
                self._event(u, t, "password_reset")
            elif draw < 0.041:
                self._event(u, t, "email_change")

    # ---------- output ----------
    def build(self) -> dict[str, pd.DataFrame]:
        self.make_profiles()
        self.make_users_and_devices()
        self.make_logins()
        self.make_payment_methods()
        self.make_subscriptions()
        self.make_security_events()
        self.make_usage()

        events = sorted(self.rows["account_events"], key=lambda r: (r[2], r[1], r[3]))
        for i, row in enumerate(events):
            row[0] = f"E{i + 1:07d}"
        self.rows["account_events"] = [tuple(r) for r in events]

        columns = {
            "users": ["user_id", "email", "signup_ts", "country", "signup_ip", "signup_device_id",
                      "account_age_days"],
            "devices": ["device_id", "fingerprint_hash", "os", "browser", "first_seen_ts"],
            "logins": ["login_id", "user_id", "ts", "ip", "country", "lat", "lon", "device_id", "success",
                       "mfa_used"],
            "account_events": ["event_id", "user_id", "ts", "event_type", "device_id", "ip"],
            "payment_methods": ["pm_id", "user_id", "card_fingerprint", "bin", "last4", "card_country",
                                "is_virtual_or_prepaid", "added_ts"],
            "subscriptions": ["sub_id", "user_id", "plan", "price_tier_country", "is_trial", "trial_start_ts",
                              "trial_end_ts", "converted", "status", "canceled_ts"],
            "transactions": ["txn_id", "user_id", "pm_id", "ts", "amount", "currency", "txn_type", "result",
                             "decline_reason", "ip", "device_id"],
            "usage_events": ["user_id", "date", "app", "sessions", "minutes"],
        }
        tables = {name: pd.DataFrame(self.rows[name], columns=cols) for name, cols in columns.items()}
        tables["disputes"] = pd.DataFrame(disputes.baseline_disputes(self.rng, self.approved_charges))
        return tables


def generate(seed: int = C.SEED, n_users: int = C.N_USERS) -> dict[str, pd.DataFrame]:
    return BaselineWorld(seed, n_users).build()
