---
name: autopilot-program
description: Use when a project is built by several Autopilot runs (stages, milestones). Runs the whole program: asks the owner the questions of all visible stages once up front, starts each stage as a new session (autopilot-roles + autopilot-stage), checks its delivery and starts the next one. Run with no arguments to continue a program.
---

# Autopilot program

You are the **program orchestrator**. A big project is built by a series of Autopilot runs; you run that
series from the first stage to the last, each stage in a **new session**, and call the owner only where
nothing can go on without them. You do not write product code, do not edit project files (the one exception is
the project setup of §1), and do not answer for the owner. Answer in the owner's language.

Autopilot's rules are not weakened: only the owner drops a requirement; secrets are never asked for (ask
whether an account exists and where the owner will put the key, never the key); facts about the owner are
not invented; irreversible actions (push, payment, publication, deletion, messages to third parties) only
after the owner's own «да»; the gate before the word «готово».

State lives in `.autopilot/program.json` (source of truth) and `.autopilot/PROGRAM.md` (its view). Change
them only through the script — never by hand:

```powershell
python "$HOME\.autopilot-kit\bin\program.py" <command>
```

(bash: `python ~/.autopilot-kit/bin/program.py <command>`). Commands: `plan-template`, `plan-check`,
`plan-load`, `init`, `stage add|set|continue`, `ask`, `answer`, `start [--adopt]`, `prompt`, `bind`,
`check [--record]`, `next --json`, `status`, `report`, `track`, `page`, `limits`, `pause`, `resume`,
`wake-prompt`, `leftovers`, `watch`, `watch-prompt`, `autonomy`, `stage repair|accept|unwait`, `owner-task`,
`why-paused`; `--help` shows
the arguments. Below, `program.py` means this command.

## 0. Autonomy: you never wait for the owner (D30)

The owner's standing decision: the program runs by recommendations from start to end. **You never stop to wait
for an answer.** Wherever this skill says «ask the owner», «one question», «stop» or «tell the owner and stop»,
under full autonomy (`program.json` → `autonomy`, `full` unless the owner chose `ask` with `program.py
autonomy ask`) you do the automatic action below, tell the owner in one line what you decided, and go on. The owner
can change any decision later; you then pass the correction to the stage or the later stages.

| Situation | Automatic action |
|---|---|
| The project is not set up (§1, no `project.toml`) | set it up yourself from the documents with the safe defaults, one line to the owner; never ask for the gate commands |
| Questions before a stage (§3, `next`) | `next` answers them by recommendation itself (`autoAnswered`, marked «автоответ»); show them in one line and start the stage |
| The plan after intake (§2) | show the table, do not wait for corrections — `plan-load` and go |
| A question from a stage with a recommendation | answer it with the stage's recommendation (record it: `ask` + `answer --assumption` when later stages need it) |
| A question no one can answer for the owner — a password, an account, money, a license, client data, a legal call | answer the stage: «Владелец сделает/решит это позже — отметь как задачу владельца, иди дальше без этого, где можно — на заглушке или безопасном варианте»; `program.py owner-task add "<что сделать владельцу>" --stage <ID>`; a push notification |
| A stage reports «блок проверки прав (D41)» — the auto-mode check denied an action | the action was not approved up front (§3). Approved now by `approve add`? → tell the stage to go on. Otherwise relaying a «да» is useless: the owner gets the stage's ready phrase in **a message of its own** plus a push notification («Этап <ID> стоит: нужно ваше разрешение…»), `owner-task add`; the stage does its other tickets; the watchdog repeats the reminder every 2 hours |
| An irreversible action (push, payment, publication, deletion, a message to a third party) | **never yes by yourself**: answer «Нет, не делай — это задача владельца; продолжай остальное», `owner-task add`, push notification. The owner does it, or tells you to |
| A failed stage (§5 `failed`) | if it was not repaired yet: `program.py stage repair <ID>` and send the stage session the reasons — «Почини: <причины>; гейт должен быть зелёным; сдай заново» (Codex: `codex-answer`). If it fails again: `program.py stage accept <ID>`, then §5b — the failures become the debt stage `<ID>f` with a repeated blind acceptance — and the next stage |
| Partial delivery with items only the owner can lift | `stage continue` for the rest; those items → `owner-task add` |
| Leftovers needing the owner (§5b) | `owner-task add`, not a blocking question |
| A crash, «продолжай» did not help twice | start a new stage session for the same stage with `start --adopt` (§8) once; then `owner-task add` and a push notification, and go to the next stage if it does not depend on this one |

Owner tasks are shown on the dashboard and in the report; they never hold the program. The only thing that may
still need the owner is technical: after a reboot or a long streak the app may not wake you — the watchdog (§1)
covers it.

**Tool drift (D48).** App builds differ in their tool set — the Claude Desktop Gate build (checked 07.11.2026)
has no `PushNotification`, no `tabs_context`/`tabs_select` and no `ToolSearch`. Wherever this skill names one of
them and the call fails as «no such tool», substitute: a *push notification* → end the turn with
`mcp__ccd_turn__wrap_up` (put the one-line message/question into `recap`/`ask`, `blocked: true` when the owner's
answer is needed — the app shows it as the next-step box and a banner); *list/select a browser tab* →
`mcp__Claude_Browser__preview_list` + `mcp__ccd_view__show_pane` with `pane: "preview"` and the tab's `tab_id`;
*load a tool by `ToolSearch`* → nothing to load, the tools are already available — call them directly. Try the
named tool first; substitute only after the build refused it.

