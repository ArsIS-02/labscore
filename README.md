# Lab Score

Еженедельный «отчёт зрелости» лаборатории одним письмом. Геймификация
мониторинга: видно, как растёт покрытие, и готовые цифры для докладов
(«218 → N детектов»).

## Метрики

- всего правил детектирования (Graylog Event Definitions);
- срабатываний за последние 7 дней + топ-5 правил недели;
- покрытие рунбуками HomeWiki (страницы правил с разделом «Реагирование»);
- уникальных техник MITRE ATT&CK в привязках правил.

Результат — одно GELF-событие (`tool=labscore`, `ls_event=weekly`) в поток
**Lab Score**; правило «LABSCORE - Еженедельный отчёт зрелости» превращает его
в письмо (уведомление «Mail.ru Daily Digest»).

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
| `LS_GELF_HOST/PORT` | `127.0.0.1:12206` | вход «Homelab tools» |

## Тесты

```bash
python -m pytest tests/ -v
```
