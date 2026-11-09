import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from labscore import compose


def test_compose_basic():
    text, m = compose(257, 42, [("CANARY - Касание", 10)], 257, 200, 100)
    assert m["ls_rules"] == 257
    assert m["ls_alerts_week"] == 42
    assert m["ls_wiki_pct"] == round(100 * 200 / 257)
    assert m["ls_techniques"] == 100
    assert "CANARY - Касание — 10" in text
    assert "200 из 257" in text


def test_compose_empty_week():
    text, m = compose(10, 0, [], 10, 0, 0)
    assert "тишина" in text
    assert m["ls_wiki_pct"] == 0


def test_compose_zero_rules_no_division_by_zero():
    text, m = compose(0, 0, [], 0, 0, 0)
    assert m["ls_wiki_pct"] == 0
