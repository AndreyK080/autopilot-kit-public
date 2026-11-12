# Autopilot Kit

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Windows 11](https://img.shields.io/badge/tested%20on-Windows%2011-lightgrey)

**Надстройка над [Autopilot](https://github.com/nick-vels/skills) Nick Vels** — навыком, который по вашей идее строит готовый проект.
Оригинал лежит внутри репозитория (`vendor/`), без изменений. Kit добавляет то, чего в нём нет: проект из нескольких прогонов под
управлением оркестратора, единый дашборд, роли с моделями и контроль «готово». Работает в **Claude Desktop/Code**, **Codex** и
**Claude Desktop через гейтвей** (сторонние модели). Только приложения по подписке, без API-ключей.

## Чем отличается от оригинала

| | Оригинал | Autopilot Kit |
|---|---|---|
| Объём | один прогон, следующий запускаете вы | **оркестратор этапов**: ведёт проект из нескольких прогонов сам |
| Дашборд | один на прогон | **дашборд программы** (все этапы, «внутри этапа») и **пульт всех проектов** |
| Модели | «сильная» и «обычная» | модель и усилие для каждой роли из вашего профиля |
| «Готово» | проверки оригинала | плюс **гейт качества**: тесты проекта должны проходить |
| Сбои и лимиты | — | паузы по лимитам подписки, сторож прерванных этапов |
| Приложения | Claude Code, Cursor, Codex и др. | три **привода**: Claude, Codex, Claude Desktop Gateway |

Подробно — [docs/DIFF_FROM_UPSTREAM.md](docs/DIFF_FROM_UPSTREAM.md).

## Быстрый старт

Нужно: Windows 11, Python 3.11+, git. Внешних зависимостей нет.

```powershell
git clone https://github.com/AndreyK080/autopilot-kit-public.git
cd autopilot-kit-public
python -m kit install      # ставит Autopilot из vendor/ и навыки kit, без сети
python -m kit doctor       # ждём FAIL 0
```

Затем выберите привод и откройте **новый чат** приложения:

<details>
<summary><b>Claude Desktop / Claude Code</b> — подписка Anthropic (Opus, Sonnet, Haiku)</summary>

```powershell
python -m kit profile set --preset quality --drive claude     # для Pro: --preset economy
```
В чате: `/autopilot-setup` (по желанию — мастер профиля). Проект: открыть папку, `/autopilot-init`, затем `/autopilot-roles` и
`/autopilot semi: <что построить>`.
</details>

<details>
<summary><b>Codex</b> — подписка ChatGPT</summary>

```powershell
python -m kit profile set --preset quality --drive codex
```
Имена моделей — в `kit/data/models.json`: проверьте, что они есть в вашей подписке. В чате: «Используй навык autopilot-init», затем
`$autopilot-roles` и `$autopilot semi: <что построить>`. Оркестратор программ в Codex написан и покрыт тестами, но живая проверка ещё
не пройдена ([docs/CODEX_SPIKE.md](docs/CODEX_SPIKE.md)).
</details>

<details>
<summary><b>Claude Desktop через гейтвей</b> — сторонние модели</summary>

```powershell
python -m kit profile set --preset desktop-gate --drive claude-gate
```
Так же, как в Claude. Лимитов подписки нет, паузы по ним не создаются; у гейтвея нет «средней» модели, поэтому исполнитель работает
на сильной (пресет `desktop-gate`).
</details>

<details>
<summary><b>Попросить установить агента</b> (Codex, Claude или другого)</summary>

Откройте агента в папке клона и вставьте:

> Прочитай `docs/DRIVES.md` и `AGENTS.md`. Мой привод: **claude | codex | claude-gate**. Установи kit по разделу «Протокол для агента»,
> проверь `python -m kit doctor`, зафиксируй привод и доложи. Не задавай API-ключи, не меняй файлы оригинального Autopilot, ничего не пушь.
</details>

## Как работать

- **Один прогон:** `/autopilot-init` → `/autopilot-roles` → `/autopilot semi: <задача>` (в Codex — `$autopilot…`).
- **Проект из нескольких этапов:** `/autopilot-program <цель или план>` — оркестратор разбивает работу, один раз спрашивает всё нужное,
  запускает каждый этап новой сессией, показывает дашборд и сообщает, когда нужны вы.

<details>
<summary>Что делает оркестратор программы</summary>

1. Приводит цель или документы к плану этапов и один раз в начале задаёт вопросы (с рекомендованным ответом).
2. Запускает каждый этап новой сессией, передаёт вам вопросы этапа и проверяет сдачу: гейт, слепая приёмка, коммит.
3. Следит за лимитами подписки (пауза до сброса) и будит прерванные этапы.
4. Показывает **дашборд программы** рядом с чатом: все этапы, процент, блок «внутри этапа», вопрос, который ждёт вас.
</details>

Больше — в [руководстве](docs/USAGE.md): роли, новый проект, программа прогонов, обновление, смена приложения, зависший гейт.

## Документация

| | |
|---|---|
| [docs/DRIVES.md](docs/DRIVES.md) | три привода: что общее, как ставить и работать, протокол установки для агента |
| [docs/DIFF_FROM_UPSTREAM.md](docs/DIFF_FROM_UPSTREAM.md) | чем kit отличается от оригинала |
| [docs/USAGE.md](docs/USAGE.md) | руководство по использованию |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | все команды `python -m kit …` и где что лежит |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/PARITY.md](docs/PARITY.md) · [docs/DECISIONS.md](docs/DECISIONS.md) | устройство, сравнение приводов, принятые решения |

<details>
<summary>Обновление оригинального Autopilot</summary>

```powershell
python -m kit check-update   # есть ли новая версия у автора
python -m kit update         # проверит совместимость («швы»), поставит и обновит копию в vendor/
```
Новая версия ставится только после зелёных швов; не обновляйте ядро, пока идёт этап программы.
</details>

## Статус

`claude` — работает; `claude-gate` — проверен живьём частично; `codex` — написан и покрыт тестами, живая проверка оркестратора ещё впереди.
Основная платформа — Windows 11.

## Оригинал и лицензия

- **Autopilot** — [nick-vels/skills](https://github.com/nick-vels/skills), автор Nick Vels, MIT. Копия без изменений — `vendor/autopilot`,
  лицензия автора — [vendor/LICENSE](vendor/LICENSE). Весь процесс разработки (брифинг, спецификация, тикеты, ревью, приёмка, дашборд
  прогона) — его работа; вопросы по самому Autopilot — в его репозиторий.
- **Autopilot Kit** — MIT, [LICENSE](LICENSE).
