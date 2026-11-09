#!/usr/bin/env python3
"""Lab Score — еженедельный отчёт зрелости лаборатории.

Считает метрики (правила Graylog, срабатывания за неделю, покрытие HomeWiki,
техники MITRE) и шлёт одно GELF-событие — Graylog превращает его в письмо.

ENV: LS_GRAYLOG_URL (по умолчанию http://127.0.0.1:9000), LS_GRAYLOG_USER/PASS,
     LS_WIKI_DB (~/homewiki/data/homewiki.db), LS_GELF_HOST/PORT (127.0.0.1:12206),
     LS_BB_DB (~/blockboard/data/blockboard.db)
"""
import base64, gzip, json, os, socket, sqlite3, ssl, time, urllib.request
from pathlib import Path

GRAYLOG = os.environ.get("LS_GRAYLOG_URL", "http://127.0.0.1:9000").rstrip("/")
USER = os.environ.get("LS_GRAYLOG_USER", "admin")
PASS = os.environ.get("LS_GRAYLOG_PASS", "admin")
WIKI_DB = Path(os.environ.get("LS_WIKI_DB", "~/homewiki/data/homewiki.db")).expanduser()
BB_DB = Path(os.environ.get("LS_BB_DB", "~/blockboard/data/blockboard.db")).expanduser()
GELF_HOST = os.environ.get("LS_GELF_HOST", "127.0.0.1")
GELF_PORT = int(os.environ.get("LS_GELF_PORT", "12206"))
GLPI = os.environ.get("LS_GLPI_URL", "http://192.168.1.149/glpi").rstrip("/")
GLPI_APP = os.environ.get("LS_GLPI_APP_TOKEN", "")
GLPI_USER = os.environ.get("LS_GLPI_USER_TOKEN", "")
HOST = socket.gethostname()

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def api(path, body=None):
    req = urllib.request.Request(GRAYLOG + path,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json",
                                          "X-Requested-By": "labscore"},
                                 method="POST" if body else "GET")
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode())
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        return json.load(r)


