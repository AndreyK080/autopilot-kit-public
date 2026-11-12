---
name: autopilot-roles
description: Use together with /autopilot. Assigns models and effort to Autopilot subagents from the user's profile and adds the owner's standing rules (quality gate, telling the user when a run yields documents, not product code, ending a multi-run project's report with the next run's command).
---

# Autopilot roles

This skill is the owner's standing instruction for **which model and effort each Autopilot subagent
runs on**, for the quality gate (§7) and for **saying plainly when a run yields documents, not
product code** (§8) and for **ending the report of a multi-run project with the next run** (§9). It is a command from the user, not background text: follow it whenever the `autopilot`
skill spawns a subagent. It changes nothing in the `autopilot` skill itself — apply it, then continue
with `autopilot` as written.

## 1. Detect the host app

**Owner pin first (T19.8):** if the project's `.autopilot-kit/project.toml` or `~/.autopilot-kit/profile.toml`
has a top-level `drive = "claude" | "claude-gate" | "codex"`, that is the vendor — skip the environment check.

Otherwise run in the terminal (use the shell you have), and print the result:

```powershell
if ($env:CLAUDE_CODE_ENTRYPOINT -eq 'claude-desktop-3p') { 'claude-gate' } elseif ($env:CODEX_THREAD_ID) { 'codex' } elseif ($env:CLAUDECODE) { 'claude' } else { 'unknown' }
```

```bash
if [ "$CLAUDE_CODE_ENTRYPOINT" = claude-desktop-3p ]; then echo claude-gate; elif [ -n "$CODEX_THREAD_ID" ]; then echo codex; elif [ -n "$CLAUDECODE" ]; then echo claude; else echo unknown; fi
```

`claude` → vendor `claude`. `claude-gate` → vendor `claude-gate` — the **Claude Desktop Gate** drive (D48):
Claude Desktop 3p whose traffic goes through the organization's gateway, not an Anthropic subscription.
`codex` → vendor `codex`. `unknown` → stop and ask the owner which app this is.
`ANTHROPIC_BASE_URL` is **not** a drive marker (T19.8): the subscription app sets it too — to its own local proxy.

## 2. Read the profile

- `~/.autopilot-kit/resolved.json` — written by `python -m kit install` / `python -m kit profile set`.
  Shape: `{"<vendor>": {"<role>": {"model": "...", "effort": "..."}}}`. Use the block of your vendor.
- If the project has `.autopilot-kit/profile.toml`, read it too: roles listed there override the global
  ones (`tier` = strong | balanced | fast, `effort`). Resolve a tier to a model through
  `~/.autopilot-kit/models.json` if it exists, otherwise tell the owner to run `python -m kit profile set`.
  This works in Codex only. In Claude Code the agent files hold the global profile and cannot be changed
  per project: if the project has a profile, tell the owner once («Проектный профиль действует только
  в Codex; в Claude Code используется глобальный — /autopilot-setup») and use the agent types as below.
- If `resolved.json` is missing, tell the owner once: «Запустите python -m kit install» — and continue
  with the defaults of the `autopilot` skill.

## 3. Map Autopilot subagents to roles

| Autopilot subagent | Role |
|---|---|
| executor of a ticket (`prompts/executor.md`) | `executor` |
| reviewer for the Manifest and Spec axes (point review, whole-branch review, and the independent coverage checks G2/G3 of the spec and plan) | `reviewer-spec` |
| reviewer for the Craft axis | `reviewer-craft` |
| final review / blind acceptance of phase 8 | `final-reviewer` |

Subagents that are in none of these rows (ADR agent, memory agent) keep the default of the host.
A role's model and effort come from the profile; they replace the model choice the `autopilot` skill
describes for that subagent (for example `model: "sonnet"` on the Agent call).

## 4. Launch with the role

**Claude Code and Claude Desktop Gate** (vendors `claude`, `claude-gate`). Start the subagent with the Agent tool
and `subagent_type: "autopilot-<role>"`
(`autopilot-executor`, `autopilot-reviewer-spec`, `autopilot-reviewer-craft`, `autopilot-final-reviewer`).
These agent files hold the model and effort from the profile. Do **not** pass a `model` parameter.
If the agent type is not found, tell the owner: «Агенты не установлены — запустите python -m kit install,
затем откройте новый чат» — and do not silently use another type.

**Codex.** Start the subagent with `collaboration.spawn_agent` and pass
`model` and `reasoning_effort` from `resolved.json` for the role, with `fork_turns: "none"`
(the app requires a fresh context for these overrides). Put the task in `message`.

## 5. Check yourself (the orchestrator)

The owner chooses your model; you cannot change it. Compare it with the `strong` tier of your vendor
(Claude and Claude Desktop Gate: the Opus family — the gateway maps the alias to its own strong model;
Codex: the model in `resolved.json` for `final-reviewer`). If you are weaker,
say so **once** in one line («Оркестратор не на сильной модели — качество планов может быть ниже»)
and continue.

## 6. Host switch

