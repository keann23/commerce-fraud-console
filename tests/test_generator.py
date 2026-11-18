"""The baseline world is deterministic and contains the legit noise the PRD asks for."""
import pandas as pd

from src.generate.baseline import generate


def test_same_seed_same_data():
    a, b = generate(seed=11, n_users=400), generate(seed=11, n_users=400)
    assert a.keys() == b.keys()
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name], check_dtype=True)


def test_different_seed_different_data():
    a, b = generate(seed=11, n_users=400), generate(seed=12, n_users=400)
    assert not a["users"]["email"].equals(b["users"]["email"])


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def test_baseline_has_no_ground_truth(baseline_only_db):
    assert scalar(baseline_only_db, "SELECT count(*) FROM ground_truth") == 0


def test_households_share_devices(small_db):
    shared = scalar(small_db, """SELECT count(*) FROM (SELECT signup_device_id FROM users
                                 GROUP BY 1 HAVING count(*) > 1)""")
    assert shared > 0


def test_travelers_exist_and_never_exceed_plane_speed(small_db):
    abroad = scalar(small_db, """SELECT count(DISTINCT l.user_id) FROM logins l JOIN users u USING (user_id)
                                 WHERE l.country <> u.country""")
    impossible = scalar(small_db, """
        WITH pairs AS (
            SELECT user_id, lat, lon, ts, lag(lat) OVER w AS plat, lag(lon) OVER w AS plon, lag(ts) OVER w AS pts
            FROM logins WINDOW w AS (PARTITION BY user_id ORDER BY ts))
        SELECT count(*) FROM pairs
        WHERE user_id NOT IN (SELECT entity_id FROM ground_truth WHERE label = 'attack')
          AND pts IS NOT NULL AND haversine_km(plat, plon, lat, lon) > 500
          AND travel_speed_kmh(plat, plon, pts, lat, lon, ts) > 900""")
    assert abroad > 0
    assert impossible == 0, "legit travelers must move at plausible speeds"


def test_plus_addressed_emails_exist_but_no_legit_inbox_collisions(baseline_only_db):
    assert scalar(baseline_only_db, "SELECT count(*) FROM users WHERE email LIKE '%+%'") > 0
    collisions = scalar(baseline_only_db, """SELECT count(*) FROM (SELECT email_normalized FROM users
                                     GROUP BY 1 HAVING count(*) > 1)""")
    assert collisions == 0


def test_normal_decline_rate_is_realistic(small_db):
    rate = scalar(small_db, """SELECT avg((result = 'declined')::INT) FROM transactions
                               WHERE txn_type = 'charge'""")
    assert 0.03 < rate < 0.10


def test_forgotten_renewal_disputes_exist_and_respect_label_delay(small_db):
    assert scalar(small_db, """SELECT count(*) FROM disputes
                               WHERE reason_category = 'canceled_subscription'""") > 0
    too_fast = scalar(small_db, """SELECT count(*) FROM disputes d JOIN transactions t USING (txn_id)
                                   WHERE d.filed_ts < t.ts + INTERVAL 2 DAY""")
    assert too_fast == 0
