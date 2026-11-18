"""DuckDB connection, table loading and the SQL runner. Python orchestrates; logic lives in sql/."""
import sys
from pathlib import Path

import duckdb
import pandas as pd

from src.config import DB_PATH, PLAN_PRICES, SQL_DIR

TABLE_ORDER = [
    "users", "devices", "logins", "account_events", "payment_methods",
    "subscriptions", "transactions", "usage_events", "disputes", "ground_truth",
]
DETECT_STAGES = [SQL_DIR / "features", SQL_DIR / "detect", SQL_DIR / "response_ladder.sql"]


def connect(path: Path | str = DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text())


def run_sql_path(con: duckdb.DuckDBPyConnection, path: Path) -> list[Path]:
    """Run one .sql file, or every .sql file in a directory in filename order."""
    if path.is_dir():
        files = sorted(path.glob("*.sql"))
    elif path.exists():
        files = [path]
    else:
        files = []
    for f in files:
        run_sql_file(con, f)
    return files


def create_fresh_database(path: Path | str = DB_PATH) -> duckdb.DuckDBPyConnection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for stale in (path, path.with_suffix(path.suffix + ".wal")):
        stale.unlink(missing_ok=True)
    con = connect(path)
    run_sql_file(con, SQL_DIR / "schema.sql")
    run_sql_file(con, SQL_DIR / "macros.sql")
    con.executemany("INSERT INTO plan_prices VALUES (?, ?)", list(PLAN_PRICES.items()))
    return con


def append_tables(con: duckdb.DuckDBPyConnection, tables: dict[str, pd.DataFrame]) -> None:
    """Insert DataFrames into existing tables, matching columns by name."""
    for name in TABLE_ORDER:
        df = tables.get(name)
        if df is None or df.empty:
            continue
        cols = ", ".join(df.columns)
        con.register("_incoming", df)
        con.execute(f"INSERT INTO {name} ({cols}) SELECT {cols} FROM _incoming")
        con.unregister("_incoming")


def refresh_derived_columns(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("UPDATE users SET email_normalized = normalize_email(email)")


def run_detection(con: duckdb.DuckDBPyConnection) -> list[Path]:
    ran = []
    for stage in DETECT_STAGES:
        ran += run_sql_path(con, stage)
    return ran


if __name__ == "__main__":
    if sys.argv[1:] == ["detect"]:
        with connect() as con:
            files = run_detection(con)
        print(f"Ran {len(files)} SQL file(s): " + (", ".join(f.name for f in files) or "none yet"))
    else:
        sys.exit("usage: python -m src.db detect")
