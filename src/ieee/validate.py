"""Validate the simulator's detection ideas on the real IEEE-CIS fraud dataset.

1. Download the competition data from Kaggle (needs a Kaggle account and accepting the competition rules):
     kaggle competitions download -c ieee-fraud-detection -p data/ieee && unzip data/ieee/*.zip -d data/ieee
2. Run:  python -m src.ieee.validate            (or: make ieee)

Loads train_transaction.csv + train_identity.csv into data/ieee.duckdb (only the columns used),
runs sql/ieee/signals.sql, and writes docs/ieee_validation.md: per-signal fraud lift and coverage,
plus how well the combined score ranks fraud.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "ieee"
REPORT = ROOT / "docs" / "ieee_validation.md"
TXN_COLS = ["TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "ProductCD", "card1", "addr1",
            "P_emaildomain", "R_emaildomain", "D1"]
ID_COLS = ["TransactionID", "DeviceType", "DeviceInfo"]
SIGNALS = {
    "sig_card_velocity": "Card velocity (3+ txns on the card in the previous hour)",
    "sig_micro_amount": "Micro amount (< $5)",
    "sig_anonymous_email": "Anonymous / privacy email domain",
    "sig_new_device_known_uid": "New device for a known customer",
    "sig_amount_spike": "Amount > 3x customer's earlier average",
    "sig_new_card": "Card first seen today (D1 = 0)",
    "sig_email_mismatch": "Buyer and recipient email domains differ",
}


def load(data_dir: Path, db_path: Path) -> duckdb.DuckDBPyConnection:
    txn, ident = data_dir / "train_transaction.csv", data_dir / "train_identity.csv"
    if not txn.exists():
        sys.exit(f"Missing {txn.relative_to(ROOT) if txn.is_relative_to(ROOT) else txn}. See the docstring for the download step.")
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(f"CREATE TABLE ieee_txn AS SELECT {', '.join(TXN_COLS)} FROM read_csv(?, header=true)", [str(txn)])
    if ident.exists():
        con.execute(f"CREATE TABLE ieee_identity AS SELECT {', '.join(ID_COLS)} FROM read_csv(?, header=true)", [str(ident)])
    else:
        con.execute("CREATE TABLE ieee_identity (TransactionID BIGINT, DeviceType VARCHAR, DeviceInfo VARCHAR)")
    return con


V2_SIGNALS = {
    "sig_uid_velocity": "v2: Customer velocity (3+ txns by the reconstructed customer in the previous hour)",
    "sig_privacy_email": "v2: Privacy email provider (list without anonymous.com)",
    "sig_has_recipient_email": "v2: Recipient email present",
}
HOLDOUT_SHARE = 0.4  # latest 40% of transactions by time: the fairest test for the v2 corrections


def signal_table(df: pd.DataFrame, signals: dict) -> pd.DataFrame:
    base = df.isFraud.mean()
    rows = []
    for col, label in signals.items():
        hit = df[col].astype(bool)
        rate = df.isFraud[hit].mean() if hit.any() else float("nan")
        rows.append({"signal": label, "share_of_txns": hit.mean(), "fraud_rate_when_present": rate,
                     "lift": rate / base if base else float("nan"),
                     "share_of_fraud_covered": hit[df.isFraud == 1].mean() if (df.isFraud == 1).any() else float("nan")})
    return pd.DataFrame(rows).sort_values("lift", ascending=False)


def ranking(df: pd.DataFrame, score: str) -> tuple[float, pd.DataFrame]:
    ranked = df.sort_values(score, ascending=False, kind="mergesort")
    n_fraud = df.isFraud.sum()
    top = []
    for share in (0.01, 0.05, 0.10):
        k = max(1, int(len(ranked) * share))
        caught = ranked.isFraud.iloc[:k].sum()
        top.append({"alert_budget": f"top {share:.0%} of txns", "precision": caught / k,
                    "recall": caught / n_fraud if n_fraud else float("nan")})
    ranks = df[score].rank(method="average")  # AUC via the rank-sum formula; ties get average rank
    pos = df.isFraud == 1
    auc = ((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum())
           if 0 < pos.sum() < len(df) else float("nan"))
    return auc, pd.DataFrame(top)


def diagnostics(con) -> dict:
    nan = float("nan")
    one = lambda sql: tuple(nan if v is None else v for v in con.execute(sql).fetchall()[0])  # NULL -> NaN
    card1_values, max_per_card1 = one("SELECT count(DISTINCT card1), max(n) FROM (SELECT card1, count(*) n FROM ieee_txn GROUP BY 1)")
    domain = {d: one(f"SELECT count(*), avg(isFraud) FROM ieee_txn WHERE P_emaildomain = '{d}'")
              for d in ("anonymous.com", "protonmail.com", "mail.com")}
    recip_same, recip_diff, no_recip = (one(f"SELECT avg(isFraud) FROM ieee_txn WHERE {w}")[0] for w in (
        "R_emaildomain IS NOT NULL AND R_emaildomain = P_emaildomain",
        "R_emaildomain IS NOT NULL AND R_emaildomain <> P_emaildomain", "R_emaildomain IS NULL"))
    return {"card1_values": card1_values, "max_per_card1": max_per_card1, "domain": domain,
            "recip_same": recip_same, "recip_diff": recip_diff, "no_recip": no_recip}


def evaluate(con) -> dict:
    con.execute((ROOT / "sql" / "ieee" / "signals.sql").read_text())
    df = con.execute("""SELECT s.*, c.risk_score, c.risk_score_v2, t.isFraud FROM ieee_signals s
                        JOIN ieee_scores c USING (TransactionID) JOIN ieee_txn t USING (TransactionID)
                        ORDER BY TransactionID""").df()  # fixed order: ties rank the same on every run
    holdout = df[df.TransactionDT >= df.TransactionDT.quantile(1 - HOLDOUT_SHARE)]
    auc, top = ranking(df, "risk_score")
    auc_v1_holdout, _ = ranking(holdout, "risk_score")
    auc_v2_holdout, top_v2 = ranking(holdout, "risk_score_v2")
    return {"n_txns": len(df), "base_rate": df.isFraud.mean(), "n_holdout": len(holdout),
            "holdout_base_rate": holdout.isFraud.mean(),
            "signals": signal_table(df, SIGNALS), "auc": auc, "top": top,
            "v2_signals_holdout": signal_table(holdout, V2_SIGNALS),
            "auc_v1_holdout": auc_v1_holdout, "auc_v2_holdout": auc_v2_holdout, "top_v2": top_v2,
            "diagnostics": diagnostics(con)}


def write_report(result: dict, path: Path = REPORT, source: str = "IEEE-CIS train set") -> str:
    fmt = {"share_of_txns": "{:.1%}", "fraud_rate_when_present": "{:.1%}", "lift": "{:.2f}x",
           "share_of_fraud_covered": "{:.1%}", "precision": "{:.1%}", "recall": "{:.1%}"}
    def table(df):
        cols = list(df.columns)
        lines = ["| " + " | ".join(c.replace("_", " ") for c in cols) + " |", "|" + "---|" * len(cols)]
        for r in df.itertuples(index=False):
            lines.append("| " + " | ".join(fmt.get(c, "{}").format(v) for c, v in zip(cols, r)) + " |")
        return "\n".join(lines)
    sig = result["signals"]
    strong = sig[sig.lift >= 1.5].signal.tolist()
    weak = sig[(sig.lift >= 1.0) & (sig.lift < 1.5)].signal.tolist()
    failed = sig[sig.lift < 1.0].signal.tolist()
    d = result["diagnostics"]
    dom = d["domain"]
    listed = lambda xs: ", ".join(f"*{x}*" for x in xs) or "none"
    text = f"""# Validating the detection ideas on real data (IEEE-CIS)

