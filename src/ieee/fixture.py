"""A small FAKE dataset with the IEEE-CIS column names, for testing the validation pipeline only.

It plants a few signals on the fraud rows (velocity bursts, micro amounts, anonymous inboxes, new
devices) so the tests can check the pipeline measures lift correctly. Its numbers mean nothing about
real fraud and are never written to docs/.
"""
from pathlib import Path

import numpy as np
import pandas as pd


def write_fixture(out_dir: Path, n_customers: int = 600, seed: int = 3) -> Path:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    txns, ids = [], []
    tid = 3_000_000
    for c in range(n_customers):
        card1, addr1 = 1000 + c, int(rng.integers(100, 500))
        first_day = int(rng.integers(0, 60))
        device = f"Device-{c}"
        email = str(rng.choice(["gmail.com", "yahoo.com", "hotmail.com"]))
        fraudster = rng.random() < 0.08
        t = first_day * 86400 + int(rng.integers(0, 86400))
        for k in range(int(rng.integers(2, 8))):
            fraud = fraudster and k >= 1
            tid += 1
            if fraud:
                t += int(rng.integers(60, 900))                    # bursts minutes apart
                amount = float(rng.choice([1.0, 2.5, 300.0]))      # micro tests or a big hit
                txn_device = f"Device-new-{c}"                     # unfamiliar device
                p_email = "anonymous.com" if rng.random() < 0.5 else email
            else:
                t += int(rng.integers(2, 20)) * 86400               # normal customers: days apart
                amount = float(round(rng.gamma(3, 30), 2))
                txn_device, p_email = device, email
            day = t / 86400
            txns.append({"TransactionID": tid, "isFraud": int(fraud), "TransactionDT": t, "TransactionAmt": amount,
                         "ProductCD": "W", "card1": card1, "addr1": addr1, "P_emaildomain": p_email,
                         "R_emaildomain": None, "D1": int(day - first_day)})
            ids.append({"TransactionID": tid, "DeviceType": "desktop", "DeviceInfo": txn_device})
    pd.DataFrame(txns).to_csv(out_dir / "train_transaction.csv", index=False)
    pd.DataFrame(ids).to_csv(out_dir / "train_identity.csv", index=False)
    return out_dir
