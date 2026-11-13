# Архитектура Autopilot Kit

> Оригинальный Autopilot — [nick-vels/skills](https://github.com/nick-vels/skills) (MIT, © Nick Vels): kit его не меняет; копия лежит в `vendor/autopilot`. Отличия — [DIFF_FROM_UPSTREAM.md](DIFF_FROM_UPSTREAM.md), приводы — [DRIVES.md](DRIVES.md).

## Что это

Комплект для одного пользователя. Ставит **оригинальный Autopilot** (nick-vels/skills, без изменений) в Claude Code, Codex
и Claude Desktop с гейтвеем (три привода, D53) и добавляет к нему **роли с моделями**, **проверки качества** и **готовые настройки приложений**.
Работает только внутри приложений по подписке (см. DECISIONS D3, D4).

```
                ┌──────────── Приложение (Claude / Codex / Gate) ─────────────┐
 владелец  ───► │ главный чат = оркестратор Autopilot (модель выбирает человек)│
 /autopilot     │    │ читает навык autopilot (оригинал, без изменений)        │
                │    │ читает навык autopilot-roles (наш)                      │
                │    │    → определяет приложение → берёт профиль              │
                │    ├─► субагент executor        (модель/усилие из профиля)  │
                │    ├─► субагент reviewer-spec   (модель/усилие из профиля)  │
                │    ├─► субагент reviewer-craft  (модель/усилие из профиля)  │
                │    └─► субагент final-reviewer  (модель/усилие из профиля)  │
                │ хук Stop → gate.py → тесты/линтер проекта → не «готово» при FAIL │
                └──────────────────────────────────────────────────────────────┘
```

## Компоненты

| Компонент | Где лежит в репозитории | Куда ставится | Назначение |
|---|---|---|---|
| Установщик `kit` | `kit/` (Python, только стандартная библиотека, ≥ 3.11) | запускается из репозитория: `python -m kit …` | `install`, `update`, `status`, `doctor`, `uninstall`, `project init` |
| Оригинальный Autopilot | копия без изменений в `vendor/autopilot` (+ `vendor/LICENSE`, `vendor/UPSTREAM.json`; D56); `upstream.lock.json` | `~/.claude/skills/autopilot`, `~/.agents/skills/autopilot` | Сам процесс разработки |
| Навык `autopilot-roles` | `skills/autopilot-roles/SKILL.md` | рядом с autopilot в обоих местах | Правила: какое приложение, какой профиль, каким типом агента и с какой моделью запускать субагентов; гейт; предупреждение, что прогон даёт документы, а не код (D16); раздел «Следующий шаг» в отчёте многоэтапного проекта (D17) |
| Навык `autopilot-setup` | `skills/autopilot-setup/SKILL.md` | там же | Мастер: тариф, рекомендации, запись профиля |
| Таблица моделей | `kit/data/models.json` | `~/.autopilot-kit/models.json` | Уровень → имя модели и допустимые усилия по вендорам |
| Профиль | пресеты в `kit/profile.py` | `~/.autopilot-kit/profile.toml` (глобально), `.autopilot-kit/profile.toml` (проект, необязательно; действует только в Codex — в Claude Code модель берётся из глобальных файлов агентов) | Роль → уровень + усилие |
| Агенты Claude | генерируются: `kit/render.py` | `~/.claude/agents/autopilot-*.md` | Модель и усилие ролей для Claude Code |
| Роли Codex | `~/.autopilot-kit/resolved.json` (пишет `install`/`profile set`) | файлов агентов Codex `install` не создаёт (`render_codex` есть в коде и тестах, но не вызывается) | Модель и усилие ролей для Codex: поля `model` и `reasoning_effort` инструмента `spawn_agent` (`fork_turns="none"`), оркестратор подставляет их по `resolved.json` (проверено приёмкой T6.2) |
| Гейт качества | `kit/gate.py` | `~/.autopilot-kit/bin/gate.py` | Запуск проверок проекта из `.autopilot-kit/project.toml` |
| Навык `autopilot-program` | `skills/autopilot-program/SKILL.md` | рядом с autopilot | Оркестратор программы из нескольких прогонов (D18): вопросы пачкой, этап = новая сессия, проверка сдачи, отчёт. Все три привода: в Claude этап — новая сессия, в Codex — фоновый `codex exec` (D24) |
| Состояние программы | `kit/program.py` (самодостаточный) | `~/.autopilot-kit/bin/program.py`; данные — `<проект>/.autopilot/program.json` + вид `PROGRAM.md` | Этапы, вопросы и ответы владельца, вердикт этапа по `state.js`, гейту, git и `PROGRESS.md`, задание сессии этапа |
| Проверка швов и dev | `kit/seams.py`, `kit trial`, `kit check-update` | dev: `~/.autopilot-kit/trial/home` | Новая версия ядра проверяется в песочнице до прода: файлы, frontmatter, якоря, настоящий `ap.py` глазами `program.py` и `gate.py` (D20); `update` не ставит версию с красными швами; еженедельная задача приложения по понедельникам |
| Пульт всех программ | `kit/dashboard.py`, `kit/dashboard_page.html` | запускается из репозитория: `python -m kit dashboard`, сервер на `127.0.0.1:8699` | Общий уровень над дашбордами программ (D43): что требует внимания, трек этапов, гейт, версия ядра, автоматика; только чтение |
| Дашборд программы | `kit/program_page.html` | `~/.autopilot-kit/bin/program_page.html` → `<проект>/.autopilot/program.html` | Ход всей программы рядом с чатом оркестратора (D21): читает `program.js` и `state.js`, опрашивает их каждые 5 с; отдаёт локальный сервер kit (D25, origin редиректит на `program.html`), панель приложения открывает его через конфигурацию `autopilot-program` в `.claude/launch.json` (`preview_start` по имени, T21.11; файл вне git — машинно-зависим) |
| Копия Autopilot для этапов | генерируется `kit/upstream.py` из закреплённой версии | `~/.claude/skills/autopilot-stage` | Оригинал без `disable-model-invocation`, другое имя и описание (D19): сессия этапа вызывает его инструментом Skill |
| Шаблоны проекта | `templates/generic/`, `templates/python-cli/`, `templates/small-web/` | в проект по `kit project init` | `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.autopilot-kit/project.toml` |

## Роли

| Роль | Кто | Рекомендация Claude | Рекомендация Codex |
|---|---|---|---|
| `orchestrator` | главный чат | сильная (рекомендуется, не навязывается) | сильная |
| `executor` | субагент, пишет код тикета | сбалансированная, `medium` | сбалансированная, `medium` |
| `reviewer-spec` | субагент Autopilot: оси Manifest + Spec | сильная, `high` | сильная, `high` |
| `reviewer-craft` | субагент Autopilot: ось Craft | сильная, `high` | сильная, `high` |
| `final-reviewer` | субагент финальной приёмки (Autopilot, фаза 8) | сильная, `high` | сильная, `high` |

Экономный пресет для младших тарифов: `reviewer-*` = сбалансированная `high`, `final-reviewer` = сильная `high` (как и в `quality`: усилие выше `high` не дают прироста, оправдывающего цену, D58).

Класс тикета (D58): `executor` — класс «обычная». Тикет `Модель: сильная` и повтор упавшего тикета запускаются тем же агентом, но на сильной модели (параметр `model` вызова) — навык `autopilot-roles` §3.

Уровни для Claude — псевдонимы, которые указывают на последнюю версию: сильная = `opus`,
сбалансированная = `sonnet`, быстрая = `haiku`. Уровни для Codex заполняются по факту
доступных моделей: каталог на 21.10.2026 — в `docs/SPIKES.md` (S4). Имена не выдумываются.

## Определение приложения

Подключение ролей — через навык-обёртку `autopilot-roles` (D13: правило в `CLAUDE.md` оркестратор не исполнил, спайк S3).
Навык `autopilot-roles` при старте выполняет в терминале проверку:
- явная фиксация владельца `drive = "claude" | "claude-gate" | "codex"` в `.autopilot-kit/project.toml` проекта
  или `~/.autopilot-kit/profile.toml` → она переопределяет окружение (T19.8/D49). Ключ верхнеуровневый: записанный
  после `[gate]`/`[roles.…]` он попадает в таблицу и игнорируется — `kit doctor` предупреждает (T19.9);
- переменная `CLAUDE_CODE_ENTRYPOINT` равна `claude-desktop-3p` → вендор `claude-gate`
  (привод «Claude Desktop Gate», D48: Claude Desktop 3p с гейтвеем организации). `ANTHROPIC_BASE_URL` признаком
  не является — подписочное приложение тоже задаёт его (локальный прокси); авторитетное подтверждение привода —
  `plan.status` из `get_usage` (`ok` → подписка, `not_applicable` → гейтвей), его применяет `program.py limits` (D49);
- переменная `CLAUDECODE` задана → вендор `claude`;
- переменная `CODEX_THREAD_ID` задана → вендор `codex` (спайк S1, `docs/SPIKES.md`);
- иначе остановиться и спросить владельца.

Вендор пишется в `.autopilot-kit/last_host`. Если он отличается от прошлого раза, сохранённые
ревьюеры Autopilot считаются недоступными и создаются заново. Тот же маркер (`claude-gate`) пишет гейт
в `host` журнала прогонов, а `program.py` добавляет его третьим элементом идентичности `orchestratorMachine`:
сессии и задачи приложения живут в профиле приложения, поэтому два профиля на одной машине не будят сессии друг друга.

## Гейт качества

`.autopilot-kit/project.toml` проекта:

```toml
[gate]
commands = ["python -m pytest -q"]   # по порядку, все должны вернуть 0
timeout_seconds = 600
```

- **Claude Code.** Хук `Stop` в `.claude/settings.json` проекта вызывает `gate.py --hook claude-stop`.
  При провале возвращается код 2, Claude получает вывод и продолжает работу.
  Защита от зацикливания: если во входных данных хука `stop_hook_active == true`
  и это уже вторая подряд неудача, гейт пропускает остановку и печатает «ГЕЙТ НЕ ПРОЙДЕН».
  Хук **не блокирует** остановку (D14), когда Autopilot ждёт владельца — поле `waiting` в `.autopilot/state.js`
  проекта (его ставит `ap.py ask`: брифинг, ручные гейты спецификации и плана, вопрос перед необратимым, стоп),
  и когда тестов ещё нет — команда pytest вернула код 5. Обычный запуск `gate.py` (без `--hook`) в обоих случаях строгий.
  Вывод гейта всегда в UTF-8. Корень проекта гейт ищет вверх от `cwd` события (или текущей папки) до ближайшей
  папки с `.autopilot-kit/project.toml`: оболочка Claude может стоять в подпапке проекта (найдено в T7.2).
- **Codex.** Хук `Stop` в Codex существует (спайк S6; формат — документация Codex, страница hooks): `.codex/hooks.json`
  или `[hooks]` в `config.toml`, на вход те же `cwd`, `transcript_path`, `stop_hook_active`, код 2 + stderr = продолжить работу,
  новые хуки нужно подтвердить в `/hooks`, проектный слой `.codex/` — доверенный. Шаблоны проекта кладут `.codex/hooks.json`
  с `gate.py --hook codex-stop` (D33; тот же обработчик, что у `claude-stop`); **вживую хук не проверен** (спайк C7).
  Запасной уровень остаётся: правило в `AGENTS.md` и шаг 7 навыка `autopilot-roles`: «перед словом "готово"
  выполни gate.py и покажи вывод». В приёмке T6.2 Codex его выполнил.

## Программа прогонов (D18, D19)

```
 владелец ─► чат в папке проекта: /autopilot-program (оркестратор, кода не пишет)
               │ program.py init / stage add / ask+answer (вопросы всех этапов — один раз)
               │ program.py next → start <ID> → prompt <ID>
               ├─► новая сессия этапа (та же папка, тот же режим разрешений)
               │      autopilot-roles → autopilot-stage <аргументы этапа> → обычный прогон Autopilot
               │◄── уведомление «сессия закончила ход»
               │ program.py check --record → waiting   → один вопрос владельцу → SendMessage в сессию этапа
               │                           → unfinished→ обычно ждёт своего субагента: ничего не делать
               │                           → failed    → стоп, один вопрос владельцу
               │                           → passed    → коммит program.json → следующий этап
               └─► program.py report

 дашборд программы: program.html ◄── program.js (program.py) + state.js (Autopilot), в панели рядом с чатом оркестратора
```

Один прогон в папке за раз (`start` отказывает). Сдача этапа: прогон закончен, тикеты сданы, G2–G4 не провалены
и слепая приёмка была, гейт — код 0, после старта есть коммит «Autopilot: сборка сдана», в `PROGRESS.md` — «## Следующий
шаг» (кроме последнего этапа). Ограничение приложения (спайк P1в): из хода, начатого уведомлением, сессию можно запустить
только в папке оркестратора, поэтому оркестратор открывается в папке проекта.

## Claude Code и Codex

Одно ядро, три привода (D24, D48, D53), одна ветка `main`. Обзор приводов, установка и работа в каждом — `docs/DRIVES.md`;
отличия от оригинала Autopilot — `docs/DIFF_FROM_UPSTREAM.md`. Что как устроено в каждом приложении и что ещё не выровнено —
`docs/PARITY.md`; каждая новая возможность добавляется туда строкой сразу для всех приводов.

Привод «Claude Desktop Gate» (D48) — то же приложение Claude Code, но трафик идёт через гейтвей организации
(`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` в `~/.claude/settings.json`), а не через подписку Anthropic.
Отличия привода: вендор `claude-gate` и пресет `desktop-gate` в профиле, лимиты подписки не применяются
(`plan.status = not_applicable` — §5a навыка программы пропускается), в билде нет `PushNotification`,
`tabs_context`/`tabs_select` и `ToolSearch` (замены — в `docs/PARITY.md`), путь хука Stop в шаблонах — `$HOME`-форма.
Подробности — раздел «Привод «Claude Desktop Gate» (D48)» в `docs/PARITY.md`.

## Чего нет и не будет в v0.1

Межвендорное ревью; API; локальные модели; сервер; веб-интерфейс; изменение файлов
оригинального Autopilot; песочницы и подписи; работа с несколькими пользователями.