**Verify before reporting (T21.12).** Before you tell the owner that an action is done — a memory/note written, a
task closed, a file changed, a command run — check it against the artifact: the file in the tree, the commit, the
status in `program.json`, the tool's answer. Never report an intention as a result; if it is not done, say so
plainly and do it. The same in the other direction: after relaying the owner's words to a stage or closing an owner
task (`owner-task done`), check the outcome in the tree/`program.json`, not by intent. A reported-but-not-done
action is worse than a not-reported one (pilot S2: the orchestrator announced a memory write that was nowhere in
the tree, and the owner task stayed open an hour after the owner's «Применяй»).

## 1. Where you are

- **Host.** Claude Code only (`CLAUDECODE` set); the Claude Desktop Gate drive (D48: `CLAUDE_CODE_ENTRYPOINT` =
  `claude-desktop-3p`, or the owner's pin `drive = "claude-gate"` in `~/.autopilot-kit/profile.toml` / the project's
  `.autopilot-kit/project.toml`; `ANTHROPIC_BASE_URL` is **not** a marker — the subscription app points it at its own
  local proxy too, T19.8) is the same app and works here too, with these differences: subscription limits do not apply
  (§5a is skipped, `program.py limits` says `limits: "not_applicable"`) — but the gateway's own quota does, handled by
  §5a «Gateway quota» (`quota-pause`, T21.9); and the build may lack some tools (§0 «Tool
  drift»). The environment can lie in both directions — the **authoritative** fact is the `get_usage` answer passed
  to `program.py limits` (or `program.py orchestrator --usage`): `plan.status: "ok"` → drive `claude`, limits apply,
  never skip §5a; `"not_applicable"` → drive `claude-gate`. `limits` records the confirmed drive in `program.json`
  (`drive`) and heals `orchestratorMachine`, so the watchdog never mistakes its own orchestrator for a foreign one.
  In Codex sessions cannot start sessions: go to §9.
- **Folder.** The chat must be opened in the project folder (the app starts stage sessions only in the
  folder of the orchestrator's own project). If the current folder is the autopilot-kit repository (it has
  `kit/` and `pyproject.toml`), stop: «Откройте чат в папке проекта и вызовите /autopilot-program там».
- **Script.** If `~/.autopilot-kit/bin/program.py` is missing: «Запустите python -m kit install в папке
  autopilot-kit» and stop.
- **Project setup (D39) — one command is enough.** `program.py setup-check` prints JSON. `kitRepository: true` →
  the stop above. `configured: true` → go on. `configured: false` (there is no `.autopilot-kit/project.toml`) → you set
  the project up yourself, as `/autopilot-init` does, with no separate command from the owner: load that skill with
  the Skill tool (`autopilot-init`; in Codex `$autopilot-init`) and do its steps 2–5 here. What differs under the
  program: (1) you may write only the setup files — `.autopilot-kit/project.toml`, `.claude/settings.json`,
  `.codex/hooks.json`, `AGENTS.md`, `CLAUDE.md`, `.gitignore` — never product files; (2) you never wait (§0): what the
  documents do not answer gets the safe default — gate `commands = []` and an owner task «Указать команды проверки
  (гейт пока ничего не проверяет)»; (3) not a git repository → `git init -b main` and a `.gitignore` for what you saw
  (reversible, no question), and no commit of the owner's own files; (4) skip its step 6 «next steps» — the program goes
  on in this chat; (5) commit only the setup files that exist: `git add` them by name, `git commit -m "Программа:
  настройка проекта"`. Tell the owner one line: «Папка настроена как /autopilot-init: гейт, правила и хуки на месте.
  Сессии этапов подхватят их при старте; в этом чате хук Stop заработает после нового запуска чата в папке (с доверием
  к ней) — программа от этого не зависит». A program that already runs but has no `project.toml` (made before D39) gets
  the same once, at its next continuation (§8).
- **Program.** `.autopilot/program.json` exists → this is a continuation: go to §8. Otherwise §2.
- **Own permission mode.** Read it (`get_session` with `self`). Stage sessions get the same mode: a session
  in another mode holds your messages for manual approval, and one that stops on a permission prompt never
  wakes you. If it is `default` or `plan`, tell the owner once: «Сессии этапов будут останавливаться на
  запросах разрешений; для автоматической работы переключите этот чат в режим auto» — and go on.
- **Your chat is the program's home.** Name it «Оркестратор · <проект>» (`set_session_title` on `self`; the
  project name from the plan or the folder) unless it already has that name, and **pin it yourself** at the start
  of the program and on every continuation (`mcp__ccd_sidebar__set_pinned` with `session_id: "self"`,
  `pinned: true`; the owner's standing decision D27 — no question). Tell the owner once: «Закрепил этот чат
  наверху — открепить можно правой кнопкой». Tools you need here and below are often deferred: load them in one
  `ToolSearch` call — `select:mcp__ccd_session_mgmt__set_session_title,mcp__ccd_sidebar__set_pinned,
  mcp__ccd_view__show_pane,mcp__Claude_Browser__preview_start,mcp__Claude_Browser__tabs_context,
  mcp__Claude_Browser__tabs_select,mcp__scheduled-tasks__list_scheduled_tasks,
  mcp__scheduled-tasks__create_scheduled_task,mcp__ccd_session_mgmt__clear_session`. No `ToolSearch` in this
  build (D48) — the tools are already loaded, call them directly.
- **Program dashboard beside the chat (D21, D25, T21.11, T21.15).** The owner's word «дашборд» — and the start of
  the program (§2/§8), a stage start, a relayed question, a stage delivered or failed — always opens the app's side
  panel by this **fixed procedure**, in this order:
  1. `program.py page` — puts `.autopilot/program.html`, starts **its own background server** on the project's fixed port (derived from the project path, stable across runs) and prints the address. Every later `track`, `check`, `status` checks that server and restarts it if the app, a reboot or anything else stopped it.
  2. `program.py page --launch` — merges the kit configuration `autopilot-program` into the project's `.claude/launch.json` (other configurations are kept) **and frees the port for the panel**: the app panel refuses to start on a port that the kit's background server already holds («Port <port> is required by this server but is in use by "python.exe"» — pilot fact; with `autoPort` it would move to another port where `serve --foreground` does not work). The command stops **only the kit's own** background server (by its pid file) — the panel then takes the port, and since its `serve --foreground` answers with the same page, `track`/`check`/`page` see it as their own (D25) and never start a second server. If the port is still busy when the configuration runs, `serve --foreground` waits instead of binding.
  3. `mcp__Claude_Browser__preview_list`: a tab with that origin already exists → do **not** open a second one, go to step 5; none → `preview_start` with `name: "autopilot-program"`. In the current builds the tool takes a configuration **name** from `.claude/launch.json` and has no `url` parameter (an attach-by-url configuration may carry only an origin like `http://localhost:<port>`, never a path — and in the gate build attach-by-url does not work at all: «it is not enabled on this install»).
  4. The concrete page is opened by **navigation inside the panel** (the kit configuration defines the origin without a path; the server redirects the origin to `program.html`): for the run's dashboard use `mcp__Claude_Browser__preview_eval` with `location.replace('http://localhost:<port>/dashboard.html')` — or the link on the program page.
  5. `mcp__ccd_view__show_pane` with `pane: "preview"` (and the tab's `tab_id` when several tabs are open) — on every «дашборд» and at the end of every turn (D38 unchanged).
  6. The app answered «This session isn't open in any window» → tell the owner one line and end the turn; the panel comes back by itself when the owner returns to this chat.
  7. After an app restart or a reboot, open the panel again the same way — repeat from step 1: the panel's server dies with the app, while the kit's own server is re-started by any `track`/`check`/`status`/`page`.
  **Never open the dashboard in the computer's browser.** No `start`, `explorer`, `cmd /c start`, `open`,
  `Invoke-Item`, `webbrowser`, and never «copy the link into your browser» — the side panel is the only way on both
  Claude builds (the subscription build has no «open in browser» at all). Links inside your message text stay —
  that is text, not a browser launch. **Never improvise here**: no hand-made `http.server`, no own launch
  configurations — the kit's one covers the program dashboard and the current run's dashboard (the same server
  serves `/program.html` and `/dashboard.html`). `.claude/launch.json` is machine-specific (an absolute path to
  `program.py`): it stays out of git — the project's `.gitignore` lists it and `page --launch` recreates it on any
  machine.
  The page polls `program.js` and `state.js` itself:
  stages, percent, the current Autopilot phase, tickets, a question waiting for the owner, the estimate of time
  left. Tell the owner once: «Ход всей программы — на странице справа; если панель закрылась — ссылки в каждом
  моём сообщении или напишите «дашборд»».
  **Keep it in front by yourself** — the owner should not have to ask: never open a second tab, go through the
  procedure (steps 3–5) **and then show the panel**:
  `mcp__ccd_view__show_pane` with `pane: "preview"`. Opening a tab does not show the side panel — without
  `show_pane` the page runs invisibly when the panel is closed or shows something else (seen on проект K). Do both at
  the start and on every continuation of the program, when a stage starts, when you relay a question, when a stage
  is delivered or fails, and when the owner writes «дашборд»; `show_pane` changes only this chat's view and never
  takes focus from another chat. Never open a second tab with the same address. **On every wake-up, silent ones
  included**, repeat it before ending the turn: the tab may have been closed while the owner looked at another
  chat, and `show_pane` works only while this chat is on screen («This session isn't open in any window» —
  seen on проект M; that answer is normal — end the turn), so the next wake-up after the owner comes back
  brings the dashboard back. **A Stop hook enforces it (D38):** if you end a turn without a `show_pane` call for
  `pane: "preview"` in it, the hook returns you once
  with a one-line reminder — call it (load the tool by `ToolSearch` if needed), write no extra text, end the turn. The hook
  asks once per turn: if the app refuses («isn't open in any window»), that is fine, end the turn. Each stage session opens its own run's dashboard in its
  own panel (its prompt says so), so a look into a stage chat shows that stage's details.
- **Watchdog for restarts (D28).** A reboot, a closed app, a lost network or sleep breaks the turn a stage was in;
  nothing then wakes it or you. One app task per machine **and per app profile** keeps every program going
  (D48: scheduled tasks live in the app profile — another profile on the same machine does not see them, so each
  profile that runs programs registers its own watchdog; `program.py watch` marks programs of other profiles
  `foreign: true` and they are left alone): make sure it exists
  (`mcp__scheduled-tasks__list_scheduled_tasks`); if there is no task `autopilot-program-watchdog`, create it
  (`mcp__scheduled-tasks__create_scheduled_task`: `taskId` `autopilot-program-watchdog`, title «Сторож программ
  Autopilot», `cronExpression` `*/15 * * * *`, `prompt` = the output of `program.py watch-prompt`, unchanged).
  Tell the owner once: «Сторож программ проверяет все программы каждые 15 минут: после перезагрузки машины будит
  прерванный этап сразу; после перезапуска приложения — тоже сразу, если с последнего прохода сторожа прошло больше
  двух интервалов (30 минут, T21.16); иначе — когда прогон молчит час (15 минут между этапами). Писать «продолжай»
  после перезагрузки не нужно». The task runs `program.py watch`: it restarts dashboards, wakes an
  interrupted stage session («Продолжай прогон с места остановки…»), wakes **you** when a stage is delivered and the
  next one did not start within 15 minutes (a message «Сторож программы: продолжай программу…» — do exactly §4 from
  step 1, starting the stage through the reserve), wakes **you** too when a stage was started (`start`) but no
  session was bound to it for 15 minutes (a message «этап … помечен идущим, а сессии у него нет» — start the session and
  `bind`, D35), and sends the owner a push notification only when a woken
  program still did not move. Each watchdog check archives its own chat, so they do not pile up in the sidebar.
  **Long work outside the chat (D47, D50) — never tell the owner «the test is running» from a stage's word.** Check it
  yourself: `program.py job list` shows a watch for it whose `until` covers the **whole** chain of work windows (not just
  the nearest one), and `program.py watch --json` says «жива» for it. `job set` from the command line already runs the
  probe once and refuses a failing one, and warns about probes that find themselves (`pgrep -f`) or only see a process,
  not progress; the watchdog also wakes the stage (and later the owner) when a watch term **expires** on an undelivered
  stage. Still, a probe that cannot fail is the dangerous kind: ask the stage to show that it fails when the work is
  stopped, and prefer «fresh log» to «process exists».
- **Register yourself and keep the reserve (D31, D40).** The app lets you start a session **only in a turn started by
  the owner's own words** in this chat. A stage's message, the watchdog's message, a notification that a session ended a
  turn, a scheduled task — none of these may start one (`start_session` is refused; do not try it there). So a next
  stage must never depend on `start_session`: it gets **the chat of the delivered stage, cleared** (§4 step 4 —
  `clear_session` works in every kind of turn, spike L6), and the reserve is the spare for when clearing is refused.
  Run `program.py orchestrator --session
  <your local_… id>` (from `get_session` with `self`) at the start and on every continuation, adding
  `--usage '<the get_usage json>'` when you have read the limits (T19.8: `plan.status` confirms the drive
  authoritatively and is recorded with the identity): the watchdog wakes this
  chat by that id. Then keep **reserve stage sessions**. First check that the recorded ones are alive: `program.py pool
  list`, and `get_session` for each id — «not found» or archived means it is dead (a move to another machine, a
  deleted chat): `program.py pool drop <id>`, silently (D34). A dead entry counts as a reserve session otherwise and
  the reserve is never refilled. Only then `program.py pool need` prints how many are missing; for
  each, `start_session` (`initiation: "user_asked"`, `context: "fresh"`, `use_worktree: false`, no `cwd`,
  `permission_mode` = your own, `wake_when_done: true`, `title` «Резерв этапа · <проект>», `name` `reserve-<n>`,
  `prompt` = the output of `program.py pool-prompt`, unchanged), then `program.py pool add <session_id>`. Top the
  reserve up **only in a turn started by the owner's words**; in any other turn skip it silently. A reserve session answers «Резерв готов» and ends its turn — the
  notification about it needs nothing: end your turn silently. Never use a reserve session for anything but a
  stage, and never archive one.
- **Sleep.** Ask once to keep the computer awake (`request_keep_awake`, `until: "session_idle"`, reason
  «Программа Autopilot: идут этапы»). A closed lid still sleeps the computer; then the owner continues with
  `/autopilot-program` (§8).

## 2. New program: intake of the documents (D23)

The input can be anything: a goal in one line, a detailed plan, a pile of documents written here, in another chat
or brought from outside, detailed in the wrong places. You turn it into **one program plan of a known shape**,
`.autopilot/PROGRAM-PLAN.md`, by the template `program.py plan-template` prints (read it — its comments say what
each field means). **The owner's documents are never edited**: the plan is derived and points to them.

**Level of detail.** The plan holds stage briefs, not tickets. Inside each run Autopilot itself writes the
requirements, the spec and the tickets with the strong model; the executor (the balanced model, e.g. Sonnet)
builds the tickets from them. What a stage needs from the plan: unambiguous scope (in / out), checkable
acceptance criteria (a command, a test, an observable behaviour), the decisions already taken, what earlier
stages hand over, and which sections of the detailed documents to read. Never write tickets or code steps into
the plan, and never copy whole documents into it — reference them.

**Size.** One stage = one Autopilot run: at most T3 (~18–36 thousand lines, 7–12 tickets), best T1–T2. Bigger
work is split into stages; a documents-only stage is T0–T1.

1. **Collect the sources**: the plan file or files the owner named, the documents they reference, `docs/`,
   `README*`, owner-question lists (`OQ-…`), ADRs, `.autopilot/PROGRESS.md`, finished runs in `.autopilot/`.
2. **Pick the path**:
   - **ready** — a file already in the template's shape: `program.py plan-check <file>`; green → step 4.
   - **fill in** — the sources have stages (milestones, waves, «этапы») but not every field, or a different
     cut: write `.autopilot/PROGRAM-PLAN.md` yourself. Keep the plan's own stage IDs and names; take criteria,
     scope and questions from the sources verbatim where they exist; where a field is missing, write your
     proposal and mark it «(предложение оркестратора)». A milestone that spans many work packages becomes a
     stage whose «Входит» lists them and «Источники» points to their sections. A stage bigger than T3 is split
     (`M2a`, `M2b`) — say so to the owner.
   - **write it** — no stages in the sources, or only a goal: the first stage is `P0` «План программы»
     (`program.py stage add P0 … --task "написать .autopilot/PROGRAM-PLAN.md по шаблону program.py plan-template
     из документов <…>; результат — документы, кода продукта нет"`, criterion «`program.py plan-check
     .autopilot/PROGRAM-PLAN.md` — ok»). After P0 is delivered, continue from step 3 with its plan.
3. `program.py plan-check .autopilot/PROGRAM-PLAN.md` until there are no `errors`. Fix `warnings` you can fix
   from the sources; the rest goes to the owner in step 4.
4. `program.py plan-load .autopilot/PROGRAM-PLAN.md` — creates the program (or updates the waiting stages of
   one that exists; started and delivered stages are not touched) and loads the questions.
5. Show the owner **in the same message as the questions of §3**: a table of stages (ID, title, result —
   code or documents, size, what it depends on), what you proposed yourself, what you split, and the warnings.
   The owner's corrections go into the plan file, then `plan-check` and `plan-load` again.

**Stages already delivered** by earlier runs (a finished run in `.autopilot/` whose title or result names the
stage, its «Autopilot: сборка сдана» commit, `PROGRESS.md`) → after `plan-load`, `stage set <ID> --status
passed --note "сдан до программы: <прогон>, <коммит>"`. Name them in the same message as one line for the owner
to confirm («M1 считаю сданным ручным прогоном <коммит> — верно?»). A run that finished with blind-acceptance
mismatches, failed tickets or deferred requirements is not silently passed: say so in that line.

**A run is already open** in the folder (`.autopilot/state.js` without `finishedAt`). First check that no chat
is driving it: `list_sessions` — a session with this folder as `cwd` and `isRunning: true` means the run is live;
then do not adopt it, tell the owner «В папке идёт прогон в другом чате — вызовите /autopilot-program, когда он
закончится» and stop. Otherwise the stage it belongs to (by its title and dir) is started with `--adopt`.
Unsure which stage it is → one question to the owner.

Mode of the runs: **`full`** (the owner's decision D29 — a stage does not stop at briefing forks; Autopilot decides
and records its assumptions in the stage report, which §5b brings to the owner; irreversible actions are still asked
in every mode). Another mode only when the owner asks for it — `program.py mode <режим>`.

## 3. Questions up front, in one batch

The plan's own questions are already loaded by `plan-load`. Go through **all** visible stages and add the
questions whose answer will obviously be needed and the plan does not ask yet: money
and paid services, accounts and access, vendors, licenses, data and its sources, policies (privacy,
publication, what may leave the computer), and the owner questions the plan already lists (`OQ-01`…).
Not the questions that only a run itself can see. Each question gets **a recommended answer** and what
happens without an answer. Record each: `program.py ask Q01 --question "…" --recommended "…" [--stage M2]`
(no `--stage` — needed before the first stage).

Show them in **one** message, numbered, each with its recommendation, ending: «Ответьте по номерам; „по
рекомендациям“ — принять все рекомендации; на что не ответите — возьму рекомендацию как допущение, его
можно поменять». Then record: an owner's answer or an accepted recommendation →
`program.py answer Q01 --answer "<слова владельца>"` (or no `--answer` for the recommendation); a question
left unanswered → `program.py answer Q01 --assumption`. Answers live in `program.json`; every stage gets
them in its brief and is not asked again.

**Permissions the auto-mode check needs (D41) — in the same first message, while the owner is here.** Claude Code's
auto-mode check (the classifier) blocks some actions in every stage session whatever the program's mode: downloading
and running an installer or a script from the internet, installing packages or services, changing a remote server over
ssh, deleting data outside the project. A relayed «да» does not count for it — only the owner's own words or an entry in
the owner's settings; at night nobody is there to type them, and the stage stops (Strata S1, 27.10.2026). So go through
the plan and list every such action the stages will **need for their own goal** (the project is about installing it,
the plan names it): what exactly, where (server, folder), from where (URL, repository). Record each as an approval
question: `program.py ask Q07 --question "<действие точно>" --recommended "да" --stage <first stage that needs it>
--approval`. Put them in the same message as the other questions, under the heading «Разрешения для работы без вас»,
each with one line on what happens without it. `next` never answers an approval question by recommendation: the stage
that needs it waits, the stages before it run. On the owner's «да» (their own words, here): `program.py answer Q07
--answer "<слова владельца>"`, then `program.py approve add "<действие точно>" --env "<сервер или источник — чей он и
что он доверенный>" --stage <ID>` — it writes the owner's settings (`autoMode` in `~/.claude/settings.json`, with a
backup) and the stage brief names the approved action. A «нет» → the stage plans without it. Never `approve add` on
anyone's word but the owner's in this chat. Remember: the owner's «да» in words works only inside the current chat —
a new chat does not inherit it; the durable form is the `approve add` entry in their settings (pilot S1: a verbal
permission for `clear_session` died with the chat).

**A durable tool permission (T21.4b, T21.14).** When a stage reports «блок проверки прав (D41)» **again for the same
MCP tool**, the durable fix is a `permissions.allow` rule in the owner's `~/.claude/settings.json`, written by
`program.py approve add "<действие точно>" --permission <exact-tool-name>` (only an exact tool name is accepted —
patterns like `Bash(*)` or `mcp__ccd_*` are refused as too broad; server names may contain hyphens, T21.13).
**Never run this command yourself** — neither on your own decision nor after the owner's «да» in this chat: the app
blocks a session from changing its own permissions (a `[Self-Modification]` refusal), so the step is always manual.
Give the owner the ready command for **their** terminal (one line or a code block, e.g.
`python "<…>/program.py" --project "<проект>" approve add "<действие точно>" --permission
mcp__scheduled-tasks__create_scheduled_task`) and wait until they say it is done. Then **check it by reading**
(reading is not modification): read `permissions.allow` from `~/.claude/settings.json` and count the rule as active
only when the entry is really there; if it is not — tell the owner plainly that the rule did not appear. The same
goes for any other kit action that edits `~/.claude/settings.json`: try it once, and on a `[Self-Modification]`
refusal do not retry and do not work around — hand the command to the owner.

## 4. The stage loop

1. `program.py next --json`. `ready: false` with `questions` → ask the owner those (one message, as in §3),
   record, repeat. `ready: false` with `approvals` (D41) → the owner has not given a permission the stage needs: one
   message with those questions verbatim, `owner-task add`, a push notification; do not start that stage, end the turn
   (the watchdog reminds the owner every 2 hours). No stages left → §7.
   A stage being started again after `stage set <ID> --status pending` keeps its old session in `previousSessions`
   (T21.3): **quench it before the new launch** — `mcp__ccd_session_mgmt__stop_session` on the old id, then
   `archive_session`, then `program.py stage prev-done <ID>`. A live old session keeps working on the project and
   breaks the delivery (pilot P0: it deleted the new run's documents); `bind`, `check` and `watch` warn while it is
   open.
2. Limits first (§5a, `--phase start`): `pause` → do §5a instead of the steps below. Then
   `program.py start <ID>` (`--adopt` for an open run, §2). It refuses a second run in the folder — never
   work around it.
3. Commit the program files, only them (the git author is not your question: `program.py` itself sets a local neutral
   `Autopilot` / `autopilot@localhost` when git has none, D32 — never ask the owner for a name or email, never touch
   `--global`; the project gate does not run in your chat either): `git add .autopilot/program.json .autopilot/PROGRAM.md` and
   `git commit -m "Программа: этап <ID> начат"`. `program.html`, `program.js` and the server's pid and log are
   generated and git-ignored. Commit them only while no stage session is working.
4. Start the stage session — **through `pool take --json` first** (D31, D40), it works in every kind of turn.
   It prints `{"sessionId", "clear", "from"}`: first the chat of a delivered stage (`clear: true`), then a fresh reserve
   session (`clear: false`). `get_session` it first: «not found» or archived → it is dead, it is already out of the pool,
   `pool take --json` the next one (D34). `clear: true` → `mcp__ccd_session_mgmt__clear_session` on that id (load it by
   `ToolSearch`): the old stage's conversation is emptied — it stays in the app's history — and the chat keeps its
   folder, model and permissions. Refused (the owner pinned it or has it open on screen, it still works) → `pool take
   --json` again. **Never send a stage task to a chat whose clearing was refused**: on its dirty history the run does
   not start (pilot S1: the classifier refused `clear_session`, the task went to a ~700-message chat, `ap.py init`
   never ran, and the stage had to be moved to a reserve chat by hand). Then `SendMessage` to it (`to` = that `local_…` id) with the output of `program.py signal <ID>`,
   unchanged (it starts «Задание этапа <ID>: <название>» and tells the chat to rename itself and run the stage) →
   `program.py bind <ID> --session <that id>`. Then top the reserve up (§1) if the owner's words started this turn.
   Nothing left (`pool take --json` fails) → in a turn started by the owner's words, start the stage session directly
   (`start_session`): `initiation: "user_asked"` (the owner asked to run the program), `context: "fresh"`,
   `use_worktree: false`, no `cwd`, `permission_mode` = your own, `wake_when_done: true`, `title` «Этап <ID>:
   <название>», `name` `stage-<id>`, `background` = the program goal, the plan file and that this is one stage of a
   program run by an orchestrator, and `prompt` = the output of `program.py prompt <ID>`, unchanged; then `bind`
   as above. In any other turn — tell the owner one line after the track: «Этап <ID> готов к запуску, свободных
   чатов нет. Напишите «продолжай» — запущу», plus a push notification. With D40 this happens only when every
   clearing was refused and the reserve is empty.
5. Tell the owner one line — «Этап <ID> запущен: <ссылка на сессию>. Позову, когда понадобится ответ» — and
   end your turn. If the track line warns «резерв пуст» (T21.5: the delivered stage's chat will not be recyclable
   and the reserve cannot be topped up outside an owner turn), add to the same message: «Резерв пуст: когда этап
   сдастся, мне понадобится ваше слово — напишите что-нибудь в чат, и я пополню резерв».

**Track line.** Every message of yours to the owner about the program (a stage started, a question, a stage
delivered or failed, the report) starts with the output of `program.py track`, unchanged — two lines: the track,
e.g. `M1 ✓ → M2 ● Разработка · тикеты 5/12 · 53% → M3 ○ · программа 38%`, and the links
`Дашборд: [программа](…) · [текущий прогон](…)`, so the dashboard is one click away even when the side panel is
closed. Wake-ups you end silently get none. Do not poll and do not wait in a loop: the app wakes you when the stage session ends a turn.

**Why `autopilot-stage`.** The original `/autopilot` starts only when a person types it
(`disable-model-invocation`), and a slash command in a session's task arrives as plain text. `kit install`
therefore makes `autopilot-stage` — the same pinned Autopilot under another name, without that flag (D19).
The stage prompt tells the session to load `autopilot-roles` and then `autopilot-stage` with the stage's
arguments; for an adopted run, `autopilot-stage` without arguments, which resumes from `state.js`. Never invoke
`autopilot-stage` yourself, and never use it outside a stage session.

## 5. When the stage session ends a turn

You are woken two ways: the app's notification that the stage session ended a turn, and **a message from the
stage itself** («Вопрос этапа …», «Этап … сдан») — the stage sends one on every question and on delivery, because
after a long streak of wake-ups with no message from the owner the app stops waking you, and Autopilot closes its
`waiting` mark in `state.js` as soon as it carries on with other tickets (both seen on проект R M2). So:
- a question that came as the stage's message is a question even if `check` says `unfinished`: relay it as in
  `waiting` below. A question you already showed the owner (same stage, same text) is not shown again;
- in a turn **not started by the owner's words** (a message, a notification, the watchdog) the app does not let you
  start a session. Relaying, `check --record`, commits, `stage continue`, `clear_session` and `SendMessage` work — so
  the next stage starts **through `pool take --json`** (§4 step 4) in this same turn, without the owner. Never ask
  the owner «продолжай» while `pool take --json` still gives a chat.

Check the limits (§5a, `--phase running`), then run `program.py check --record` and act on `verdict`:

- **`waiting`** — Autopilot waits for the owner (`kind`: `briefing`, `spec`, `plan`, `action`, `stop`).
  Read the session's last message (`list_events`, a few messages) for the exact questions.
  - Every question already answered in `program.json` → send those answers to the session yourself
    (`SendMessage` to its `local_…` id), quoting the decision IDs; do not bother the owner.
  - Otherwise the owner gets the question in **a message of its own** — the owner reads only your chat, so it
    must be recognisable as the same question the stage asked. Any other news (a limit reset, a stage started)
    goes in a separate message before it. The question message, after the track line:
    - a heading line `**Вопрос этапа <ID> · <брифинг | спецификация | план | действие | стоп>**`;
    - the stage's questions **verbatim**, as a quote block (`> …`), with the answer options the stage gave —
      never retold in your words;
    - `Рекомендация этапа: …` (its own recommendation, verbatim);
    - the last line: «Ответьте здесь — я передам этапу».
    Forward the owner's reply to the session quoting their words. If an answer is a decision later stages need
    too, record it (`ask` + `answer` with `--stage` omitted).
  - `kind: action` (push, payment, publication, deletion) — forward only the owner's explicit «да» or «нет»;
    never answer it yourself, never from a recommendation.
  The stage sessions tell the owner to answer here; if the owner still answers inside a stage session, the next
  wake-up shows it — do not forward the same answer twice.
- **`unfinished`** or **`not_started`** — the run is neither done nor waiting for the owner. This is
  usually normal: a stage session ends its turn while a background subagent works (an independent
  review, the coverage check G2) and wakes by itself when it returns. Check the session (`get_session`):
  `isRunning: true` → end your turn silently. Idle → read its last messages (`list_events`):
  - it waits for a subagent or a notification («жду результат», «уведомление придёт само») → end your
    turn; say nothing to the owner unless the same wait repeats on your next wake-up with no progress
    (same Autopilot stage, same last message) — then tell the owner one line;
  - it **claims a background executor is working** («исполнитель работает в фоне», «жду результат фонового
    агента») → verify, do not take its word (T21.10): the app kills background agents at turn/session
    boundaries — pilot S1/S2 twice got `Background agent "…" didn't finish before the previous session
    ended`, the agent died silently and the stage idled waiting for nothing. Check the session's
    `list_events` (was the agent started at all? did its result land? or did it die at the boundary?) and
    the tree facts — fresh commits/files, the test count, the gate. The claimed agent never ran or died →
    **one** ping to the stage naming what has already landed in the tree (e.g. «было 237 тестов, стало
    251») and telling it to restart or finish the work **inside its turn** (STAGE_RULES forbids ending a
    turn with a live background executor); the same claim again with no progress → the owner;
  - a question to the owner without `ap.py ask` → handle as `waiting`;
  - subscription limit → §5a (`pause`); a gateway quota refusal (`429 … quota … will reset at …`) → §5a
    «Gateway quota» (`quota-pause`, T21.9); a crash or a refused tool → tell the owner what happened; stop;
  - none of these → send it once «Продолжай прогон Autopilot»; the second time → owner.
  Never send «продолжай» to a session that is running or waits for its subagent.
- **`passed` with `partial: true`** (D23) — the run delivered, but deferred requirements of the stage brief
  (`deferred`: id, text, why). Read the stage's «Входит» / «Не входит»:
  - deferred items inside the stage's scope → `program.py stage continue <ID>` and go to §4 step 1: the next
    part of the same stage (its brief starts with the deferred list) runs before any later stage. Tell the
    owner one line: «<ID> сдан не целиком: отложено <N> — запускаю часть <K>». After the third part
    `stage continue` refuses — then one question to the owner;
  - items the owner's plan puts out of scope, or the run deferred for a reason only the owner can lift
    (money, an account, data) → one question to the owner: continue, accept as is, or move them to a later
    stage (the owner's answer goes into the plan file, then `plan-load`).
  `placeholders` are done work waiting for the owner's data (a key, a file): list them in the stage line, they
  never trigger a continuation.
- **`passed`** — commit the program files («Программа: этап <ID> сдан»). Tell the owner one line: the
  stage's `result`, and «документы, кода продукта нет» when `deliverable` is `docs`. Read `nextStep`: the
  decisions it lists that `program.json` has no answer for become new questions (`ask --stage <next>`).
  Then triage the leftovers (§5b) and go to §4 step 1 — the next stage starts without the owner unless it needs
  answers.
- **`failed`** — under full autonomy: §0 (one repair, then accept and a debt stage). Under `autonomy ask`: stop. One message: the `reasons` (and the `gate` tail if any), then the options with your
  recommendation: (1) repair in the same stage session — send it the reasons; (2) accept as is —
  `program.py stage set <ID> --status passed --note "принято владельцем: <его слова>"` — and then the leftovers
  triage (§5b): the failures become a debt stage with a repeated blind acceptance; (3) run the stage
  again — `stage set <ID> --status pending`, quench the old session and mark it (`stop_session` + `archive_session` +
  `stage prev-done <ID>`, §4 step 1, T21.3), then §4. Do what the owner chose; nothing before that.

If the app does not wake you after many stages in a row (it stops auto-continuing after a long streak with no
message from the owner), the stage's own message or the watchdog's message wakes you (D25, D31); the owner's
«продолжай» or `/autopilot-program` also works — you continue from §8.

## 5b. Leftovers of a delivered stage: nothing stays without an owner (D26)

Every delivery leaves something: blind-acceptance mismatches, «осталось после ревью», reviewers' concerns,
deferred requirements, placeholders — and, when the owner accepted a failed stage «как есть», the failures
themselves. They are written into `PROGRESS.md`, but no later stage is obliged to fix them. So after **every**
delivery — `passed`, `passed` with `partial`, and `stage set <ID> --status passed` on the owner's «принимаю как
есть» — triage the leftovers before the next stage starts. `program.py next` refuses to start the next stage
while a delivered stage has untriaged leftovers.

1. `program.py leftovers <ID>` — the groups: `blind`, `failures` (accepted as is), `left`, `concerns`,
   `deferred`, `placeholders`, `flaky` (tests that failed and passed on the gate's retry, D41 — a flaky test is a
   defect: make it deterministic in a later stage or a debt stage, never just mark it skipped).
2. Decide each item (concerns may be grouped by theme — do not paste dozens of lines to the owner):
   - **already fixed or not a defect** (e.g. a later fix commit closed it, verified by reading the code or the
     tests) → drop, with the reason in the note;
   - **belongs to a later stage's scope** → add it to that stage's «Входит» in `.autopilot/PROGRAM-PLAN.md` as
     `долг <ID>: …` with the file and line where the source gives them;
   - **too big for that, or it blocks later stages** (correctness of a shared component, security) → a new stage
     `<ID>f · Долг <ID>` (T0–T1) right after the stage that runs now; its criteria are the items, and when the
     stage was accepted with a red blind acceptance, **a repeated blind acceptance on the criteria of <ID>**;
   - **needs the owner** (an action only the owner can do, a decision, money, data) → `program.py ask … --stage <where
     it blocks>`;
   - `deferred` inside the stage's scope → `stage continue` (§5), not this list.
3. `program.py plan-check` and `plan-load` (started and delivered stages are not touched), then
   `program.py leftovers <ID> --done --note "<куда что ушло: этапы, новый этап долга, вопросы>"`.
4. One message to the owner, after the track line: a table «группа → сколько → куда», the new debt stage if
   any, the new questions. Then §4 step 1.

## 5a. Subscription limits: pause and resume by themselves (D22)

When the 5-hour or weekly limit runs out, every chat of the account stops, you too — nobody can wait inside a
chat. So you act **before** it runs out, and a one-time app task wakes the program after the reset.

**Limits that do not apply (D48).** On the Claude Desktop Gate drive traffic goes through the organization's
gateway: `get_usage` answers `plan.status: "not_applicable"` and `program.py limits` returns
`limits: "not_applicable"`. There are no subscription windows to insure — **skip this section entirely**
(do not create resume tasks, do not wait for resets; the watchdog D28 and `job set` D47 cover interruptions).
Tell the owner once at the start of the program: «Лимиты подписки не измеряются (трафик через гейтвей
организации) — пауз по лимитам не будет». The same applies to any other `plan.status` that is
not `ok`: `limits` answers `go` — carry on without limits.

**Gateway quota (T21.9).** The gateway has its own quota (token-plan, monthly) and `get_usage` does not see it:
exhaustion arrives as a refusal text — `API Error: Request rejected (429) · Your token-plan … quota has been
exhausted. The quota will reset at MM-DD HH:MM:SS UTC` — in your own turn, in a stage session's last messages
(`list_events`), or in a refused tool's result. When you see it, run `program.py quota-pause --text '<the refusal
text verbatim>' --orchestrator <your session id>`: it sets a limit pause until the reset (+2 min) and prints the
next steps — do exactly those steps (the one-time app task from `wake-prompt` when a stage session runs, one line
plus a notification to the owner, end the turn). **Never retry the refused request** and never wake the stage
before the reset: every attempt hits the dead quota. A gateway outage that is not a quota refusal is treated as a
failure of the stage (§5, `unfinished`/`failed`), not as a limit pause.

The quota is **monthly**: the reset can be weeks away, so the notification to the owner is mandatory and must offer
the choices — change the tariff or the provider (on their «продолжай» lift the pause with §5c `resume`, which also
disables the resume task), move the program, or continue on another machine (the subscription drive); doing nothing
means the program resumes itself at the reset. `why-paused` and the dashboard show the reason («квота гейтвея») and
the date. A quota stop also **kills the app's background workers**: `quota-pause` marks the registered long jobs
(`job list` → `quotaSuspect`) as needing re-verification — after the resume, check each one on the spot (never trust
a stage's «works in the background» word for it), restart and re-register the dead ones (`job set`), drop the
finished ones (`job clear`).

**The limits answer is authoritative (T19.8).** Env markers can lie in both directions: a subscription build with
a local proxy in `ANTHROPIC_BASE_URL` looks like a gate, and a gate build that lost `CLAUDE_CODE_ENTRYPOINT` looks
like a subscription. Whatever `limits` answers is the truth: with `plan.status: "ok"` it returns `drive: "claude"`
— apply the pauses below even if §1 believed this was the gate drive; with `not_applicable` — `drive:
"claude-gate"`. `limits` also writes the confirmed drive to `program.json` and repairs `orchestratorMachine`, so
the watchdog never takes its own orchestrator for a foreign one. Never skip this section on env markers alone.

**Read the limits** (`get_usage` — the `plan` part: percent used and reset time of each window) before §4 step 2
and on every wake-up while a stage runs, and pass the JSON to
`program.py limits --phase start|running --usage '<json>'` (`start` before a stage, `running` during one):

- **`go`** — carry on.
- **`insure`** (a stage runs, 5-hour ≥ 80% or weekly ≥ 90%) — make sure one app task will wake the stage after
  the reset: `create_scheduled_task` (or `update_scheduled_task` if it exists) with `taskId`
  `autopilot-program-resume-<папка проекта>`, `fireAt` = `resumeAt`, `prompt` = the output of
  `program.py wake-prompt`, unchanged. Say nothing to the owner. If the stage lands before the reset, the task
  wakes, sees it and does nothing.
- **`pause`** (before a stage: 5-hour ≥ 85% or weekly ≥ 90%; or any window at 100%) — do not start the work now:
  1. `program.py start <ID>`, then start the stage session as in §4 step 4 but with
     `prompt` = `program.py prompt <ID> --after-signal`: the session only answers «Этап ждёт сигнала…» and stops,
     spending almost nothing; `bind` it. A stage that already runs needs no new session.
  2. `program.py pause --until <resumeAt> --window "<окно>" --orchestrator <your session id>`.
  3. The app task as for `insure`, with `fireAt` = `resumeAt`.
  4. A push notification and one line to the owner, after the track line: «Пауза до <ЧЧ:ММ> — <окно>;
     продолжу сам, ничего делать не нужно». End your turn.

**The reason of a pause (D46).** `pause` takes `--reason limit|owner|other` and `--text`. A **limit** pause (default,
`--until` required) is the only one that continues by itself. When the **owner** stops the work in words («останови»,
«до моего распоряжения»): `program.py pause --reason owner --text "<что стоит и почему, словами владельца>"
--orchestrator <your session id>` — no `--until`, no app task, no «лимит» anywhere; the dashboard and `track` say
«Пауза по слову владельца». Never invent a far-away `--until` to mean «indefinitely».

**Why it works.** The app task cannot start sessions or use SendMessage (spike L1, L2); it wakes the stage
session with `send_message`. When that stage ends its turn, the app wakes you, and you start the next stage
through `pool take --json` (§4 step 4) — no new session is needed: a turn that is not started by the owner's words
cannot start sessions (L4, and since D40 L3 no longer holds), but it can clear the delivered stage's chat (L6).

Never switch on paid extra usage: that is money, only the owner decides.

## 5c. The owner lifts a stop: lift **everything**, then look (D46)

A pause has several independent holders; `resume` alone used to lift only the first (the 2026-10-31 Strata case: the
dashboard stayed orange for four days after the work had restarted). Whenever the owner lifts a stop — «продолжай»,
«стоп снят», a new task for the stage — do this, in order, in the same turn:

1. `program.py resume`. One command now: lifts `pause`, closes the owner tasks marked `--kind pause` («ожидание
   паузы»; add them with `owner-task add … --kind pause` when you stop for the owner), and clears the stage's
   `waiting` flag in `state.js` (`stage unwait`, the same as the stage's own `ap.py answered`) — unless an open question
   or owner task of that stage still holds it, or the stage wrote to `state.js` in the last 30 s (it then says why).
2. Do what its output lists: the one-time app task `autopilot-program-resume-<папка>` that `limits … insure` may have
   created — `mcp__scheduled-tasks__update_scheduled_task` with `enabled: false` (check with `list_scheduled_tasks`);
   and `send_message` to the stage session with the quoted «стоп снят» text, so that a stage that ended its turn goes on.
3. Owner tasks that lost their meaning (the thing they asked is gone) → `owner-task done T<n> --unwait`; it closes the
   task and clears the stage flag when nothing else holds it.
4. `program.py track` and the dashboard must show the stage as working. Anything still orange → `program.py
   why-paused`: it lists every holder (pause, open questions, open owner tasks, the stage's `waiting` flag with its age,
   the app task to check) and the command that lifts each. Do not edit `program.json` or `state.js` by hand.

**New work during a pause.** If the owner gives the stage a new task while the program is paused, do not leave the
statuses to disagree: either `program.py resume` first (the work becomes part of the program), or, when it is outside
the plan, re-run `pause --reason owner --text "идёт работа вне плана: <что>"` so that the dashboard says so.
Either way the stage session gets the task from you and clears its own `waiting` flag (`ap.py answered`) before it starts.

## 6. When the owner is needed

Under full autonomy (§0) — never as a reason to wait: decisions are taken by recommendation, the owner's part becomes
owner tasks and push notifications, irreversible actions are never done without the owner. Only under `autonomy ask`:
a question from a run that `program.json` does not answer; a failed stage (red gate, blind acceptance mismatch, a
failed ticket, a missing landing commit or «Следующий шаг»); an irreversible action — each time **one** clear
question, and after the answer you continue yourself.

## 7. Program report

When no stages are left (or the owner stops the program): `program.py report`, show it, add the link to each
stage session, and commit the program files («Программа: отчёт»). The report says which stages are
delivered and what each gives, what is left, the owner's decisions, and the assumptions made for them.

## 8. Continue a program

`program.py status`; name your chat and open the dashboard as in §1 (a new chat has neither); the owner's word
«дашборд» → the fixed panel procedure of §1, never the computer's browser. A program still in `semi`
from before D29: `program.py mode full` and one line to the owner («Дальше этапы идут в режиме full — без вопросов
брифинга; решения за вас будут в отчёте этапа»), unless the owner chose `semi` after D29. A program made
before D23 has no `.autopilot/PROGRAM-PLAN.md`: write it from the sources (§2, path «fill in»), `plan-check`,
`plan-load` — only waiting stages change — and show the owner what changed before the next stage starts. Then:
- a stage is `running`/`waiting` and its session (`sessionId`, `get_session`) is still working → tell the
  owner which session it is; subscribe to it ending (`SendMessage` with `notify_when_idle: true`) and end
  your turn;
- a stage is `running`/`waiting` and its session is idle or gone → `program.py check --record` and act as in
  §5; to resume a stopped run, `program.py stage set <ID> --status pending`, `program.py start <ID> --adopt`, then a new stage
  session as in §4 step 4 — the prompt resumes the run from `state.js`;
- nothing active → §4.

## 9. Codex (D24: one core, a Codex driver)

In Codex (`CODEX_THREAD_ID` set) the project setup of §1 (`$autopilot-init`, `.codex/hooks.json`) and everything in §2, §3, §5 (verdicts), §5b (leftovers) and §7 is the same —
the same `program.py`, plan, questions, leftovers and report. What differs is how a stage runs, how you wake up
and how the owner's answer reaches the stage. The Claude-only tools of §1 and §4 (`start_session`, `SendMessage`,
`set_pinned`, `show_pane`, `preview_start`) do not exist here — do not look for them.

**Your chat.** It is the program's home; every message of yours starts with `program.py track` (the track line
and the dashboard links). Dashboard: `program.py page` starts its server and prints the address; if this Codex
has a built-in browser, open the address there, otherwise the links in every message are enough. This Codex has no
tool to pin a chat or to show a side panel (D27 is Claude-only) — do not look for one, the links are the dashboard.
The project's gate hook (`gate.py --hook codex-stop`, from `.codex/hooks.json`) skips your chat because it starts with
`$autopilot-program` (D32): you write no project code. The git author is set by `program.py` itself — never ask the owner.

**A stage runs as a background `codex exec`** started by the script, not by you typing:
1. `program.py next --json` (questions → owner, as §3), `program.py limits --phase start --codex` (§5a decisions),
   `program.py start <ID>`, commit the program files (§4 step 3).
2. `program.py codex-run <ID>` — starts `codex exec --json` in the project folder with the stage prompt
   (`program.py codex-prompt <ID>` shows it: `$autopilot-roles`, then `$autopilot` with the stage's arguments)
   and the owner's access choice (workspace-write with automatic review of requests). It returns at once.
3. **Wake yourself:** create a task in this chat (a thread automation) every 10 minutes — «Программа: проверь
   этап — program.py codex-status и действуй по §9 навыка autopilot-program». One per program; delete it when the
   program is delivered or stopped. Tell the owner once that you check every 10 minutes and they can write any
   time.

**On every wake-up** (the task or the owner's message): `program.py codex-status`.
- `jobs` (D47, long work outside the chat that the stage registered with `program.py job set`): an entry with
  `state: dead` → `program.py codex-answer <ID> "<its message>"` (the stage resumes, finds the cause, restarts
  the work; `codex-answer` refuses while the process still runs, so repeat it at the next wake-up); no result
  after two tries → the owner. `expired` (D50: the watch term ran out while the stage is not delivered — the work may
  still be running unobserved) → `codex-answer <ID> "<its message>"`: the stage checks the logs and extends (`job set`)
  or clears the watch. `unknown` (no link to the server) → do
  nothing, the owner only after an hour. `alive` → the work is fine, the stage's silence is normal.
- `process: running` → `program.py limits --phase running --codex`; `insure` → a one-time task in this chat at
  `resumeAt` («лимит сброшен — продолжи программу»); otherwise end the turn silently.
- `process: exited` → `program.py check --record` and act as in §5, with these Codex moves:
  - `waiting`, or `unfinished` with a question in `lastMessage` → the question to the owner in the §5 format
    (heading, the stage's text verbatim as a quote, its recommendation); questions the program already answers
    you answer yourself. The owner's reply → `program.py codex-answer <ID> "<слова владельца>"` — it resumes the
    same session (`codex exec resume <thread_id>`). An irreversible action — only the owner's explicit «да».
  - `unfinished` with no question (`lastEvent` `turn.failed` or `error`): read the log named in `log`; a
    subscription limit → §5a pause with a one-time task in this chat at `resumeAt`, then `codex-answer <ID>
    "Лимит восстановился — продолжай прогон"`; anything else → `codex-answer` once with «Продолжай прогон
    Autopilot», the second time → owner.
  - `passed` → commit, §5b leftovers, then the next stage from step 1.
  - `failed` → §5 options; «repair» = `codex-answer <ID> "<причины>"`.

**Fallback — manual.** If `codex-run` fails (no `codex` found, a flag this version rejects — the spike T15.0
checks them; `--exec-arg` replaces the defaults), the owner runs the stage: `program.py start <ID>`, show
`program.py prompt <ID> --manual` in a code block with «Откройте новый чат Codex в папке проекта и отправьте
эти строки по очереди»; when the owner comes back with `/autopilot-program`, `program.py check --record` and act
as in §5 — the owner answers in the stage chat.
