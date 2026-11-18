"""Prove the dbt port and the plain-SQL pipeline produce identical results.

Compares every table dbt built (schema `dbt`) with the one `make detect` built (schema `main`),
row for row in both directions. Run after `make detect` and `dbt build`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402


def main() -> int:
    con = connect(read_only=True)
    models = [p.stem for p in (ROOT / "dbt" / "models").rglob("*.sql")]
    failures = 0
    for name in sorted(models):
        cols = [r[0] for r in con.execute(f"DESCRIBE main.{name}").fetchall()
                if r[1] not in ("VARCHAR[]",)]  # list columns compared via string form below
        lists = [r[0] for r in con.execute(f"DESCRIBE main.{name}").fetchall() if r[1] == "VARCHAR[]"]
        select = ", ".join(cols + [f"CAST({c} AS VARCHAR) AS {c}" for c in lists])
        only_main, only_dbt = con.execute(f"""
            SELECT (SELECT count(*) FROM (SELECT {select} FROM main.{name} EXCEPT ALL SELECT {select} FROM dbt.{name})),
                   (SELECT count(*) FROM (SELECT {select} FROM dbt.{name} EXCEPT ALL SELECT {select} FROM main.{name}))
        """).fetchall()[0]
        rows = con.execute(f"SELECT count(*) FROM main.{name}").fetchall()[0][0]
        ok = only_main == 0 and only_dbt == 0
        failures += not ok
        print(f"{'OK ' if ok else 'DIFF'} {name:<30} {rows:>8,} rows" + ("" if ok else f"  (-{only_main} / +{only_dbt})"))
    print("dbt output matches plain SQL" if not failures else f"{failures} table(s) differ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
