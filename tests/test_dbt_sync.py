"""The dbt port is generated from sql/; this fails if someone edits sql/ and forgets to regenerate."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dbt_models_in_sync_with_sql():
    result = subprocess.run([sys.executable, "dbt/sync_from_sql.py", "--check"], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_dbt_models_never_reference_ground_truth():
    for path in (ROOT / "dbt" / "models").rglob("*.sql"):
        assert "ground_truth" not in path.read_text(), path.name
    sources = (ROOT / "dbt" / "models" / "sources.yml").read_text()
    assert "- name: ground_truth" not in sources
