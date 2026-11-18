"""The Splunk log export: one JSON-lines file per sourcetype, timestamps present, truth kept separate."""
import json

from splunk.export_logs import EVENTS, export


def test_export_writes_every_sourcetype(small_db, tmp_path):
    counts = export(tmp_path, con=small_db)
    assert set(counts) == set(EVENTS)
    for sourcetype, n in counts.items():
        path = tmp_path / f"{sourcetype.split(':')[1]}.json"
        lines = path.read_text().splitlines()
        assert len(lines) == n > 0
        first = json.loads(lines[0])
        assert "ts" in first and first["ts"][:2] == "20"


def test_truth_is_a_separate_lookup_not_an_event_stream(small_db, tmp_path):
    export(tmp_path, con=small_db)
    assert (tmp_path / "ground_truth.csv").exists()
    for path in tmp_path.glob("*.json"):
        assert "campaign_id" not in path.read_text()
