# Lab Score

Еженедельный «отчёт зрелости» лаборатории одним письмом. Геймификация
мониторинга: видно, как растёт покрытие, и готовые цифры для докладов
(«218 → N детектов»).

## Метрики

- всего правил детектирования (Graylog Event Definitions);
- срабатываний за последние 7 дней + топ-5 правил недели;
- покрытие рунбуками HomeWiki (страницы правил с разделом «Реагирование»);
- уникальных техник MITRE ATT&CK в привязках правил;
- блокировки BlockBoard: активных, добавлено и снято за неделю;
- тикеты GLPI: открытые, закрытые за неделю, среднее время реакции (MTTR).

Результат — одно GELF-событие (`tool=labscore`, `ls_event=weekly`) в поток
**Lab Score**; правило «LABSCORE - Еженедельный отчёт зрелости» превращает его
в письмо (уведомление «Mail.ru Daily Digest»).

## Ежемесячный PDF-отчёт

`labscore_report.py` собирает отчёт зрелости за 30 дней в PDF (reportlab,
кириллица из DejaVu): динамика срабатываний, топ-10 правил, покрытие
рунбуками и MITRE, блокировки, тикеты. Готовый файл копируется в
`~/homewiki/data/reports/` и доступен из HomeWiki по адресу
`/reports/labscore-YYYY-MM.pdf` (после входа).

```bash
cp systemd/labscore-report.service systemd/labscore-report.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now labscore-report.timer   # 1-е число месяца, 09:11
```

## Установка (RED OS 8, пользователь redos)

```bash
mkdir -p ~/labscore
cp labscore.py ~/labscore/
printf 'LS_GRAYLOG_USER=admin\nLS_GRAYLOG_PASS=***\n' > ~/labscore/labscore.env
chmod 600 ~/labscore/labscore.env
cp systemd/labscore.service systemd/labscore.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now labscore.timer   # понедельник 09:23
```

Ручной прогон: `python3 ~/labscore/labscore.py` — печатает отчёт и шлёт событие.

## Настройка (env)

| ENV | Умолчание | Назначение |
|---|---|---|
| `LS_GRAYLOG_URL` | `http://127.0.0.1:9000` | API Graylog |
| `LS_GRAYLOG_USER/PASS` | admin/admin | учётка (в env-файле, не коммитить) |
| `LS_WIKI_DB` | `~/homewiki/data/homewiki.db` | база HomeWiki |
| `LS_BB_DB` | `~/blockboard/data/blockboard.db` | база BlockBoard (метрика блокировок) |
| `LS_GLPI_URL` | `http://192.168.1.149/glpi` | API GLPI (метрика тикетов) |
| `LS_GLPI_APP_TOKEN` / `LS_GLPI_USER_TOKEN` | пусто | токены GLPI API; пусто — метрика пропускается |
| `LS_GELF_HOST/PORT` | `127.0.0.1:12206` | вход «Homelab tools» |

## Тесты

```bash
python -m pytest tests/ -v
```
