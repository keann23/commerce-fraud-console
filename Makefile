PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: setup data detect eval test app all clean dbt

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

data:
	$(PY) -m src.generate.run

detect:
	$(PY) -m src.db detect

test:
	$(PY) -m pytest -q

app:
	$(PY) -m streamlit run app/Home.py

all: data detect eval test

clean:
	rm -f data/commerce.duckdb data/commerce.duckdb.wal

eval:
	$(PY) -m src.evaluate

# Phase 2: regenerate dbt models from sql/, build them with tests, prove parity with `make detect`.
dbt: detect
	$(PY) dbt/sync_from_sql.py
	cd dbt && ../$(PY) -m dbt.cli.main build --profiles-dir .
	$(PY) dbt/check_parity.py
