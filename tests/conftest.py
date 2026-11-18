import pytest

from src.db import run_detection
from src.generate.run import build_database

TEST_SEED = 7
TEST_USERS = 2_000


@pytest.fixture(scope="session")
def small_db(tmp_path_factory):
    """A small but complete world with the default attack campaigns and detections, built once."""
    path = tmp_path_factory.mktemp("db") / "test.duckdb"
    con = build_database(path, seed=TEST_SEED, n_users=TEST_USERS)
    run_detection(con)
    yield con
    con.close()


@pytest.fixture(scope="session")
def baseline_only_db(tmp_path_factory):
    """Legit customers only, no attacks. Read-only by convention: do not inject into it."""
    path = tmp_path_factory.mktemp("baseline") / "baseline.duckdb"
    con = build_database(path, seed=TEST_SEED + 1, n_users=800, with_attacks=False)
    yield con
    con.close()


@pytest.fixture(scope="session")
def injection_db(tmp_path_factory):
    """A legit-only world that tests may inject custom campaigns into."""
    path = tmp_path_factory.mktemp("inject") / "inject.duckdb"
    con = build_database(path, seed=TEST_SEED + 2, n_users=800, with_attacks=False)
    yield con
    con.close()


@pytest.fixture(scope="session")
def macro_db(tmp_path_factory):
    """An empty warehouse with only schema and macros, for pure SQL unit tests."""
    from src.db import create_fresh_database
    con = create_fresh_database(tmp_path_factory.mktemp("macros") / "macros.duckdb")
    yield con
    con.close()
