# Autopilot Kit — правила для агента, работающего с репозиторием

Надстройка над [оригинальным Autopilot](https://github.com/nick-vels/skills) (автор Nick Vels, MIT) для Claude Desktop/Code, Codex и
Claude Desktop с гейтвеем организации. Одна ветка `main`, одно ядро, три привода — см. [docs/DRIVES.md](docs/DRIVES.md);
чем kit отличается от оригинала — [docs/DIFF_FROM_UPSTREAM.md](docs/DIFF_FROM_UPSTREAM.md).

## Если тебя просят установить kit

Читай раздел «Установка силами другой LLM» в [docs/DRIVES.md](docs/DRIVES.md) и следуй протоколу. Коротко: `python -m kit install`,
`python -m kit profile set --drive <claude | codex | claude-gate>`, `python -m kit doctor` (нужен `FAIL 0`). Привод не угадывай —
спроси владельца, если окружение неоднозначно.

## Запреты

- Не использовать API OpenAI/Anthropic и не задавать API-ключи (исключение — гейтвей организации в приводе `claude-gate`: его
  настраивает организация, kit ключей не задаёт и не печатает).
- Не менять файлы оригинального Autopilot (`~/.claude/skills/autopilot`, `~/.agents/skills/autopilot`): kit ставит их без изменений и
  откажется перезаписывать правленые (`LOCAL_CHANGES`).
- Не пушить в удалённые репозитории без просьбы владельца.
- Не расширять объём работы: идеи — одной строкой в `docs/DEFERRED.md`.

## Техника

- Python ≥ 3.11, только стандартная библиотека; тесты — `python -m pytest -q` (нужен `pytest`).
- Тесты не трогают реальный домашний каталог: `tmp_path` и переменная `AUTOPILOT_KIT_HOME`.
- Файлы пользователя вне репозитория меняются только с резервной копией `.bak-<UTC>`; JSON-настройки сливаются.
- Основная платформа — Windows 11; на других ОС не проверялось.

## Документы

[docs/DRIVES.md](docs/DRIVES.md) · [docs/DIFF_FROM_UPSTREAM.md](docs/DIFF_FROM_UPSTREAM.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
[docs/OPERATIONS.md](docs/OPERATIONS.md) · [docs/PARITY.md](docs/PARITY.md) · [docs/DECISIONS.md](docs/DECISIONS.md).

Репозиторий собирается из приватного источника командой публикации; правки в нём принимаются как предложения (issue или pull request)
и переносятся в источник вручную.
