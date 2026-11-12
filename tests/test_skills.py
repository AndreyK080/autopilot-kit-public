from kit import commands

ROLES = commands.KIT_ROOT / "skills" / "autopilot-roles" / "SKILL.md"


def test_roles_skill_tells_user_when_run_yields_documents():
    # D16: прогон, который даёт только документы, говорит об этом во вступлении, на дашборде, в отчёте и коммите
    text = ROLES.read_text(encoding="utf-8")
    section = text.split("## 8. Run deliverable", 1)[1]
    for phrase in (
        "set deliverable=docs",
        "В этом прогоне пишутся документы, код продукта не\n   появится; разработка кода — следующим прогоном.",
        'init --title "Документы: <что пишется>"',
        'stage build --note "Пишутся документы, код продукта не пишется"',
        "**Готовы документы, не продукт.**",
        "Кода продукта нет — пользоваться пока нечем. Следующий шаг:",
        'finish --result "Документы готовы, кода продукта нет',
        "Сданы документы, кода продукта нет",
    ):
        assert phrase in section, phrase


def test_roles_skill_ends_multi_run_report_with_next_run():
    # D17: отчёт многоэтапного проекта заканчивается командой следующего прогона и решениями до него
    text = ROLES.read_text(encoding="utf-8")
    section = text.split("## 9. Multi-run project", 1)[1]
    for phrase in (
        "«## Следующий шаг»",
        "/autopilot-roles\n     /autopilot <режим>: <задание следующего этапа>",
        "«Что нужно от тебя до запуска»",
        "без ответа — следующий прогон остановится на\n     брифинге",
        "`.autopilot/PROGRESS.md` gets the same section «## Следующий шаг»",
    ):
        assert phrase in section, phrase


def test_program_skill_runs_stages_through_kit_script_and_stage_copy():
    # D18/D19: оркестратор ведёт состояние только скриптом и запускает этапы через autopilot-stage
    text = (commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        r'python "$HOME\.autopilot-kit\bin\program.py" <command>',
        "`prompt` = the output of `program.py prompt <ID>`, unchanged",
        "`use_worktree: false`, no `cwd`, `permission_mode` = your own",
        "Never invoke\n`autopilot-stage` yourself",
        "program.py check --record",
        "never answer it yourself, never from a recommendation",
        "`program.py prompt <ID> --manual`",
        "## 9. Codex (D24: one core, a Codex driver)",
        "`program.py codex-run <ID>`",
        "`program.py codex-answer <ID> \"<слова владельца>\"`",
        "**Wake yourself:** create a task in this chat (a thread automation) every 10 minutes",
        '--status\npassed --note "сдан до программы: <прогон>, <коммит>"',
        "`isRunning: true` means the run is live;\nthen do not adopt it",
        "Name it «Оркестратор · <проект>»",
        "starts **its own background server** on the project's fixed port",
        "`preview_start` with `name: \"autopilot-program\"`",
        "**Keep it in front by yourself**",
        "Never open a second tab with the same address.",
        "**pin it yourself** at the start",
        "**and then show the panel**",
        "**Watchdog for restarts (D28).**",
        "## 0. Autonomy: you never wait for the owner (D30)",
        "**never yes by yourself**",
        "`program.py stage repair <ID>`",
        "`cronExpression` `*/15 * * * *`, `prompt` = the output of `program.py watch-prompt`, unchanged",
        "**a message from the\nstage itself**",
        "in a turn **not started by the owner's words** (a message, a notification, the watchdog) the app does not let you",
        "starts with the output of `program.py track`",
        "`program.py limits --phase start|running --usage '<json>'`",
        "`program.py prompt <ID> --after-signal`",
        "`prompt` = the output of\n  `program.py wake-prompt`, unchanged",
        "Never switch on paid extra usage",
        "## 5b. Leftovers of a delivered stage: nothing stays without an owner (D26)",
        "`program.py next` refuses to start the next stage\nwhile a delivered stage has untriaged leftovers.",
        "**a repeated blind acceptance on the criteria of <ID>**",
        "**The owner's documents are never edited**",
        "The plan holds stage briefs, not tickets.",
        "`program.py plan-check .autopilot/PROGRAM-PLAN.md` until there are no `errors`",
        "`program.py plan-load .autopilot/PROGRAM-PLAN.md`",
        "`program.py stage continue <ID>`",
        "`placeholders` are done work waiting for the owner's data",
        "the owner gets the question in **a message of its own**",
        "`**Вопрос этапа <ID> · <брифинг | спецификация | план | действие | стоп>**`",
        "the stage's questions **verbatim**, as a quote block",
        "**Register yourself and keep the reserve (D31, D40).**",
        "`program.py orchestrator --session\n  <your local_… id>`",
        "`prompt` = the output of `program.py pool-prompt`, unchanged",
        "**through `pool take --json` first** (D31, D40)",
        "output of `program.py signal <ID>`,\n   unchanged",
        "Never ask\n  the owner «продолжай» while `pool take --json` still gives a chat.",
    ):
        assert phrase in text, phrase


