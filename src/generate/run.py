"""Build data/commerce.duckdb from scratch: schema, macros, baseline world, default attack campaigns.
`make data` calls this. Attack Mode in the app calls the same injectors on top of this database."""
import argparse
import time
from pathlib import Path

import numpy as np

from src import config as C
from src.db import append_tables, create_fresh_database, refresh_derived_columns
from src.generate.attacks.ato import inject_ato
from src.generate.attacks.card_testing import CARD_PATTERNS, inject_card_testing
from src.generate.attacks.trial_abuse import inject_trial_abuse
from src.generate.baseline import generate

DEFAULT_CARD_TESTING_CAMPAIGNS = 12
DEFAULT_TRIAL_ABUSE_CAMPAIGNS = 10
DEFAULT_ATO_CAMPAIGNS = 8


def inject_default_attacks(con, seed: int) -> list[str]:
    """A spread of campaigns across the PRD parameter ranges, so evaluation covers easy and hard cases."""
    rng = np.random.default_rng(seed + 1)
    campaigns = []
    for i in range(DEFAULT_CARD_TESTING_CAMPAIGNS):
        campaigns.append(inject_card_testing(
            con, seed=seed * 1000 + i,
            attempts=int(rng.integers(100, 501)),
            duration_minutes=int(rng.integers(5, 31)),
            n_ips=int(rng.integers(1, 4)),
            n_devices=int(rng.integers(1, 4)),
            decline_rate=float(rng.uniform(0.7, 0.9)),
            card_pattern=CARD_PATTERNS[i % len(CARD_PATTERNS)],
        ))
    for i in range(DEFAULT_TRIAL_ABUSE_CAMPAIGNS):
        campaigns.append(inject_trial_abuse(
            con, seed=seed * 2000 + i,
            n_accounts=int(rng.integers(10, 51)),
            duration_days=int(rng.integers(10, 46)),
            n_devices=int(rng.integers(1, 4)),
            n_virtual_cards=int(rng.integers(1, 4)),
            student_variant=i % 4 == 3,
        ))
    for i in range(DEFAULT_ATO_CAMPAIGNS):
        campaigns.append(inject_ato(
            con, seed=seed * 3000 + i,
            n_victims=int(rng.integers(5, 16)),
            impossible_travel_rate=float(rng.uniform(0.2, 0.7)),
            monetize_rate=float(rng.uniform(0.5, 1.0)),
            n_devices=int(rng.integers(1, 4)),
        ))
    return campaigns


def build_database(path: Path | str = C.DB_PATH, seed: int = C.SEED, n_users: int = C.N_USERS,
                   with_attacks: bool = True):
    tables = generate(seed=seed, n_users=n_users)
    con = create_fresh_database(path)
    append_tables(con, tables)
    refresh_derived_columns(con)
    if with_attacks:
        inject_default_attacks(con, seed)
    return con


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=C.SEED)
    parser.add_argument("--users", type=int, default=C.N_USERS)
    parser.add_argument("--no-attacks", action="store_true")
    args = parser.parse_args()

    started = time.time()
    con = build_database(seed=args.seed, n_users=args.users, with_attacks=not args.no_attacks)
    print(f"Built {C.DB_PATH.relative_to(C.ROOT)} (seed={args.seed}) in {time.time() - started:.1f}s")
    for (name,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
        count = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        print(f"  {name:<20}{count:>10,}")
    con.close()


if __name__ == "__main__":
    main()
