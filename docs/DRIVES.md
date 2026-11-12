# Три привода: Claude (подписка), Codex, Claude Desktop Gate

**Одна ветка `main`, одно ядро, три привода.** Ветки под приложения не делаются: привод — это режим одного и того же кода,
он выбирается профилем и окружением (решения D24, D48, D49, D53). Любое исправление ядра, гейта или оркестратора попадает
сразу во все три.

```
оригинальный Autopilot (github.com/nick-vels/skills, версия закреплена в kit/data/upstream.pin, без изменений)
        │
        ▼
autopilot-kit (этот репозиторий, ветка main): роли с моделями · гейт качества · оркестратор программ · шаблоны проектов
        │
        ├── привод «claude»       Claude Desktop / Claude Code по подписке Anthropic (Opus, Sonnet, Haiku)
        ├── привод «codex»        Codex по подписке ChatGPT (модели OpenAI)
        └── привод «claude-gate»  Claude Desktop 3p: то же приложение, но трафик идёт через гейтвей организации,
                                  модели не Anthropic
```

Работает в режиме «или-или»: проект ведёт одно приложение за раз, и тот привод, в котором он начат, делает всё. Сменить приложение
можно: откройте проект в другом и повторите `autopilot-roles` — навык заметит смену и пересоздаст ревьюеров.

## Что общее, а что своё