Keep the vendor in `.autopilot-kit/last_host` of the project (create the folder if needed). If it
differs from the vendor you detected, do not reuse any subagent or reviewer Autopilot remembers
from the previous app — create them anew — and then write the new value.

## 7. Quality gate

If the project has `.autopilot-kit/project.toml`, run before saying «готово» for a ticket and
before the final report:

```
python "%USERPROFILE%\.autopilot-kit\bin\gate.py"
```

(on bash: `python ~/.autopilot-kit/bin/gate.py`). Show its output. Exit code other than 0 means the
work is not done: fix and run it again. If the file does not exist, skip this step.

## 8. Run deliverable: product code or documents only

The user expects Autopilot to build a product. A run whose task is to write documents (plans, specs,
analysis, research) must say so at every place the user looks, or they take the stage «Разработка» and
the commit «Autopilot: сборка сдана» for a finished product.

**Decide once, in Phase 0, before the opening block**, from the brief and the files it points to (a
start prompt, a handoff document):

- `docs` — the task says the result is documents, not code: «не код», «без кода», «ожидаемый
  результат — не код», «только план / спецификация / анализ / исследование», "planning artifacts",
  "no code yet" — or every output it asks for is a document.
- `code` — everything else, including a task that asks for code and documents together.
- Unclear → in `semi`, `interview`, `manual` ask one line in the opening block («Этот прогон пишет код
  продукта или только документы?»); in `full` choose what the task text supports and say which.

Keep the decision in the state: `python3 .autopilot/ap.py set deliverable=docs` (or `code`) right after
`init`. On resume, read `deliverable` from `state.js`; if it is missing, decide again as above.

For `code` nothing changes. For `docs`, in every mode:

1. **Opening block, first line, verbatim:** «В этом прогоне пишутся документы, код продукта не
   появится; разработка кода — следующим прогоном.» The next line names the documents that will be
   written.
2. **Dashboard.** `ap.py init --title "Документы: <что пишется>"`. Open the stages with notes:
   `stage build --note "Пишутся документы, код продукта не пишется"`,
   `stage review --note "Ревью документов, не кода"`, `stage final --note "Приёмка документов"`.
   When Phase 5 starts, say in the chat once: «Этап «Разработка» на дашборде — это написание
   документов, не кода.»
3. **Final report, first line, before «## Готово»:** «**Готовы документы, не продукт.** Есть: <какие
   документы>. Кода продукта нет — пользоваться пока нечем. Следующий шаг: <что запустить дальше,
   например следующий прогон Autopilot с кодом>.» No «Запустить» block for a product that does not
   exist; the commands that check the documents go under «Проверить документы».
4. `ap.py finish --result "Документы готовы, кода продукта нет: <какие>"`.
5. `.autopilot/PROGRESS.md`: the line «Последняя сборка» ends with «— документы, кода продукта нет;
   следующий шаг — <…>».
6. The landing commit keeps its subject «Autopilot: сборка сдана» (runs and sessions find the landing
   by it) and gets a body line: add `-m "Сданы документы, кода продукта нет. Следующий шаг: <…>"`
   after the subject.
7. Tell the memory agent that the project has no product code yet, so the memory file does not
   describe a product that can be run.

## 9. Multi-run project: the report ends with the next run

The owner's words: «при многоэтапном проекте итоговый отчёт заканчивается готовой командой следующего
прогона и списком решений, нужных до него». A user new to Autopilot does not know what to type after
a run lands.

**It applies** when the project is built in more than one run: the plan has stages or milestones
(M1 → M2 …, waves, «этап»), the task is bigger than one run, or this run left work for a next stage
(deferred requirements, work packages for later, a `docs` run from §8). A single run that delivered
everything asked skips it.

1. **The final report ends with the section «## Следующий шаг»** — the last section, after
   «Где что лежит». In it:
   - a paste-ready command in its own code block, the two messages in order:

     ```
     /autopilot-roles
     /autopilot <режим>: <задание следующего этапа> — по плану `<файл плана>`, раздел «<этап>»
     ```

     `<режим>` is the mode of this run unless the user asked otherwise; the task names the next stage
     and the plan file and section it comes from, so a new chat can start from it without this one.
     One line under the block: «Открой новый чат в папке проекта и отправь эти две строки по очереди».
   - **«Что нужно от тебя до запуска»** — a numbered list of the decisions and data the next run needs
     from the user: owner-question IDs from the plan (`OQ-01` …), accounts, access, files, data. Each
     item says what happens if it is not given: «без ответа — следующий прогон остановится на
     брифинге» or «без ответа — возьму допущение <какое>, его можно поменять». Nothing needed → one
     line «Ничего — можно запускать».
2. **`.autopilot/PROGRESS.md` gets the same section «## Следующий шаг»** — the command block and the
   list, written from the same files — so a plain session or the next run finds the command without
   the report.
3. The command's task text is never invented beyond the plan: it quotes the plan's name for the next
   stage. If the plan does not say what comes next, the section says so and asks the user one line.
