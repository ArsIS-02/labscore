#!/usr/bin/env python3
"""Lab Score — еженедельный отчёт зрелости лаборатории.

Считает метрики (правила Graylog, срабатывания за неделю, покрытие HomeWiki,
техники MITRE) и шлёт одно GELF-событие — Graylog превращает его в письмо.

ENV: LS_GRAYLOG_URL (по умолчанию http://127.0.0.1:9000), LS_GRAYLOG_USER/PASS,
     LS_WIKI_DB (~/homewiki/data/homewiki.db), LS_GELF_HOST/PORT (127.0.0.1:12206)
"""
import base64, gzip, json, os, socket, sqlite3, ssl, time, urllib.request
from pathlib import Path

GRAYLOG = os.environ.get("LS_GRAYLOG_URL", "http://127.0.0.1:9000").rstrip("/")
USER = os.environ.get("LS_GRAYLOG_USER", "admin")
PASS = os.environ.get("LS_GRAYLOG_PASS", "admin")
WIKI_DB = Path(os.environ.get("LS_WIKI_DB", "~/homewiki/data/homewiki.db")).expanduser()
GELF_HOST = os.environ.get("LS_GELF_HOST", "127.0.0.1")
GELF_PORT = int(os.environ.get("LS_GELF_PORT", "12206"))
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


def compose(rules_total, alerts, top, wiki_rules, covered, techs):
    """Текст отчёта и словарь метрик (отдельно для тестов)."""
    pct = round(100 * covered / wiki_rules) if wiki_rules else 0
    lines = [
        f"Правил детектирования: {rules_total}",
        f"Срабатываний за неделю: {alerts}",
        f"Рунбуки HomeWiki: {covered} из {wiki_rules} правил ({pct}%)",
        f"Техник MITRE ATT&CK в привязках: {techs}",
        "Топ недели: " + ("; ".join(f"{t} — {n}" for t, n in top) if top else "тишина"),
    ]
    metrics = {"ls_rules": rules_total, "ls_alerts_week": alerts,
               "ls_wiki_rules": wiki_rules, "ls_wiki_covered": covered,
               "ls_wiki_pct": pct, "ls_techniques": techs}
    return "\n".join(lines), metrics


def send_gelf(short, fields):
    msg = {"version": "1.1", "host": HOST, "short_message": short,
           "timestamp": time.time(), "level": 5}
    msg.update({f"_{k}": v for k, v in fields.items()})
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(gzip.compress(json.dumps(msg).encode()), (GELF_HOST, GELF_PORT))
    sock.close()


def main():
    rules_total, alerts, top = graylog_metrics()
    wiki_rules, covered, techs = wiki_metrics()
    text, metrics = compose(rules_total, alerts, top, wiki_rules, covered, techs)
    send_gelf("labscore: еженедельный отчёт зрелости", {
        **metrics, "tool": "labscore", "homelab_app": "labscore",
        "ls_event": "weekly", "ls_text": text,
    })
    print(text)


if __name__ == "__main__":
    main()
