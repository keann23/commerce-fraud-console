"""Weekly intel brief: metrics, deterministic template, and the Claude writer's request and fallback."""
from types import SimpleNamespace

from src.intel_brief import (MODEL, build_facts, claude_brief, complete_weeks, template_brief,
                             weekly_metrics)


def latest_facts(con):
    return build_facts(con, complete_weeks(weekly_metrics(con))[-1])


def test_weekly_metrics_cover_the_window(small_db):
    df = weekly_metrics(small_db)
    assert len(df) >= 17  # ~120 days
    assert df.approved_usd.notna().all()


def test_template_brief_is_deterministic_and_grounded(small_db):
    facts = latest_facts(small_db)
    a, b = template_brief(facts), template_brief(facts)
    assert a == b
    assert facts["week_starting"] in a and "synthetic" in a
    assert ".0 alerts" not in a  # counts render as integers


class FakeMessages:
    def __init__(self, stop_reason="end_turn", text="# Brief\nAll good."):
        self.calls, self.stop_reason, self.text = [], stop_reason, text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)])


def fake_client(messages):
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def test_claude_brief_sends_only_facts_with_fallbacks(small_db):
    facts = latest_facts(small_db)
    messages = FakeMessages()
    out = claude_brief(facts, client=fake_client(messages))
    assert out.startswith("# Brief")
    call = messages.calls[0]
    assert call["model"] == MODEL
    assert call["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["betas"]
    assert "thinking" not in call  # Opus 5.5 thinks adaptively by default; disabling it is a 400
    sent = call["messages"][0]["content"]
    assert facts["week_starting"] in sent and "email" not in sent  # aggregate facts only, no customer PII


def test_claude_refusal_falls_back_to_template(small_db):
    facts = latest_facts(small_db)
    out = claude_brief(facts, client=fake_client(FakeMessages(stop_reason="refusal", text="")))
    assert out == template_brief(facts)
