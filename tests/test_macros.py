"""Unit tests for the SQL macros that detections are built on."""
import pytest

from src.generate.geo import haversine_km


def one(con, sql, *params):
    return con.execute(sql, list(params)).fetchone()[0]


@pytest.mark.parametrize("raw, expected", [
    ("k.e.an@gmail.com", "kean@gmail.com"),            # Gmail ignores dots
    ("kean+7@gmail.com", "kean@gmail.com"),            # plus tag stripped
    ("K.Ean+Trial12@GMAIL.com", "kean@gmail.com"),     # case + dots + plus together
    ("kean@googlemail.com", "kean@gmail.com"),         # Googlemail is the same inbox
    ("  Kean@Gmail.com ", "kean@gmail.com"),           # whitespace
    ("k.ean@outlook.com", "k.ean@outlook.com"),        # dots matter outside Gmail
    ("kean+promo@outlook.com", "kean@outlook.com"),    # plus tags stripped for all providers
])
def test_normalize_email(macro_db, raw, expected):
    assert one(macro_db, "SELECT normalize_email(?)", raw) == expected


@pytest.mark.parametrize("email, disposable", [
    ("x@mailinator.com", True),
    ("x@YOPMAIL.com", True),
    ("x@gmail.com", False),
    ("x@stateu.edu", False),
])
def test_disposable_domains(macro_db, email, disposable):
    assert one(macro_db, "SELECT is_disposable_email(?)", email) is disposable


def test_haversine_known_distance(macro_db):
    # New York JFK -> London Heathrow is about 5,540 km.
    km = one(macro_db, "SELECT haversine_km(40.6413, -73.7781, 51.4700, -0.4543)")
    assert 5500 < km < 5580
    assert km == pytest.approx(haversine_km(40.6413, -73.7781, 51.4700, -0.4543), rel=1e-9)


def test_impossible_travel_speed(macro_db):
    # NYC then London 1 hour later: ~5,540 km/h, clearly impossible (> 900 km/h).
    fast = one(macro_db, """SELECT travel_speed_kmh(40.6413, -73.7781, TIMESTAMP '2026-09-01 10:00',
                                                    51.4700, -0.4543, TIMESTAMP '2026-09-01 11:00')""")
    # Same trip over 8 hours: ~690 km/h, a normal flight.
    slow = one(macro_db, """SELECT travel_speed_kmh(40.6413, -73.7781, TIMESTAMP '2026-09-01 10:00',
                                                    51.4700, -0.4543, TIMESTAMP '2026-09-01 18:00')""")
    assert fast > 900
    assert slow < 900


def test_travel_speed_handles_identical_timestamps(macro_db):
    speed = one(macro_db, """SELECT travel_speed_kmh(0, 0, TIMESTAMP '2026-09-01 10:00',
                                                     0, 1, TIMESTAMP '2026-09-01 10:00')""")
    assert speed > 0 and speed != float("inf")