def graylog_metrics():
    rules_total = api("/api/events/definitions?page=1&per_page=1").get("total", 0)
    events = api("/api/events/search", {"query": "", "page": 1, "per_page": 500})
    week_ago = time.time() - 7 * 86400
    alerts, top = 0, {}
    for e in events.get("events", []):
        ev = e.get("event", {})
        try:
            ts = time.mktime(time.strptime(ev["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if ts >= week_ago:
            alerts += 1
            t = ev.get("message", "?")
            top[t] = top.get(t, 0) + 1
    return rules_total, alerts, sorted(top.items(), key=lambda x: -x[1])[:5]


def wiki_metrics():
    con = sqlite3.connect(WIKI_DB)
    rules = con.execute("SELECT techniques, body FROM pages WHERE type='rule'").fetchall()
    con.close()
    covered = sum(1 for t, b in rules if b and "## Реагирование" in b)
    techs = set()
    for t, _ in rules:
        try:
            techs.update(json.loads(t))
        except Exception:
            pass
    return len(rules), covered, len(techs)


def blockboard_metrics(week_ago):
    """Блокировки BlockBoard: активные, добавленные и снятые за неделю."""
    if not BB_DB.exists():
        return 0, 0, 0
    con = sqlite3.connect(BB_DB)
    try:
        active = con.execute("SELECT COUNT(*) FROM blocks WHERE active=1").fetchone()[0]
        added = con.execute("SELECT COUNT(*) FROM blocks WHERE created>=?", (week_ago,)).fetchone()[0]
        removed = con.execute(
            "SELECT COUNT(*) FROM history WHERE ts>=? AND action IN ('unblock','expire')",
            (week_ago,)).fetchone()[0]
    finally:
        con.close()
    return active, added, removed


def glpi_metrics(week_ago):
    """SOC-метрики по тикетам GLPI: открытые, закрытые за неделю, MTTR.

    MTTD у нас около нуля (тикет создаётся автоматически через TicketBridge
    в ту же минуту, что и алерт), поэтому считаем только MTTR — среднее
    время от создания до закрытия тикета. GLPI недоступен → None.
    """
    if not (GLPI_APP and GLPI_USER):
        return None
    base = GLPI + "/apirest.php"
    hdr = {"Content-Type": "application/json", "App-Token": GLPI_APP}
    try:
        req = urllib.request.Request(base + "/initSession",
                                     headers={**hdr, "Authorization": "user_token " + GLPI_USER})
        with urllib.request.urlopen(req, context=CTX, timeout=15) as r:
            hdr["Session-Token"] = json.load(r)["session_token"]
        req = urllib.request.Request(base + "/Ticket?range=0-999&order=DESC", headers=hdr)
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            tickets = json.load(r)
    except Exception:
        return None
    finally:
        if "Session-Token" in hdr:
            try:
                urllib.request.urlopen(urllib.request.Request(base + "/killSession",
                                       headers=hdr), context=CTX, timeout=10)
            except Exception:
                pass

    def ts(s):
        try:
            return time.mktime(time.strptime((s or "")[:19], "%Y-%m-%d %H:%M:%S"))
        except Exception:
            return None

    open_cnt, closed_week, durations = 0, 0, []
    for t in tickets:
        c = ts(t.get("closedate"))
        if c:
            if c >= week_ago:
                closed_week += 1
                cr = ts(t.get("date_creation"))
                if cr:
                    durations.append(c - cr)
        else:
            open_cnt += 1
    return {"total": len(tickets), "open": open_cnt, "closed_week": closed_week,
            "mttr_h": round(sum(durations) / 3600 / len(durations), 1) if durations else None}


def compose(rules_total, alerts, top, wiki_rules, covered, techs, bb_active, bb_added, bb_removed,
            glpi=None):
    """Текст отчёта и словарь метрик (отдельно для тестов)."""
    pct = round(100 * covered / wiki_rules) if wiki_rules else 0
    lines = [
        f"Правил детектирования: {rules_total}",
        f"Срабатываний за неделю: {alerts}",
        f"Рунбуки HomeWiki: {covered} из {wiki_rules} правил ({pct}%)",
        f"Техник MITRE ATT&CK в привязках: {techs}",
        f"Блокировки BlockBoard: {bb_active} активных (+{bb_added} / −{bb_removed} за неделю)",
    ]
    if glpi:
        line = (f"Тикеты GLPI: {glpi['open']} открытых из {glpi['total']}, "
                f"закрыто за неделю: {glpi['closed_week']}")
        if glpi["mttr_h"] is not None:
            line += f", MTTR {glpi['mttr_h']} ч"
        line += " (заведение автоматическое: MTTD < 1 мин)"
        lines.append(line)
    lines.append("Топ недели: " + ("; ".join(f"{t} — {n}" for t, n in top) if top else "тишина"))
    metrics = {"ls_rules": rules_total, "ls_alerts_week": alerts,
               "ls_wiki_rules": wiki_rules, "ls_wiki_covered": covered,
               "ls_wiki_pct": pct, "ls_techniques": techs,
               "ls_bb_active": bb_active, "ls_bb_added_week": bb_added,
               "ls_bb_removed_week": bb_removed}
    if glpi:
        metrics.update({"ls_glpi_total": glpi["total"], "ls_glpi_open": glpi["open"],
                        "ls_glpi_closed_week": glpi["closed_week"]})
        if glpi["mttr_h"] is not None:
            metrics["ls_glpi_mttr_h"] = glpi["mttr_h"]
    return "\n".join(lines), metrics


def send_gelf(short, fields):
    msg = {"version": "1.1", "host": HOST, "short_message": short,
           "timestamp": time.time(), "level": 5}
    msg.update({f"_{k}": v for k, v in fields.items()})
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(gzip.compress(json.dumps(msg).encode()), (GELF_HOST, GELF_PORT))
    sock.close()


def main():
    week_ago = time.time() - 7 * 86400
    rules_total, alerts, top = graylog_metrics()
    wiki_rules, covered, techs = wiki_metrics()
    bb_active, bb_added, bb_removed = blockboard_metrics(week_ago)
    glpi = glpi_metrics(week_ago)
    text, metrics = compose(rules_total, alerts, top, wiki_rules, covered, techs,
                            bb_active, bb_added, bb_removed, glpi)
    send_gelf("labscore: еженедельный отчёт зрелости", {
        **metrics, "tool": "labscore", "homelab_app": "labscore",
        "ls_event": "weekly", "ls_text": text,
    })
    print(text)


if __name__ == "__main__":
    main()