def test_parity_table_covers_both_apps():
    # D24: каждая возможность kit описана и для Claude Code, и для Codex
    text = (commands.KIT_ROOT / "docs" / "PARITY.md").read_text(encoding="utf-8")
    rows = [r for r in text.splitlines() if r.startswith("| ") and not r.startswith("| Возможность") and not r.startswith("|---")]
    assert len(rows) >= 15
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 4 and all(cells), row
        assert cells[3].split(":")[0].split(" ")[0] in ("=", "≈", "спайк", "план", "нет"), row


def test_program_skill_checks_that_reserve_sessions_are_alive():
    # D34: мёртвые записи резерва (после переезда на другую машину) не считаются резервом
    text = (commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in ("`program.py pool\n  list`", "`program.py pool drop <id>`", "A dead entry counts as a reserve session otherwise", "`pool take --json` the next one"):
        assert phrase in text, phrase


def test_program_skill_sets_the_project_up_itself():
    # D39: без .autopilot-kit/project.toml оркестратор настраивает проект сам, как /autopilot-init, и не ждёт владельца
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Project setup (D39) — one command is enough.**", "`program.py setup-check`",
                   "(there is no `.autopilot-kit/project.toml`)", "load that skill with the Skill tool (`autopilot-init`",
                   "you may write only the setup files", "skip its step 6",
                   "The project is not set up (§1, no `project.toml`)", "`$autopilot-init`"):
        assert phrase in text, phrase


def test_program_skill_reuses_the_delivered_stage_chat():
    # D40: сессии запускаются только в ходе со словами владельца — следующий этап получает очищенный чат сданного
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**only in a turn started by the owner's own words**", "`start_session` is refused; do not try it there",
                   "**the chat of the delivered stage, cleared**", "`clear: true` → `mcp__ccd_session_mgmt__clear_session`",
                   "Refused (the owner pinned it or has it open on screen, it still works) → `pool take --json` again",
                   "Top the reserve up **only in a turn started by the owner's words**", "mcp__ccd_session_mgmt__clear_session`."):
        assert phrase in text, phrase


def test_program_skill_asks_auto_mode_permissions_up_front():
    # D41: разрешения для проверки режима auto — в первом сообщении, пока владелец рядом; запись — approve add
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Permissions the auto-mode check needs (D41) — in the same first message, while the owner is here.**",
                   "«Разрешения для работы без вас»", "--approval`", "`next` never answers an approval question by recommendation",
                   "`program.py approve add \"<действие точно>\"", "Never `approve add` on anyone's word but the owner's in this chat.",
                   "A stage reports «блок проверки прав (D41)»", "`ready: false` with `approvals` (D41)"):
        assert phrase in text, phrase


def test_program_skill_quenches_previous_sessions_and_dirty_chats():
    # T21.3/T21.4: перезапуск этапа гасит прежнюю сессию; задание не уходит в неочищенный чат
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("keeps its old session in `previousSessions`", "**quench it before the new launch**",
                   "`program.py stage prev-done <ID>`", "Never send a stage task to a chat whose clearing was refused",
                   "works only inside the current chat"):
        assert phrase in text, phrase


