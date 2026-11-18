# Splunk versions of the detections

The same four detections, written in SPL so they can run where many fraud and security teams actually work: on raw event logs in Splunk.

> **Status: written, not yet run against a live Splunk instance.** The log export is tested; the SPL follows the SQL logic line by line, but it hasn't been executed in Splunk from this repo. If a search errors, the SQL file it mirrors is the reference for the intended logic.

## Load the data (about 15 minutes)

1. **Get Splunk.** Splunk Enterprise has a free trial that converts to Splunk Free (500 MB/day indexing); the export is about 250 MB.
2. **Export the logs** from this repo:
   ```bash
   make data
   .venv/bin/python splunk/export_logs.py
   ```
   This writes `data/splunk/*.json` (one file per sourcetype) plus `ground_truth.csv` and `disposable_domains.csv`.
3. **Create an index** named `fraud` (Settings → Indexes → New Index).
4. **Add the sourcetypes:** copy `splunk/props.conf` into an app's `local/props.conf`, or in the Add Data wizard pick JSON with timestamp field `ts`.
5. **Upload each file** (Settings → Add Data → Upload) into index `fraud` with these sourcetypes:

   | File | Sourcetype |
   |---|---|
   | payments.json | `fraud:payments` |
   | logins.json | `fraud:logins` |
   | account_events.json | `fraud:account_events` |
   | signups.json | `fraud:signups` |
   | payment_methods.json | `fraud:payment_methods` |
   | usage.json | `fraud:usage` |
   | disputes.json | `fraud:disputes` |

6. **Upload the lookups** (Settings → Lookups → Lookup table files): `disposable_domains.csv` (used by trial abuse) and `ground_truth.csv` (only for `evaluate.spl`).
7. **Run the searches** in `searches/` with the time range set to **All time**.

## The searches

| File | Mirrors | Technique |
|---|---|---|
| `card_testing.spl` | `sql/detect/card_testing.sql` | `mvexpand` each attempt to IP and device, `streamstats time_window=10m` for rolling velocity, `dedup` to keep the worst window |
| `ato.spl` | `sql/detect/ato.sql` | `streamstats current=f` for "no earlier successful login from this device/country", haversine in `eval`, carry the latest anchor forward per account, score the 48 hours after it |
| `trial_abuse.spl` | `sql/detect/trial_abuse.sql` | email normalization in `eval`, group accounts by each shared device/card/inbox (**one hop**, see below) |
| `friendly_fraud.spl` | `sql/detect/friendly_fraud.sql` | `streamstats` for same-device/IP purchase history, `join` to disputes, `map` for each dispute's after-purchase window |
| `evaluate.spl` | `src/evaluate.py` | recall against the `ground_truth` lookup, for training only |

## SQL → SPL: what translates and what doesn't

| SQL idea | SPL equivalent | Notes |
|---|---|---|
| `count(*) OVER (... RANGE INTERVAL 10 MINUTES PRECEDING)` | `streamstats time_window=10m ... by entity` | Needs events in time order |
| `lag()` | `streamstats current=f last(x)` | |
| `row_number() ... = 1` / `QUALIFY` | `sort` + `dedup` | |
| `JOIN` | `join`, `lookup`, or searching both sourcetypes together then `stats by key` | The combined-search pattern scales better than `join` |
| Correlated time windows per row | `map` | One sub-search per row: fine for hundreds, slow for millions |
| `WITH RECURSIVE` (connected components) | **none** | SPL has no recursion. `trial_abuse.spl` groups by one shared value at a time. Rings chained only through different links can split; real teams iterate the search or use a graph store |
| DuckDB macros (`normalize_email`) | inline `eval`, or a Splunk macro | |

## Interview angle

*"Why keep both SQL and SPL?"* Warehouse SQL is right for batch scoring, backtests and evaluation over months of history. SPL is right for near-real-time alerting on raw logs, where the fraud and security operations teams already live. The logic is the same; what changes is what each language makes easy: SQL has recursion and set operations, SPL has streaming time windows over events.