| | `claude` | `codex` | `claude-gate` |
|---|---|---|---|
| Приложение | Claude Desktop / Claude Code | Codex (приложение или CLI) | Claude Desktop 3p (`CLAUDE_CODE_ENTRYPOINT=claude-desktop-3p`) |
| Откуда модели | подписка Anthropic | подписка ChatGPT | гейтвей организации (в `~/.claude/settings.json`: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`) |
| Уровни моделей | сильная `opus`, средняя `sonnet`, быстрая `haiku` | `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna` (таблица `kit/data/models.json`) | псевдонимы те же, но гейтвей сам отображает их в свои модели; пресет `desktop-gate` |
| Где лежат навыки | `~/.claude/skills` | `~/.agents/skills` | `~/.claude/skills` |
| Как задаются модели ролей | файлы агентов `~/.claude/agents/autopilot-*.md` | поля `model` и `reasoning_effort` в `spawn_agent` из `~/.autopilot-kit/resolved.json` (агентских файлов нет) | как в `claude` |
| Как вызываются навыки | `/autopilot`, `/autopilot-roles`, `/autopilot-program` | `$autopilot`, `$autopilot-roles`, `$autopilot-program` (или «Используй навык …») | как в `claude` |
| Гейт «готово» | хук Stop в `.claude/settings.json` → `gate.py --hook claude-stop` | хук Stop в `.codex/hooks.json` → `gate.py --hook codex-stop` + правило в `AGENTS.md` | как в `claude`, путь хука в форме `$HOME/...` |
| Этапы программы | новая сессия приложения на этап | фоновый `codex exec` (`program.py codex-run`) | как в `claude` |
| Лимиты | `get_usage`: паузы и продолжение после сброса | `rate_limits` из `~/.codex/sessions` | не применяются (`plan.status = not_applicable`): пауз по лимитам нет |
| Дашборд | панель рядом с чатом | ссылка на страницу в браузере | как в `claude` |
| Зрелость | работает, используется в проектах | написано, тесты зелёные, **живая проверка не пройдена** (спайк T15.0) | первый срез проверен живьём 07.11.2026, часть пунктов после правок ждёт перепроверки |

Одинаково у всех трёх: оригинальный Autopilot, `gate.py`, `program.py`, `program.json`, план программы, пульт `kit dashboard`,
навыки `autopilot-roles`, `autopilot-setup`, `autopilot-init`, `autopilot-program`, шаблоны проекта. Построчное сравнение
возможностей — [PARITY.md](PARITY.md).

## Как определяется привод

Навык `autopilot-roles` проверяет по порядку и останавливается на первом совпадении:

1. `drive = "claude" | "claude-gate" | "codex"` в `.autopilot-kit/project.toml` проекта или `~/.autopilot-kit/profile.toml` — явная
   фиксация владельца (сильнее всего; ключ должен стоять до всех `[таблиц]` файла, `kit doctor` предупредит, если нет);
2. `CLAUDE_CODE_ENTRYPOINT=claude-desktop-3p` → `claude-gate`;
3. `CLAUDECODE` задана → `claude`;
4. `CODEX_THREAD_ID` задана → `codex`;
5. иначе навык останавливается и спрашивает владельца.

Признак `ANTHROPIC_BASE_URL` приводом не считается: подписочное приложение тоже ставит туда локальный прокси. Оркестратор
программ дополнительно подтверждает привод по ответу `get_usage` (`plan.status: ok` → подписка, `not_applicable` → гейтвей).
Если окружение неоднозначно, зафиксируйте привод:

```powershell
python -m kit profile set --drive claude        # или codex, или claude-gate
```

Привод пишется в `.autopilot-kit/last_host`, в журнал гейта (`host`) и в идентичность оркестратора.

---

## Привод 1. Claude Desktop / Claude Code по подписке (модели Anthropic)

**Нужно:** Windows 11, Python 3.11+, git, приложение Claude с входом по подписке. `ANTHROPIC_API_KEY` в окружении быть не должно.

**Установка** (из клона репозитория):

```powershell
python -m kit install     # Autopilot, навыки kit, агенты ролей, гейт, resolved.json
python -m kit doctor      # ожидается FAIL 0; WARN про вход claude CLI — нормально
```

**Настройка:** откройте **новый чат** (навыки и агенты читаются при старте) и выполните `/autopilot-setup` — мастер спросит
тариф и запишет профиль (пресет `economy` для Pro, `quality` для остальных). Без мастера:
`python -m kit profile set --preset quality`. Модель главного чата выбираете вы сами в приложении (лучше сильную).

**Работа над проектом:**

1. Откройте приложение в папке проекта, примите доверие к папке (без него хук гейта не работает).
2. Один запуск: `/autopilot-init`, затем `/autopilot-roles`, затем `/autopilot semi: <что построить>`.
3. Программа из нескольких прогонов: `/autopilot-program <цель или файл плана>` — оркестратор сам настраивает проект, ведёт этапы
   новыми сессиями, показывает дашборд рядом с чатом, следит за лимитами подписки (пауза при 5-часовом ≥ 85% или недельном ≥ 90%).
4. Чат оркестратора держите в режиме разрешений `auto`; компьютер не должен засыпать.

**Особенности:** этапы запускаются через копию `autopilot-stage` (её ставит `install`, вручную не вызывать); сторож программ и
проверка обновлений — задачи приложения.

## Привод 2. Codex (модели OpenAI)

**Нужно:** Windows 11, Python 3.11+, git, Codex с входом по ChatGPT (`codex login status`). `OPENAI_API_KEY` быть не должно.
Приложение Claude для этого привода не требуется: `install` создаст папки `~/.claude/...`, но Codex их не читает.

**Установка** — те же две команды:

```powershell
python -m kit install
python -m kit doctor
python -m kit profile set --drive codex      # рекомендуется: явная фиксация привода
```

**Настройка:** в Codex новый чат → «Используй навык autopilot-setup» (или `$autopilot-setup`); без мастера —
`python -m kit profile set --preset quality`. Имена моделей Codex берутся из `kit/data/models.json` (раздел `codex`):
**проверьте, что они доступны вашей подписке, и при необходимости поправьте файл** — в нём модели владельца репозитория на
октябрь 2026. После правки: `python -m kit install` (пересчитает `resolved.json`), новый чат. Проектный
`.autopilot-kit/profile.toml` (правки ролей для одного проекта) действует только в этом приводе.

**Работа над проектом:**

1. Откройте Codex в папке проекта. Шаблоны проекта кладут `AGENTS.md` и `.codex/hooks.json`; хук Stop при первом запуске надо
   один раз подтвердить в `/hooks`.
2. Первым сообщением: «Используй навык autopilot-roles» (или `$autopilot-roles`), вторым: `$autopilot semi: <что построить>`.
3. Программа из нескольких прогонов: `$autopilot-program <цель или файл плана>`. Этапы идут фоновым `codex exec`
   (`program.py codex-run`), оркестратор просыпается задачей в своём чате и читает состояние через `program.py codex-status`.
   Дашборд — ссылка в сообщениях оркестратора (панели в Codex нет).

**Что проверено вживую, а что нет** (честно):

- проверено (приёмка T6.2, 21.10.2026): роли и модели субагентов через `spawn_agent`, проект доведён до зелёных тестов,
  гейт по правилу `AGENTS.md` не дал объявить «готово» при красных тестах;
- **не проверено** (спайк T15.0, пункты C1–C8 в [`docs/CODEX_SPIKE.md`](CODEX_SPIKE.md)): хук Stop
  в живом Codex, запуск этапов `codex-run`, пробуждение оркестратора, ответы на вопросы этапа `codex-answer`, встроенный браузер
  для дашборда. Пока их не прошли, считайте оркестратор программ в Codex экспериментальным; одиночный `$autopilot` с гейтом
  работает надёжнее.
- задачи по расписанию для проверки обновлений ядра в Codex не заведены: обновляйте вручную (раздел «Обновление» ниже).

## Привод 3. Claude Desktop Gate (сторонние модели через гейтвей)

**Что это:** то же приложение Claude Desktop (сборка 3p), но провайдер задан организацией: в `~/.claude/settings.json` прописаны
`ANTHROPIC_BASE_URL` (адрес гейтвея) и `ANTHROPIC_AUTH_TOKEN`. Модели не от Anthropic: гейтвей сам отображает псевдонимы
`opus`/`sonnet`/`haiku` в свои (у владельца — Qwen). Ключи и токены kit **не задаёт и не печатает**: это настройка организации.
Это исключение из запрета на API (D3) закреплено в D48.

**Нужно:** то же, что в приводе 1, плюс приложение уже подключено к гейтвею организации.

**Установка:**

```powershell
python -m kit install
python -m kit doctor                                  # гейтвей распознаётся как OK; API-ключи по-прежнему FAIL
python -m kit profile set --preset desktop-gate       # исполнитель на сильной модели
python -m kit profile set --drive claude-gate         # явная фиксация, если окружение ненадёжно
```

Пресет `desktop-gate` нужен потому, что у гейтвея нет настоящей «средней» модели: псевдоним `sonnet` даёт слабую (flash)
модель, и в `quality` исполнитель получал бы её. Агенты `~/.claude/agents` общие для всех профилей Claude на машине, поэтому
пресет выбирается на машину, а не на проект.

**Работа над проектом:** как в приводе 1 (`/autopilot-init`, `/autopilot-roles`, `/autopilot`, `/autopilot-program`). Отличия:

- лимитов подписки нет: паузы и задачи продолжения по лимиту не создаются, за остановками следят сторож программ и `program.py job set`;
- в билде нет некоторых инструментов (`PushNotification`, `tabs_context`/`tabs_select`, `ToolSearch`): навыки используют
  замены (`mcp__ccd_turn__wrap_up`, `preview_list` + `show_pane`), таблица замен — в [PARITY.md](PARITY.md);
- расписания и сессии приложения живут в профиле приложения (`AppData\Local\Claude-3p`), сторож программ регистрируется на каждый
  профиль отдельно, программы чужого профиля он не трогает (`foreign: true`);
- путь хука Stop в шаблонах — `python "$HOME/.autopilot-kit/bin/gate.py" --hook claude-stop` (Git Bash и PowerShell раскрывают `$HOME`);
  проекты на общем диске нескольких машин работают без `kit relocate`.

**Проверено:** пресет, определение привода, `doctor`, запись `host: claude-gate` в журнал гейта, срабатывание хука Stop от приложения
(07.11.2026). После правки D49 ещё перепроверяются: суженный признак окружения, `get_usage`-подтверждение, сторож в профиле гейтвея,
доставка `wrap_up` владельцу.

---

## Установка силами другой LLM (Codex, Claude или любой агент)

Репозиторий рассчитан на то, что установку может выполнить сам агент по этой инструкции. Человеку достаточно открыть агента в
папке клона и вставить запрос:

> Прочитай `docs/DRIVES.md` и `AGENTS.md` в этом репозитории. Мой привод: **<claude | codex | claude-gate>**. Установи kit по разделу
> «Протокол для агента», проверь `python -m kit doctor`, зафиксируй привод и доложи результат. Не задавай API-ключи, не меняй
> файлы оригинального Autopilot, ничего не пушь.

### Протокол для агента

1. **Окружение.** Windows 11 (на других ОС не проверялось), `python --version` ≥ 3.11, `git --version`. Нет Python 3.11+ — стоп,
   сообщить владельцу. Внешних зависимостей нет, `pip install` не нужен (для разработки kit — только `pytest`).
2. **Привод.** Спросить владельца или определить: задан `CODEX_THREAD_ID` → `codex`; `CLAUDE_CODE_ENTRYPOINT=claude-desktop-3p`
   или в `~/.claude/settings.json` есть `ANTHROPIC_BASE_URL` на чужой адрес и `ANTHROPIC_AUTH_TOKEN` → `claude-gate`; иначе →
   `claude`. Сомнение — спросить, не угадывать.
3. **Запреты.** Не создавать и не вписывать `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` и токены; не копировать токены гейтвея в файлы
   репозитория и в ответы; не править `~/.claude/skills/autopilot` и `~/.agents/skills/autopilot` вручную (это оригинал, kit
   откажется его перезаписывать — `LOCAL_CHANGES`); не пушить без просьбы.
4. **Установка** из корня клона: `python -m kit install`. Повторный запуск безопасен. Файлы вне репозитория меняются только с
   копией `<файл>.bak-<UTC>`.
5. **Профиль.** `python -m kit profile set --preset <economy|quality|desktop-gate>`: `economy` — младшие тарифы, `quality` — остальные,
   `desktop-gate` — только гейтвей. Затем `python -m kit profile set --drive <привод>`.
6. **Проверка.** `python -m kit doctor` — нужно `FAIL 0`; `python -m kit status` — «хеши совпадают». Любой `FAIL` — показать
   владельцу, не обходить. Для `codex` ещё проверить `codex login status`.
7. **Тесты kit** (по желанию): `python -m pytest -q` из корня клона (нужен `pytest`).
8. **Проект.** Показать владельцу, что дальше делается в **новом чате в папке проекта** (навыки читаются при старте чата):
   `autopilot-init` → `autopilot-roles` → `autopilot` или `autopilot-program` (синтаксис вызова — в разделе нужного привода выше).
9. **Отчёт агента:** какой привод выбран и почему, версия Autopilot (`python -m kit status`), итог `doctor`, что не проверено
   (для `codex` — спайк T15.0).

### For an AI agent (English summary)

This repo is an add-on for the upstream *Autopilot* skill (nick-vels/skills, pinned in `kit/data/upstream.pin`, installed unmodified).
One `main` branch, one engine, three "drives": `claude` (Claude Desktop/Code on an Anthropic subscription), `codex` (Codex on a
ChatGPT subscription), `claude-gate` (Claude Desktop 3p behind an organization gateway, non-Anthropic models). Install with
`python -m kit install`, set the drive with `python -m kit profile set --drive <claude|codex|claude-gate>`, verify with
`python -m kit doctor` (expect FAIL 0). Python ≥ 3.11 stdlib only; tested on Windows 11 only. Never set API keys, never edit the
upstream skill files, never push without the owner's request. The Codex drive is implemented and unit-tested but not yet verified live
(spike T15.0).

## Обновление оригинального Autopilot

Ядро — чужой код: kit его не меняет и подстраивается сам. Порядок: проверка → швы в песочнице → установка.

```powershell
python -m kit check-update    # есть ли новая версия оригинала
python -m kit trial           # поставить кандидата в dev (~/.autopilot-kit/trial/home) и проверить швы; прод не меняется
python -m kit update --yes    # поставить в прод, только если швы зелёные и ни один этап программы не идёт
```

У владельца репозитория по понедельникам в 10:07 это делает задача приложения Claude (ставит сама при зелёных швах и свободных
этапах, D42). В приводе Codex такой задачи нет — запускайте `check-update` раз в неделю вручную. Не обновляйте ядро, пока идёт
этап программы: у этапа своя копия `.autopilot/ap.py`, и получится смесь версий.

## Как добавить четвёртый привод

Привод — это строка в `kit/data/models.json` (вендор и уровни моделей), признак окружения в `gate.py drive_of()` и
`program.py drive_id()`, пункты в этом файле и в [PARITY.md](PARITY.md). Образец — D48 (привод `claude-gate`) и D36/D37 (Antigravity,
MVP). Ветки для этого не нужны.
