#!/usr/bin/env python3
"""Lab Score — ежемесячный PDF-отчёт зрелости лаборатории.

Собирает метрики за 30 дней (Graylog, HomeWiki, BlockBoard, GLPI),
рисует PDF (reportlab + DejaVu) и кладёт его в ~/labscore/reports/
и в статику HomeWiki (/static/reports/) для просмотра из браузера.

ENV: те же, что у labscore.py, плюс LS_REPORTS_DIR (~/labscore/reports),
     LS_WIKI_STATIC (~/homewiki/app/static).
"""
import json
import os
import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle)
from reportlab.lib.styles import ParagraphStyle

from labscore import api, wiki_metrics, blockboard_metrics, glpi_metrics, send_gelf

DAYS = 30
REPORTS = Path(os.environ.get("LS_REPORTS_DIR", "~/labscore/reports")).expanduser()
WIKI_REPORTS = Path(os.environ.get("LS_WIKI_REPORTS",
                                    "~/homewiki/data/reports")).expanduser()
FONTS = "/usr/share/fonts/dejavu-sans-fonts"


def graylog_month():
    """Срабатывания за 30 дней с постраничным обходом."""
    since = time.time() - DAYS * 86400
    total_rules = api("/api/events/definitions?page=1&per_page=1").get("total", 0)
    alerts, top, page = 0, {}, 1
    while page <= 10:                       # защита от бесконечности
        r = api("/api/events/search", {"query": "", "page": page, "per_page": 500})
        evs = r.get("events", [])
        if not evs:
            break
        stop = False
        for e in evs:
            ev = e.get("event", {})
            try:
                ts = time.mktime(time.strptime(ev["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                continue
            if ts < since:
                stop = True
                break
            alerts += 1
            t = ev.get("message", "?")
            top[t] = top.get(t, 0) + 1
        if stop:
            break
        page += 1
    return total_rules, alerts, sorted(top.items(), key=lambda x: -x[1])[:10]


def build_pdf(path, month_name, data):
    pdfmetrics.registerFont(TTFont("DV", f"{FONTS}/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DV-B", f"{FONTS}/DejaVuSans-Bold.ttf"))
    h1 = ParagraphStyle("h1", fontName="DV-B", fontSize=18, spaceAfter=6*mm)
    h2 = ParagraphStyle("h2", fontName="DV-B", fontSize=13, spaceBefore=6*mm,
                        spaceAfter=2*mm, textColor=colors.HexColor("#c2410c"))
    p = ParagraphStyle("p", fontName="DV", fontSize=10, leading=14)
    cell = ParagraphStyle("cell", fontName="DV", fontSize=9, leading=12)

    story = [Paragraph(f"Отчёт зрелости лаборатории — {month_name}", h1),
             Paragraph(f"Период: {DAYS} дней · сформировано "
                       + time.strftime("%d.%m.%Y %H:%M"), p), Spacer(1, 4*mm)]

    story.append(Paragraph("Ключевые метрики", h2))
    rows = [["Метрика", "Значение"]]
    for k, v in data["metrics"]:
        rows.append([k, str(v)])
    t = Table(rows, colWidths=[110*mm, 60*mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "DV-B"), ("FONTNAME", (0, 1), (-1, -1), "DV"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(Paragraph("Топ-10 правил за период", h2))
    top = data["top"]
    if top:
        mx = top[0][1]
        rows = [["Правило", "Срабатывания", ""]]
        for name, n in top:
            rows.append([Paragraph(name, cell), str(n), "█" * max(1, round(30 * n / mx))])
        t = Table(rows, colWidths=[95*mm, 22*mm, 53*mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "DV-B"), ("FONTNAME", (0, 1), (-1, -1), "DV"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("TEXTCOLOR", (2, 1), (2, -1), colors.HexColor("#ea580c")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("За период срабатываний не было — тишина.", p))

    story.append(Spacer(1, 8*mm))
    story.append(Paragraph(
        "Сформировано автоматически: Lab Score × Graylog × HomeWiki × BlockBoard × GLPI",
        ParagraphStyle("foot", fontName="DV", fontSize=8,
                       textColor=colors.HexColor("#6b7280"))))

    SimpleDocTemplate(str(path), pagesize=A4, title=f"Lab Score {month_name}",
                      leftMargin=20*mm, rightMargin=20*mm,
                      topMargin=20*mm, bottomMargin=20*mm).build(story)


def main():
    since = time.time() - DAYS * 86400
    rules_total, alerts, top = graylog_month()
    wiki_rules, covered, techs = wiki_metrics()
    bb_active, bb_added, bb_removed = blockboard_metrics(since)
    glpi = glpi_metrics(since)

    metrics = [("Правил детектирования", rules_total),
               (f"Срабатываний за {DAYS} дней", alerts),
               (f"Рунбуки HomeWiki", f"{covered} из {wiki_rules} "
                f"({round(100 * covered / wiki_rules) if wiki_rules else 0}%)"),
               ("Техник MITRE ATT&CK", techs),
               ("Блокировки BlockBoard", f"{bb_active} активных (+{bb_added} / −{bb_removed})")]
    if glpi:
        mttr = f", MTTR {glpi['mttr_h']} ч" if glpi["mttr_h"] is not None else ""
        metrics.append(("Тикеты GLPI", f"{glpi['open']} открытых из {glpi['total']}, "
                        f"закрыто за период: {glpi['closed_week']}{mttr}"))

    REPORTS.mkdir(parents=True, exist_ok=True)
    name = time.strftime("labscore-%Y-%m")
    pdf = REPORTS / f"{name}.pdf"
    month_name = time.strftime("%m.%Y")
    build_pdf(pdf, month_name, {"metrics": metrics, "top": top})

    link = ""
    try:
        WIKI_REPORTS.mkdir(parents=True, exist_ok=True)
        target = WIKI_REPORTS / pdf.name
        target.write_bytes(pdf.read_bytes())
        link = f"homewiki /reports/{pdf.name}"
    except OSError as e:
        print("wiki copy failed:", e)

    send_gelf(f"labscore: месячный PDF-отчёт {month_name} готов", {
        "tool": "labscore", "homelab_app": "labscore", "ls_event": "monthly_pdf",
        "ls_pdf": str(pdf), "ls_wiki_link": link, "ls_alerts_month": alerts,
        "ls_rules": rules_total})
    print(pdf)


if __name__ == "__main__":
    main()
