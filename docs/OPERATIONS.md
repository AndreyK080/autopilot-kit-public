# Эксплуатация

> Оригинальный Autopilot — [nick-vels/skills](https://github.com/nick-vels/skills) (MIT, © Nick Vels): kit его не меняет и не содержит. Отличия — [DIFF_FROM_UPSTREAM.md](DIFF_FROM_UPSTREAM.md), приводы — [DRIVES.md](DRIVES.md).

Все команды выполняются из папки `autopilot-kit`: `python -m kit <команда>`.

| Команда | Что делает |
|---|---|
| `install` | Ставит Autopilot по `kit/data/upstream.pin` в `~/.claude/skills/autopilot` и `~/.agents/skills/autopilot`, пишет `~/.autopilot-kit/upstream.lock.json`; делает копию `autopilot-stage` для сессий этапов; копирует навыки kit (`autopilot-roles`, `autopilot-setup`, `autopilot-init`, `autopilot-program`; прежняя версия — в `~/.autopilot-kit/backups/`); пишет `resolved.json`, `models.json`, `bin/gate.py`, `bin/program.py` и агентов `~/.claude/agents/autopilot-*.md` из текущего профиля. Повторный запуск ничего не ломает |
| `status` | Коммит из lock, совпадение хешей в каждой цели, HEAD на GitHub, есть ли обновление. Код 1 — если что-то не совпало |
| `update [--yes]` | Берёт HEAD с GitHub, показывает `git log` по `skills/autopilot` и список изменённых файлов, проверяет швы (красные — отказ даже с `--yes`), спрашивает `y/N`, ставит, обновляет pin и lock |
| `check-update` | Сравнивает файлы `skills/autopilot` на GitHub с lock. Код 0 — обновлений нет (сдвиг HEAD из-за других навыков автора не в счёт), 10 — есть: коммиты и изменённые файлы, 1 — ошибка |
| `trial [--commit SHA]` | Dev: ставит версию-кандидата (по умолчанию HEAD) в `~/.autopilot-kit/trial/home` — полная установка с копией вашего `profile.toml` — и проверяет швы; отчёт `~/.autopilot-kit/trial/report.md`. Прод не меняется. Код 1 — есть красные швы |
| `doctor` | Таблица OK/WARN/FAIL: Python, git, Autopilot и хеши, навыки, `resolved.json`, агенты, API-ключи в окружении (FAIL), вход Codex (`codex login status`), вход claude CLI (WARN) |
| `dashboard [--project П]… [--port N] [--no-open] [--foreground]` | Пульт всех программ (D43): поднимает фоновый сервер на `127.0.0.1:8699` и открывает страницу. Что требует внимания, трек этапов, гейт, версия ядра против GitHub, автоматика, задачи владельца. Страница обновляется каждые 15 с, GitHub и `doctor` — раз в 30 минут. Только чтение; находит программы вне реестра (папка и подпапка рядом с известными). После перезагрузки компьютера запустите снова; повторный запуск заменяет сервер старой версии. Журнал: `~/.autopilot-kit/dashboard.log` |
| `profile set [--preset p] [--role роль=уровень:усилие]… [--drive d] [--dry-run]` | Пишет `~/.autopilot-kit/profile.toml`, пересчитывает `resolved.json`, пересоздаёт агентов. `--drive claude\|claude-gate\|codex` явно фиксирует привод (D49), переопределяя определение по окружению |
| `project init --template <имя> --path <папка проекта>` | Копирует шаблон проекта; `*.kit-new` для существующих файлов, слияние `settings.json`. Без `--path` — текущая папка, то есть папка kit |
| `/autopilot-init` (навык, не команда) | В чате, открытом в папке проекта: читает документы, ставит шаблон `generic`, вписывает команды гейта и правила стека. Находит kit по `~/.autopilot-kit/kit_path` |
| `/autopilot-program` (навык, не команда) | В чате, открытом в папке проекта: ведёт программу из нескольких прогонов; без `.autopilot-kit/project.toml` сам настраивает проект, как `/autopilot-init` (D39); вопросы пачкой в начале, этап = новая сессия, проверка сдачи `program.py check`, отчёт программы. Без аргументов — продолжает по `.autopilot/program.json` |
| `python ~/.autopilot-kit/bin/program.py <команда>` | Состояние программы для навыка: `init`, `stage add|set`, `ask`, `answer`, `start [--adopt]`, `prompt`, `bind`, `check [--record]`, `next`, `status`, `report`, `track` (строка хода для чата), `page` и `serve` (дашборд программы и его постоянный фоновый сервер, D25), `limits` (решение по лимитам подписки: go / pause / insure), `pause [--reason limit\|owner\|other --text]` / `resume` (снимает паузу, задачи «ожидание паузы» и флаг ожидания этапа, D46), `why-paused` (что держит дашборд «ждущим» и чем снять), `stage unwait`, `wake-prompt` (текст разовой задачи продолжения), `prompt --after-signal`, `plan-template` / `plan-check` / `plan-load` (план программы, D23), `stage continue` (продолжение частично сданного этапа). Один прогон в папке за раз |
| `uninstall [--yes]` | Удаляет то, что поставил kit (по lock и маркеру в файлах); изменённое вами оставляет; прежние файлы агентов возвращает из `.bak`. `profile.toml` остаётся |

## Где что лежит

| Путь | Назначение |
|---|---|
| `~/.claude/skills/autopilot`, `~/.agents/skills/autopilot` | оригинальный Autopilot (Claude Code / Codex) |
| `~/.claude/skills/autopilot-roles`, `autopilot-setup`, то же в `~/.agents/skills` | навыки kit |
| `~/.claude/agents/autopilot-*.md` | агенты ролей для Claude Code (модель и усилие из профиля) |
| `~/.autopilot-kit/upstream.lock.json` | какой коммит Autopilot и какие хеши файлов поставлены |
| `~/.autopilot-kit/profile.toml` | ваш профиль ролей |
| `~/.autopilot-kit/resolved.json`, `models.json` | вендор → роль → модель, усилие; таблица моделей |
| `~/.autopilot-kit/bin/gate.py` | гейт качества |
| `~/.autopilot-kit/bin/program.py`, `program_page.html`, `program_plan.md` | состояние программы прогонов (навык `/autopilot-program`), шаблон дашборда и шаблон плана программы |
| `~/.claude/skills/autopilot-stage` | копия Autopilot без `disable-model-invocation` для сессий этапов (D19); пересоздаётся `install`/`update`, маркер `.autopilot-kit-generated` |
| `~/.autopilot-kit/trial/` | dev-песочница `trial`: `home/` (установка кандидата) и `report.md`; пересоздаётся при каждом `trial`, удаляется `uninstall` |
| `~/.autopilot-kit/kit_path` | путь к репозиторию kit (пишет `install`; нужен навыку `/autopilot-init`) |
| `<проект>/.autopilot-kit/project.toml` | команды гейта проекта; `profile.toml` рядом — необязательные правки ролей (только Codex) |
| `<проект>/.autopilot/state.js` | состояние прогона Autopilot; гейт читает из него только поле `waiting`, `program.py` — итог прогона |
| `<проект>/.autopilot/program.json`, `PROGRAM.md` | программа прогонов: этапы, вопросы и ответы владельца (источник истины) и её вид |
| `<проект>/.autopilot/program.html`, `program.js`, `program-serve.pid`, `program-serve.log` | дашборд программы, его данные и фоновый сервер (`program.py serve`, порт 8700–8899 от пути проекта); всё в `.autopilot/.gitignore` |
| `<проект>/.autopilot-kit/gate_state.json`, `last_host` | служебные файлы |

Файлы пользователя вне репозитория kit меняются только с копией `<файл>.bak-<UTC>`.
Переменная `AUTOPILOT_KIT_HOME` переопределяет домашний каталог (нужна тестам).

## Откат Autopilot на прошлую версию

1. Найдите нужный коммит: `git log` в клоне `https://github.com/nick-vels/skills` или поле `commit` в прежнем lock.
2. Впишите его хеш одной строкой в `kit/data/upstream.pin`.
3. `python -m kit install` — файлы заменятся, если вы их не правили (иначе `LOCAL_CHANGES`), lock обновится.

## Типичные ситуации

- **`LOCAL_CHANGES`**: в папке Autopilot есть файлы, отличные от lock. Верните их или удалите папку цели и повторите `install`.
- **Агенты не найдены в чате** (`Agent type not found`): запустите `install` и откройте новый чат.
- **Смена тарифа или моделей**: `/autopilot-setup` или `profile set`; изменения вступают в силу в новом чате.
- **Обновление таблицы моделей** (`kit/data/models.json`): редактируется в репозитории kit, затем `install`.
- **Еженедельная проверка**: задача приложения «Autopilot: проверка обновлений» (понедельник, 10:00, файл `~/.claude/scheduled-tasks/autopilot-weekly-update-check/SKILL.md`) выполняет `check-update`; при новой версии — `trial` (швы), проверку занятости и, если швы зелёные и ни один этап не идёт, `update --yes` + `doctor` (D42), иначе — уведомление с причиной.
- **Продолжение после лимита**: разовая задача приложения `autopilot-program-resume-<папка проекта>` (ставит оркестратор, D22) будит чат этапа после сброса лимита. Сработавшая задача сама отключается; список — раздел «Scheduled» боковой панели.
