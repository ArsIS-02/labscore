import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from labscore import compose, blockboard_metrics


def test_compose_basic():
    text, m = compose(257, 42, [("CANARY - Касание", 10)], 257, 200, 100, 5, 3, 1)
    assert m["ls_rules"] == 257
    assert m["ls_alerts_week"] == 42
    assert m["ls_wiki_pct"] == round(100 * 200 / 257)
    assert m["ls_techniques"] == 100
    assert m["ls_bb_active"] == 5
    assert m["ls_bb_added_week"] == 3
    assert m["ls_bb_removed_week"] == 1
    assert "CANARY - Касание — 10" in text
    assert "200 из 257" in text
    assert "5 активных (+3 / −1" in text


def test_compose_empty_week():
    text, m = compose(10, 0, [], 10, 0, 0, 0, 0, 0)
    assert "тишина" in text
    assert m["ls_wiki_pct"] == 0
    assert "0 активных" in text


def test_compose_zero_rules_no_division_by_zero():
    text, m = compose(0, 0, [], 0, 0, 0, 0, 0, 0)
    assert m["ls_wiki_pct"] == 0


def test_blockboard_metrics_missing_db(tmp_path, monkeypatch):
    import labscore
    monkeypatch.setattr(labscore, "BB_DB", tmp_path / "nope.db")
    assert blockboard_metrics(time.time() - 7 * 86400) == (0, 0, 0)


def test_blockboard_metrics_counts(tmp_path, monkeypatch):
    import sqlite3, labscore
    db = tmp_path / "blockboard.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE blocks(id INTEGER PRIMARY KEY, indicator TEXT, itype TEXT,"
                " reason TEXT DEFAULT '', source TEXT DEFAULT '', created REAL, expires REAL,"
                " active INTEGER DEFAULT 1, status TEXT DEFAULT '', executor_msg TEXT DEFAULT '')")
    con.execute("CREATE TABLE history(id INTEGER PRIMARY KEY, ts REAL, action TEXT,"
                " indicator TEXT, actor TEXT DEFAULT '', detail TEXT DEFAULT '')")
    now = time.time()
    con.executemany("INSERT INTO blocks(indicator, itype, created, active) VALUES(?,?,?,?)",
                    [("1.1.1.1", "ip", now - 86400, 1),
                     ("2.2.2.2", "ip", now - 86400, 1),
                     ("3.3.3.3", "ip", now - 30 * 86400, 1),
                     ("4.4.4.4", "ip", now - 86400, 0)])
    con.executemany("INSERT INTO history(ts, action, indicator) VALUES(?,?,?)",
                    [(now - 3600, "unblock", "4.4.4.4"),
                     (now - 7200, "expire", "5.5.5.5"),
                     (now - 30 * 86400, "unblock", "6.6.6.6")])
    con.commit(); con.close()
    monkeypatch.setattr(labscore, "BB_DB", db)
    active, added, removed = blockboard_metrics(now - 7 * 86400)
    assert active == 3 and added == 3 and removed == 2


def test_compose_with_glpi():
    g = {"total": 10, "open": 3, "closed_week": 5, "mttr_h": 2.5}
    text, m = compose(10, 1, [], 10, 5, 3, 0, 0, 0, g)
    assert "Тикеты GLPI: 3 открытых из 10" in text
    assert "MTTR 2.5 ч" in text and "MTTD < 1 мин" in text
    assert m["ls_glpi_open"] == 3 and m["ls_glpi_mttr_h"] == 2.5


def test_compose_glpi_no_mttr():
    g = {"total": 2, "open": 2, "closed_week": 0, "mttr_h": None}
    text, m = compose(10, 1, [], 10, 5, 3, 0, 0, 0, g)
    assert "MTTR" not in text and "ls_glpi_mttr_h" not in m