*Generated by `python -m src.ieee.validate` on {date.today().isoformat()} from the {source}:
{result['n_txns']:,} transactions, base fraud rate {result['base_rate']:.2%}. The data itself is not in this repo
(competition rules: non-commercial use, no redistribution); only these aggregate results are.*

The simulator's detectors are tuned on synthetic data, so this checks whether the **underlying signals**
carry information on real, labelled e-commerce fraud. Each idea is mapped to its closest proxy in the
anonymized IEEE-CIS columns (header of `sql/ieee/signals.sql`). Lift = fraud rate when the signal fires
÷ overall fraud rate; above 1 means the signal is informative.

## 1. First pass: signals as designed, before looking at the data

{table(sig)}

- **Transferred (lift ≥ 1.5x):** {listed(strong)}
- **Weak (1.0 to 1.5x):** {listed(weak)}
- **Did not transfer (below 1x):** {listed(failed)}

Combined score (fixed weights, not fitted): ROC AUC **{result['auc']:.3f}** (0.5 = random).

*The score is a sum of a few binary signals, so it takes only a handful of distinct values and a "top 1%"
cut falls inside large groups of tied transactions (ties are broken by transaction id). AUC, which handles
ties properly, is the number to trust; the precision/recall cut-offs are indicative.*

{table(result['top'])}