def test_program_skill_opens_panel_by_launch_name_not_url():
    # T21.11: preview_start в текущих билдах принимает только name из .claude/launch.json; импровизация запрещена
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("`program.py page --launch`", "`preview_start` with `name: \"autopilot-program\"`",
                   "has no `url` parameter", "**Never improvise here**", "no hand-made `http.server`",
                   "stays out of git", "After an app restart or a reboot, open the panel again the same way"):
        assert phrase in text, phrase
    assert "no `name`, no `.claude/launch.json`" not in text  # старая невыполнимая формулировка убрана


def test_stage_rules_open_run_dashboard_by_launch_name():
    # T21.11: этап открывает дашборд прогона той же конфигурацией kit и не заводит свой сервер
    from kit import program
    rules = program.STAGE_RULES
    assert "name: \"autopilot-program\"" in rules and "page --launch" in rules
    assert "Своего `http.server` и своих конфигураций запуска не заводи" in rules
    assert "show_pane" in rules  # правило «панель в конце каждого хода» осталось
    from kit import gate
    assert "T21.11" in gate.PANE_REMINDER and 'name: "autopilot-program"' in gate.PANE_REMINDER


def test_program_skill_verifies_own_reports_by_artifact():
    # T21.12: отчёт владельца проверяется по артефакту, а не по намерению (инцидент S2: «записал в память» без записи)
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Verify before reporting (T21.12).**", "check it against the artifact",
                   "Never report an intention as a result",
                   "(`owner-task done`), check the outcome in the tree/`program.json`"):
        assert phrase in text, phrase


def test_program_skill_never_runs_permission_command_itself():
    # T21.14: приложение блокирует изменение собственных разрешений сессией ([Self-Modification]) — шаг всегда ручной
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Never run this command yourself**", "[Self-Modification]",
                   "ready command for **their** terminal", "**check it by reading**",
                   "do not retry and do not work around"):
        assert phrase in text, phrase
    assert "do not run it yourself without their «да» in this chat" not in text  # старая формулировка с ожиданием «да» убрана


def test_program_skill_dashboard_word_is_a_fixed_panel_procedure():
    # T21.15: слово «дашборд» — фиксированная процедура панели, шаги 1–7, и жёсткий запрет браузера компьютера
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("The owner's word «дашборд»", "**fixed procedure**, in this order",
                   "`program.py page` — puts `.autopilot/program.html`",
                   "**and frees the port for the panel**",
                   "is in use by \"python.exe\"» — pilot fact",
                   "stops **only the kit's own** background server (by its pid file)",
                   "`serve --foreground` waits instead of binding",
                   "do **not** open a second one, go to step 5",
                   "`preview_start` with `name: \"autopilot-program\"`",
                   "attach-by-url does not work at all: «it is not enabled on this install»",
                   "**navigation inside the panel**",
                   "location.replace('http://localhost:<port>/dashboard.html')",
                   "on every «дашборд» and at the end of every turn (D38 unchanged)",
                   "This session isn't open in any window", "end the turn; the panel comes back by itself",
                   "repeat from step 1"):
        assert phrase in text, phrase


def test_program_skill_forbids_the_computer_browser():
    # T21.15: жёсткий запрет — только боковая панель, никаких start/explorer/open/Invoke-Item/webbrowser
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    assert "**Never open the dashboard in the computer's browser.**" in text
    for tool in ("`start`", "`explorer`", "`cmd /c start`", "`open`", "`Invoke-Item`", "`webbrowser`"):
        assert tool in text
    assert "never «copy the link into your browser»" in text
    assert "that is text, not a browser launch" in text
    # §8 продолжает ссылаться на процедуру §1
    assert "never the computer's browser" in text


def test_stage_rules_and_pane_reminder_forbid_the_computer_browser():
    # T21.15: тот же запрет в задании этапа и в напоминании хука
    from kit import gate, program
    for text in (program.STAGE_RULES, gate.PANE_REMINDER):
        assert "браузере компьютера" in text and "webbrowser" in text and "Invoke-Item" in text
        assert "T21.15" in text
