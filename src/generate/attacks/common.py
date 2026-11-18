"""Helpers shared by attack injectors: id allocation, buffered row writes, ground truth."""
import hashlib
from datetime import datetime, timedelta

import pandas as pd

from src import config as C
from src.db import append_tables, refresh_derived_columns

ID_FORMATS = {  # table -> (id column, prefix, zero-padded width)
    "users": ("user_id", "U", 6),
    "devices": ("device_id", "D", 7),
    "logins": ("login_id", "L", 8),
    "account_events": ("event_id", "E", 7),
    "payment_methods": ("pm_id", "PM", 6),
    "subscriptions": ("sub_id", "S", 6),
    "transactions": ("txn_id", "T", 8),
    "disputes": ("dispute_id", "DP", 6),
}
CAMPAIGN_PREFIX = {"card_testing": "CT", "trial_abuse": "TA", "ato": "ATO", "friendly_fraud": "FF"}


DAY = 86_400.0
END_SEC = C.WINDOW_DAYS * DAY


def to_ts(sec: float) -> datetime:
    return C.WINDOW_START + timedelta(seconds=round(float(sec)))


def stable_hash(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def random_bin(rng) -> str:
    return str(int(rng.choice([4, 5]))) + f"{int(rng.integers(0, 100_000)):05d}"


def random_ip(rng) -> str:
    a = int(rng.integers(11, 224))
    b, c, d = (int(x) for x in rng.integers(0, 256, 3))
    return f"{a}.{b}.{c}.{d}"


def next_campaign_id(con, attack_type: str) -> str:
    prefix = CAMPAIGN_PREFIX[attack_type]
    n = con.execute("SELECT count(DISTINCT campaign_id) FROM ground_truth WHERE campaign_id LIKE ?",
                    [f"{prefix}-%"]).fetchall()[0][0]
    return f"{prefix}-{n + 1:03d}"


class CampaignWriter:
    """Collects rows for one campaign, hands out unique ids, writes everything in one go."""

    def __init__(self, con, attack_type: str):
        self.con = con
        self.attack_type = attack_type
        self.campaign_id = next_campaign_id(con, attack_type)
        self.rows: dict[str, list[dict]] = {}
        self._next: dict[str, int] = {}

    def new_id(self, table: str) -> str:
        col, prefix, width = ID_FORMATS[table]
        if table not in self._next:
            current = self.con.execute(
                f"SELECT max(CAST(regexp_extract({col}, '\\d+$') AS BIGINT)) FROM {table}").fetchall()[0][0]
            self._next[table] = (current or 0) + 1
        n = self._next[table]
        self._next[table] += 1
        return f"{prefix}{n:0{width}d}"

    def add(self, table: str, **row) -> dict:
        self.rows.setdefault(table, []).append(row)
        return row

    def truth(self, entity_type: str, entity_id: str, sec: float, label: str = "attack",
              attack_type: str | None = None):
        self.add("ground_truth", entity_type=entity_type, entity_id=entity_id, campaign_id=self.campaign_id,
                 attack_type=attack_type or self.attack_type, injected_ts=to_ts(sec), label=label)

    def flush(self) -> str:
        tables = {name: pd.DataFrame(rows) for name, rows in self.rows.items()}
        if "ground_truth" in tables:  # one row per entity even if it was registered twice
            tables["ground_truth"] = tables["ground_truth"].drop_duplicates(
                subset=["entity_type", "entity_id", "label"])
        append_tables(self.con, tables)
        refresh_derived_columns(self.con)
        return self.campaign_id


# ---------- row builders shared by injectors ----------
def add_device(w: CampaignWriter, sec: float, os_browser: tuple[str, str]) -> str:
    device_id = w.new_id("devices")
    w.add("devices", device_id=device_id, fingerprint_hash=stable_hash("dev", w.campaign_id, device_id),
          os=os_browser[0], browser=os_browser[1], first_seen_ts=to_ts(sec))
    return device_id


def add_payment_method(w: CampaignWriter, user_id: str, card: tuple[str, str], sec: float, salt: str,
                       card_country: str = "US", is_virtual: bool = False) -> str:
    """card is (bin, last4). The same (salt, bin, last4) always gives the same card fingerprint."""
    pm_id = w.new_id("payment_methods")
    w.add("payment_methods", pm_id=pm_id, user_id=user_id, card_fingerprint=stable_hash("card", salt, *card),
          bin=card[0], last4=card[1], card_country=card_country, is_virtual_or_prepaid=is_virtual,
          added_ts=to_ts(sec))
    return pm_id


def add_txn(w: CampaignWriter, user_id, pm_id, sec, amount, txn_type, result, reason, ip, device_id) -> str:
    txn_id = w.new_id("transactions")
    w.add("transactions", txn_id=txn_id, user_id=user_id, pm_id=pm_id, ts=to_ts(sec), amount=round(amount, 2),
          currency="USD", txn_type=txn_type, result=result, decline_reason=reason, ip=ip, device_id=device_id)
    return txn_id


def add_dispute(w: CampaignWriter, rng, txn_id: str, txn_sec: float, reason: str,
                force_visible: bool = False) -> str | None:
    """File a dispute with the shared lag model. Returns None if it lands after the window ends,
    unless force_visible, which redraws the lag (used when a scenario needs an observable dispute)."""
    from src.generate.disputes import dispute_row
    for _ in range(50 if force_visible else 1):
        dispute_id = w.new_id("disputes")
        row = dispute_row(rng, dispute_id, txn_id, to_ts(txn_sec), reason)
        if row:
            w.add("disputes", **row)
            return dispute_id
    return None


def add_genuine_fraud_dispute(w: CampaignWriter, rng, txn_id: str, txn_sec: float, rate: float):
    """The real cardholder disputes a charge they truly didn't make. For friendly-fraud detection this is
    the hardest lookalike: an 'unauthorized' dispute that is honest."""
    if rng.random() < rate:
        dispute_id = add_dispute(w, rng, txn_id, txn_sec, "unauthorized")
        if dispute_id:
            w.truth("dispute", dispute_id, txn_sec, label="lookalike", attack_type="friendly_fraud")
