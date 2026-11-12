---
name: autopilot-init
description: Use once per project, before /autopilot. Reads the project's documents and folder, detects the stack, installs the autopilot-kit project files (quality gate, rules, permissions) and fills in the test commands itself.
---

# Autopilot project init

You prepare the **current project folder** for Autopilot so the owner does not have to choose templates or
write test commands. Work from the documents and files, ask only what they do not answer.
Answer in the owner's language. Do not start `/autopilot` and do not write product code.

## 1. Find the project and the kit

- The project is the current working directory (the folder the chat was opened in). If it is the autopilot-kit
  repository itself (it contains `kit/` and `pyproject.toml`), stop and tell the owner to open the chat in the project folder.
- The kit location is the single line in `~/.autopilot-kit/kit_path` (PowerShell: `$HOME\.autopilot-kit\kit_path`).
  If the file is missing, tell the owner: «Запустите python -m kit install в папке autopilot-kit» and stop.
  Do not search the disk.

## 2. Read the project

Read, without changing anything:

- the document set: `README*`, `docs/`, requirement/spec/architecture files, anything the owner named;
- the tree down to three levels (skip `.git`, `node_modules`, `.venv`, `venv`, caches; for those only note whether they exist):
  `pyproject.toml`, `requirements*.txt`, `package.json`, `pnpm-lock.yaml`, `go.mod`,
  `Cargo.toml`, `Makefile`, `tests/`, scripts and their imports or usage docstrings (they often name the real run command),
  existing `CLAUDE.md`/`AGENTS.md`/`.claude/`;
- the git state (`git status`, is it a repository).

Decide: language and framework, how to create the environment, how tests are run (or will be run — documents may
describe a stack for code that does not exist yet), whether a virtual environment already exists.

## 3. Install the project files

If `.autopilot-kit/project.toml` already exists the project is initialised: skip to step 4 and only adjust.

Otherwise, with the kit folder as the working directory of the command and an **absolute** project path:

```powershell
$kit = (Get-Content "$HOME\.autopilot-kit\kit_path" -Encoding UTF8 -TotalCount 1).Trim()
Push-Location $kit; try { python -m kit project init --template generic --path "<project>" } finally { Pop-Location }
```

```bash
(cd "$(cat ~/.autopilot-kit/kit_path)" && python -m kit project init --template generic --path "<project>")
```

Show the owner its output. It creates `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json` (permissions + Stop hook of the gate for Claude Code),
`.codex/hooks.json` (the same Stop hook for Codex) and `.autopilot-kit/project.toml`. Files that already exist are never
overwritten: the template lands beside them as `*.kit-new`; `settings.json` and `hooks.json` are merged. If a `*.kit-new` appears, read both files, merge the useful rules into the
owner's file yourself, then delete the `*.kit-new` and tell the owner what you took.
The template's `.gitignore` also keeps `.claude/launch.json` out of git (T21.11): that configuration is
machine-specific (an absolute path to `program.py`) and `program.py page --launch` recreates it on any machine.

## 4. Fill in what the documents imply

Edit only these places, with the smallest change:

1. `.autopilot-kit/project.toml` → `commands`: the checks that prove the project works, run in order, each must exit 0.
   Use the project's own runner: `.venv\Scripts\python -m pytest -q`, `uv run ...`, `npm test`, `go test ./...`.
   Typical: tests, plus lint/type-check if the documents require it. A deterministic validator of the project's data
   or artifacts is a legitimate gate command when the project has no tests (say in the report that it is not a test suite).
   If nothing checkable exists yet, write the command the documents promise (for pytest an empty suite is tolerated by
   the hook) or leave `commands = []`; an empty list means the gate passes without checking anything — say so plainly.
   Keep the `timeout_seconds`; raise it only for a known slow suite.
2. `AGENTS.md` → section «Стек и запуск»: language/version, environment, how to run checks and the app, key folders,
   constraints from the documents. Replace the placeholder comment **and** the line «Не определено…». Write in the
   language of the existing `AGENTS.md`. Mark what you inferred rather than read («по импортам», «догадка»). Keep
   «Стиль», «Готовность» and «Роли Autopilot»; add a stack-specific style line only when the documents state one, and
   reword «Каждое поведение покрыто тестом» only if the project plainly has no code to test.
3. `.claude/settings.json` → `permissions.allow`: for each gate command add its short stable prefix (the runner and
   subcommand, e.g. `uv run`, `npm test`, `.venv\Scripts\python -m pytest`), never the full command with its flags,
   in both forms `Bash(<prefix> *)` and `PowerShell(<prefix> *)`. Skip commands with `&&`, pipes or redirects.
   Do not add anything else and never touch `deny` or `hooks` (nor `.codex/hooks.json`). Codex needs no allow-list
   here: its gate runs from the Stop hook and from the rule in `AGENTS.md`.

**Files:** read with UTF-8 (`Get-Content -Encoding UTF8`) and write UTF-8 without BOM (`[IO.File]::WriteAllText(path, text)`
or your editor tool), never `>` or `Set-Content` without `-Encoding`: the files contain Cyrillic.

Do not create `.venv`, install packages into the project, or run the app. If the environment is missing, say so in
the report. (A gate command that uses a tool's own cache, like `uv run`, may fill that cache — that is fine.)

## 5. Check

- Run the gate once: `python "$HOME\.autopilot-kit\bin\gate.py"` (bash: `python ~/.autopilot-kit/bin/gate.py`) from the
  project folder and show the output. A red gate is acceptable only because code is not written yet — say which.
- If the folder is not a git repository, tell the owner Autopilot commits per ticket and offer `git init` together
  with a `.gitignore` for what you saw (environments, caches, bulky generated files); run them only after an explicit yes,
  and make no commit.

## 6. Report

Short, one line per point: the stack you found and where from (mark guesses); the gate commands you wrote and whether
they are tests or something else; what the permissions got; what you need from the owner; the next steps — open a
**new chat in this folder**, trust the folder when asked (without it the Stop hook of the gate does not run, though the
gate itself still works by hand), then `/autopilot-roles` and `/autopilot semi: <task, link to the documents>`.
In **Codex** the same: a new chat in this folder, trust the project's `.codex/` layer when asked and approve the new Stop hook
once in `/hooks` (Codex skips hooks it has not been told to trust; the rule in `AGENTS.md` still holds the gate), then
`$autopilot-roles` and `$autopilot semi: <task, link to the documents>`.
