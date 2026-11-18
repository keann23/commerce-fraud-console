"""Shared constants for the synthetic commerce world. Change the seed here, nowhere else."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "commerce.duckdb"
SQL_DIR = ROOT / "sql"

SEED = 42
N_USERS = 20_000
WINDOW_START = datetime(2026, 7, 18)
WINDOW_DAYS = 120
WINDOW_END = WINDOW_START + timedelta(days=WINDOW_DAYS)
TRIAL_DAYS = 7
BILLING_CYCLE_DAYS = 30

# Monthly list price in USD. Regional tiers are applied as a multiplier per country,
# and all amounts are stored in USD so SQL can sum them without FX conversion.
PLAN_PRICES = {
    "single_app": 22.99,
    "photography": 19.99,
    "all_apps": 59.99,
    "student": 19.99,
}
APPS = ["Photoshop", "Lightroom", "Illustrator", "Premiere", "Acrobat"]


@dataclass(frozen=True)
class Country:
    lat: float
    lon: float
    price_multiplier: float
    weight: float


COUNTRIES = {
    "US": Country(39.8, -98.6, 1.00, 0.38),
    "CA": Country(56.1, -106.3, 0.95, 0.05),
    "GB": Country(52.4, -1.5, 1.05, 0.08),
    "DE": Country(51.2, 10.4, 1.05, 0.07),
    "FR": Country(46.6, 2.2, 1.05, 0.05),
    "NL": Country(52.1, 5.3, 1.05, 0.02),
    "ES": Country(40.4, -3.7, 1.00, 0.03),
    "JP": Country(36.2, 138.3, 0.95, 0.06),
    "KR": Country(36.5, 127.9, 0.90, 0.03),
    "AU": Country(-25.3, 133.8, 1.00, 0.04),
    "SG": Country(1.35, 103.8, 0.95, 0.02),
    "BR": Country(-14.2, -51.9, 0.60, 0.06),
    "MX": Country(23.6, -102.6, 0.65, 0.04),
    "IN": Country(20.6, 79.0, 0.40, 0.07),
}

EMAIL_DOMAINS = {
    "gmail.com": 0.45,
    "yahoo.com": 0.12,
    "outlook.com": 0.12,
    "hotmail.com": 0.08,
    "icloud.com": 0.10,
    "proton.me": 0.03,
    "aol.com": 0.02,
    "comcast.net": 0.03,
    "web.de": 0.05,
}
EDU_DOMAINS = ["stateu.edu", "techinst.edu", "cityuniv.edu", "northcollege.edu", "artschool.edu"]