## 2. Why some signals didn't transfer

Diagnostics on the same data showed the misses were **mapping errors**, not evidence against the ideas:

- **`card1` is not one card.** It has {d['card1_values']:,} distinct values, one shared by up to
  {d['max_per_card1']:,} transactions, so "velocity on the same card1" measures popular card groups, not one
  card being hammered. Velocity per reconstructed customer is the right proxy.
- **`anonymous.com` is not a privacy service here.** It covers {dom['anonymous.com'][0]:,} transactions at a
  {dom['anonymous.com'][1]:.1%} fraud rate (below the base rate), so it behaves like a mainstream provider.
  Actual privacy-focused providers are rare but far riskier (protonmail.com {dom['protonmail.com'][1]:.0%},
  mail.com {dom['mail.com'][1]:.0%}).
- **The recipient-email risk is the reverse of the idea.** Fraud is {d['recip_same']:.1%} when a recipient email
  is present and *matches* the buyer's domain, {d['recip_diff']:.1%} when it differs, and {d['no_recip']:.1%} when
  there is none. Having a recipient email at all is the risk signal.

## 3. Second pass: corrected proxies, tested on the latest {HOLDOUT_SHARE:.0%} of transactions

The corrections were chosen after looking at the full data, so to limit self-deception they are reported
on the latest {HOLDOUT_SHARE:.0%} of transactions by time ({result['n_holdout']:,} transactions, base rate
{result['holdout_base_rate']:.2%}). That is the closest thing to fresh data this dataset allows, but it is
**not** a clean out-of-sample test, because the diagnostics above used every row.

{table(result['v2_signals_holdout'])}

On that holdout, the same fixed weights score ROC AUC **{result['auc_v1_holdout']:.3f}** with the first-pass
signals and **{result['auc_v2_holdout']:.3f}** with the corrected ones.

{table(result['top_v2'])}

## 4. What this means for the project

- The account-takeover idea (**new device on a known customer**) carries over directly and is the strongest
  first-pass signal; behavioural velocity carries over once it is measured per customer.
- Proxies matter as much as ideas: two of seven first-pass mappings pointed the wrong way because of what
  the anonymized columns actually mean. On a real team, the equivalent step is checking field definitions
  with data engineering before trusting a rule.
- A hand-weighted score of a few binary signals is a weak ranker on its own. These signals belong as features
  in a fitted model (with the dataset's C/D/V columns), with rules reserved for high-lift, explainable cases.
- Friendly fraud can't be tested here: `isFraud` is chargeback-based, so it mixes true and friendly fraud.
"""
    path.write_text(text)
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "ieee.duckdb")
    args = parser.parse_args()
    con = load(args.data, args.db)
    result = evaluate(con)
    print(write_report(result))


if __name__ == "__main__":
    main()
