# Спайки осуществимости

> Оригинальный Autopilot — [nick-vels/skills](https://github.com/nick-vels/skills) (MIT, © Nick Vels): kit его не меняет; копия лежит в `vendor/autopilot`. Отличия — [DIFF_FROM_UPSTREAM.md](DIFF_FROM_UPSTREAM.md), приводы — [DRIVES.md](DRIVES.md).

| Спайк | Что делали | Факт | Вывод |
|---|---|---|---|
| S1 | Проверили окружение Claude Code (21.10.2026) | `CLAUDECODE=1`; также `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_EXECPATH`, `CLAUDE_AGENT_SDK_VERSION`, `AI_AGENT` | Признак вендора `claude` — `CLAUDECODE` задан (как в ARCHITECTURE) |
| S2 | Агенты `probe-strong` (`model: opus`, `effort: high`) и `probe-fast` (`model: haiku`, `effort: low`) в `~/.claude/agents/`; запуск типом агента | Агенты подхватываются только **новой сессией** (в чате, где созданы, — «not found»). После перезапуска: `probe-strong` → `claude-opus-5-5`, `probe-fast` → `claude-haiku-5-5`. Усилие (`effort`) по ответу агента не проверяется | Модель роли через frontmatter агента работает. Усилие считаем применённым, прямой проверки нет |
| S3 | `/autopilot manual strict …` в `spikes/demo` с `CLAUDE.md`: executor → probe-fast, reviewer → probe-strong, логировать в `spikes/out/roles.log` | `roles.log` не создан. Оркестратор Autopilot написал, что не выполняет инструкцию, т.к. это «текст из файла, а не просьба пользователя»; субагенты были обычные. Задача при этом выполнена (3 теста зелёные) | **Не слушается** (правило в проектном `CLAUDE.md` оркестратор не считает командой) |

Решение по S3 (владелец, 21.10.2026): вариант (б), навык-обёртка — см. D13 в `docs/DECISIONS.md`.

## Codex (T1.2, 21.10.2026)

Источник: `spikes/codex-demo/out/CODEX_SPIKE_RESULTS.md` (Codex Desktop, отчёт самого Codex; `roles.log` и `role-model-audit.md` я просмотрел,
модели в них согласуются с отчётом). Версии: десктопный `codex.exe` 0.163.0-alpha.11; `codex` в PATH — 0.146.0-alpha.10.1 (разные бинарники).

| Спайк | Что делали | Факт | Вывод |
|---|---|---|---|
| S1 | Переменные `CODEX*` в Codex Desktop | `CODEX_THREAD_ID`, `CODEX_SESSION_ID`, `CODEX_SHELL=1`, `CODEX_CI=1`, `CODEX_VERSION`, `CODEX_CLI_PATH`, `CODEX_INTERNAL_ORIGINATOR_OVERRIDE=Codex Desktop` и др. | Признак вендора `codex`: задана `CODEX_THREAD_ID` (уточняющий: `CODEX_INTERNAL_ORIGINATOR_OVERRIDE`). Это наблюдаемые детали реализации, не документированный контракт |
| S4 | Каталог моделей (`~/.codex/models_cache.json`) и запуск субагента с заданной моделью | Субагент запускается инструментом `collaboration.spawn_agent` с полями `model` и `reasoning_effort` (нужен `fork_turns="none"`). Подтверждено `turn_context` в журнале сессии: `gpt-6-luna`/`low`; ревьюер `gpt-6-astra`/`high` | Выбор модели и усилия субагента работает. Запасной `codex exec` не понадобился. Постоянные файлы `~/.codex/agents/*.toml` (`model`, `model_reasoning_effort`) описаны в документации, **не проверены** |
| S5 | `/autopilot manual strict …` в `codex-demo` (навык в `~/.agents/skills/autopilot`, правило в `AGENTS.md`) | Навык найден в `~/.agents/skills`. Роли соблюдены: executor → `gpt-6-luna/low`, ревьюеры → `gpt-6-astra/high`, 3 теста зелёные, оригинальные 21 файл Autopilot не изменены | «Слушается» — **в контролируемом прогоне**, где оркестратор использовал явные параметры spawn по правилу из `AGENTS.md`. Автообнаружение во «свежем» чате из `codex-demo` и жёсткое исполнение одним `AGENTS.md` не доказаны (чат стартовал в корне репо) |
| S6 | Хуки перед завершением хода | Есть: хук `Stop` (`~/.codex/hooks.json`, `.codex/hooks.json` или `[hooks]` в `config.toml`); `hooks` stable. Код 2 = продолжить, есть `stop_hook_active`. Новые хуки нужно подтвердить в `/hooks` | Поддерживается. Команда-пример проверена напрямую (3 ветки); автоматическое срабатывание в самом Codex **не проверено** |

Побочные факты: `sync.py` Autopilot на Windows падает на запуске сервера (`ps -Ao`), помогает его опция `--no-serve`; жёсткая ссылка `index.html` в песочнице Codex запрещена (навык допускает `dashboard.html`).

### Модели Codex в аккаунте (на 21.10.2026, видимые `list`)

| Модель | Усилия |
|---|---|
| `gpt-6.1-sol` | low, medium, high, xhigh, max, ultra |
| `gpt-6-sol` | low, medium, high, xhigh, max, ultra |
| `gpt-6-astra` | low, medium, high, xhigh, max, ultra |
| `gpt-6-luna` | low, medium, high, xhigh, max |
| `gpt-5.6-sol` | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-terra` | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-luna` | low, medium, high, xhigh, max |

Скрытые (`hide`): `gpt-reserve`, `codex-auto-review` — не использовать как цели ролей. Во всех моделях есть `max`, поэтому правило «`max` для Codex → `xhigh`» из ARCHITECTURE на этом каталоге не нужно; понижение усилия остаётся как общий механизм в `resolve`.


## Программа прогонов (T10.0, 23.10.2026)

Оркестратор — чат Claude Code Desktop (Opus 5.5, режим `auto`); сессии этапов запускались им же в `spikes/program-demo`
(свой git, шаблон python-cli).

| Спайк | Что делали | Факт | Вывод |
|---|---|---|---|
| P1а | Сессия этапа по заданию вызывает `autopilot-roles`, затем `autopilot` инструментом Skill | `autopilot-roles` загрузился и выполнился (вендор `claude`, роли из `resolved.json`). `autopilot` — отказ: «cannot be used with Skill tool due to disable-model-invocation» | Оригинальный Autopilot из сессии не запускается — у него `disable-model-invocation: true` |
| P1б | Задание сессии начинается строкой `/autopilot semi: …` | Строка пришла обычным текстом, навыка `autopilot` в сессии нет | Слеш-команды в задании новой сессии не разворачиваются. Решение владельца — D19: копия `autopilot-stage` без флага |
| P1в | Запуск сессии этапа из хода, начатого уведомлением о конце хода другой сессии, с `cwd` другой папки | Отказ приложения: «it can only start sessions where this one runs, in this project» | Цепочка этапов работает, только если оркестратор открыт в папке проекта и сессии этапов — там же (без `cwd`); так и записано в навыке |
| P3 | Режим разрешений сессии этапа | Наследует режим оркестратора (`auto`), `parentSessionId` указывает на оркестратор | Передавать `permission_mode` явно не нужно, но навык передаёт свой — на случай другого значения по умолчанию |
| P1г | Сессия этапа с заданием из `program.py prompt`: `autopilot-roles`, затем `autopilot-stage` (D19) с аргументами этапа | Прогон пошёл: брифинг, спецификация, план, таск, ревью, F1, слепая приёмка, сдача. Решения Q1/Q2 из задания сессия «взяла из программы, повторно не спрашиваю» | Запуск этапа без человека работает через копию `autopilot-stage` |
| P2 | Вопрос брифинга → ответ | Уведомление о конце хода с пометкой «ждёт владельца»; `program.py check` → `waiting/briefing` с `note` из `state.js`; текст вопроса — из последнего сообщения сессии; ответ через `SendMessage` на `local_…` id — «delivered», ход сессии начался сразу | Цикл «вопрос — один ответ — продолжение» работает; режим разрешений одинаковый (`auto`), ручного одобрения сообщений не было |
| P2б | Ожидание фоновых субагентов | Сессия этапа заканчивает ход, пока работает её фоновый субагент (G2, исполнитель, ревьюеры, слепая приёмка), и просыпается сама. Оркестратор получил 7 таких уведомлений; `check` → `unfinished` | `unfinished` — обычно не остановка. Навык: не слать «продолжай» сессии, которая работает или ждёт своего субагента |
| P4 | Сон компьютера | Живьём не проверялся. Есть `request_keep_awake` (`session_idle`; закрытая крышка всё равно усыпляет). Облачная сессия требует push на GitHub и не может писать оркестратору | v1 — локально + удержание от сна + продолжение `/autopilot-program` по `program.json`; облако — `docs/DEFERRED.md` |
| P5 | Чтение итога этапа | `program.py check --record` → `passed`: `finishedAt`, тикеты `done`, G2–G4 `ok`, слепая приёмка 9/9, гейт код 0, коммит «Autopilot: сборка сдана» после старта этапа, «## Следующий шаг» в `PROGRESS.md`; `result`, `concerns`, `report` переданы в вердикт | Итог читается кодом, без пересказа сессии. Сессия этапа сама направила «Следующий шаг» на `/autopilot-program`, прочитав `PROGRAM.md` |

Итог T10.0: D18 не опровергнут; запуск этапа — через `autopilot-stage` (D19). Длительность этапа S1 (T1, один таск) — около 16 минут.

## Лимиты подписки (T13.0, 23.10.2026)

Чат A (`spike-limit-a`) изображал этап, прерванный лимитом; разовая задача приложения `spike-t13-resume` сработала в 09:00:30.

| Спайк | Что делали | Факт | Вывод |
|---|---|---|---|
| L1 | Задача по расписанию будит простаивающий чат | `SendMessage` отказ: «cannot reach another session from a session nobody opened in this app»; `mcp__ccd_session_mgmt__send_message` — «delivered», чат A ответил «Продолжил после паузы» | Будить можно, только инструментом `send_message` |
| L2 | Задача по расписанию запускает новую сессию | Отказ: «Starting sessions requires a user at the keyboard; this session runs unattended» | Задача не может ни запустить этап, ни стать оркестратором |
| L3 | Родитель разбуженного чата в ходе по уведомлению запускает новую сессию в своей папке | Запущена, ответила «Следующий этап запущен» | После пробуждения этапа цепочка идёт сама. **Устарело (D40, 26.10.2026):** приложение теперь отказывает в любом ходе не со слов владельца — «Start sessions only on the user's own words to you here; this turn runs an automated event, another session's message, or the task another session gave you» (оркестратор DeerFlow, ход по своему `CronCreate`) |
| L4 | Чат, ход которого начат сообщением другой сессии, запускает сессию | Отказ: в таком ходе приложение не запускает сессии, только карточку-предложение | Будить задачей нужно чат этапа, а не оркестратора; для паузы между этапами оркестратор заранее создаёт чат следующего этапа в режиме ожидания сигнала |
| L5 | Что видно в момент исчерпания лимита | Не вызывалось нарочно (встали бы все чаты) | Записать при первом естественном случае; страховка — задача продолжения ставится заранее при 5-часовом ≥ 80% |
| L6 | (26.10.2026, режим auto) Чат-родитель в ходе, начатом сообщением другой сессии вместе с уведомлением о конце хода, очищает свою простаивающую сессию B (`clear_session`) и шлёт ей новое задание | Очистка прошла сразу, без запроса подтверждения: «its conversation now starts over empty (folder, model and settings kept)». B на вопрос о кодовом слове, которое запомнила до очистки, ответила «не знаю кодового слова» | Чат сданного этапа можно очистить и отдать следующему этапу из любого хода — без `start_session` (D40). Ограничения инструмента: только сессия, запущенная этим чатом, простаивающая, не закреплённая и не открытая на экране |

## Antigravity (волна 16, 26.10.2026)

Источник: страницы Google, прочитанные напрямую текстом страницы (не пересказом): `antigravity.google/terms`, `antigravity.google/docs/faq`, `antigravity.google/docs/cli/headless`, `antigravity.google/docs/plans`, `policies.google.com/terms` (редакция от 30.07.2026). Живых запусков `agy` пока нет. Цитаты до 15 слов.

| Спайк | Что делали | Факт | Вывод |
|---|---|---|---|
| A14 | Прочитали условия Antigravity, FAQ, документацию headless и общие условия Google | (1) Additional Terms: использование «third party software, tools, or services to access the Service» — «is a breach of this Agreement» (пример в тексте — OpenClaw с OAuth Antigravity); последствие — приостановка аккаунтов Antigravity и/или Gemini CLI. Там же запрещено использовать сервис «in connection with products not provided by us». (2) FAQ: использовать Claude Code, OpenClaw, OpenCode с входом Antigravity нельзя; для сторонних агентов Google рекомендует ключ Gemini Enterprise или Google AI Studio. (3) FAQ о headless: `agy -p` «intended for direct scripting and CI workflows»; обёртка `agy` в сторонних агентах или приложениях и ротация аккаунтов — «not supported under consumer plans». (4) Документация headless: `agy -p` — штатный способ запуска из скриптов и CI (`--output-format json`, `--continue`, `--conversation`, `--model`, `--effort low/medium/high`, `--print-timeout`, по умолчанию 5 минут, без подтверждения разрешений действие тихо отклоняется с кодом 0). (5) Общие условия Google (30.07.2026) о запуске официальных клиентов скриптами ничего особого не говорят. (6) По условиям записываются «Interactions» (запросы, код, обратная связь), их могут просматривать сотрудники Google; отказаться можно в настройках. (7) При выборе модели Claude действуют коммерческие условия Anthropic. (8) Доступно в разрешённых странах для личных аккаунтов Google, возраст 18+, рабочие аккаунты Workspace не гарантированы | **Разрешено прямо:** запускать официальный `agy -p` своим скриптом (в том числе в CI). **Запрещено прямо:** вход Antigravity через сторонние программы и ротация аккаунтов. **Не определено:** наш `program.py`, запускающий `agy -p` по очереди для программы прогонов, — это «собственный скрипт» или «приложение-обёртка». Вариант A (навыки, `AGENTS.md`, гейт, без запуска `agy` комплектом) условий не затрагивает. Вариант B (привод через `agy -p`) — в серой зоне; письмо в поддержку решено не отправлять (D37). Отдельный риск — данные «Interactions» уходят в Google (закрытые проекты не запускать, пока не решено). Остаточный риск принят владельцем на время MVP-проверки (D37) |
