"""IEEE-CIS validation pipeline, exercised on a small fake dataset with planted signals."""
from src.ieee.fixture import write_fixture
from src.ieee.validate import SIGNALS, evaluate, load, write_report


def run(tmp_path):
    data = write_fixture(tmp_path / "ieee")
    con = load(data, tmp_path / "ieee.duckdb")
    return evaluate(con)


def test_pipeline_measures_planted_signals(tmp_path):
    result = run(tmp_path)
    lifts = result["signals"].set_index("signal")["lift"]
    for planted in ["sig_card_velocity", "sig_micro_amount", "sig_anonymous_email", "sig_new_device_known_uid"]:
        assert lifts[SIGNALS[planted]] > 1.5, planted
    assert result["auc"] > 0.8


def test_report_renders(tmp_path):
    result = run(tmp_path)
    text = write_report(result, tmp_path / "report.md", source="test fixture")
    assert "ROC AUC" in text and "test fixture" in text


def test_signal_sql_never_reads_the_label():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "sql" / "ieee" / "signals.sql").read_text()
    code = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    assert "isfraud" not in code.lower()
