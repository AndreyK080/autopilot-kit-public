import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from kit import program
from tests.conftest import git


def stamp(minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).astimezone().isoformat(timespec="seconds")


def write_run(root, **fields):
    state = {"version": 2, "dir": "2026-10-23-demo--wip", "startedAt": stamp(1), "finishedAt": None,
             "waiting": None, "stages": [], "tickets": [], "gates": {}, "blind": None, "result": None}
    state.update(fields)
    (root / ".autopilot").mkdir(exist_ok=True)
    (root / ".autopilot" / "state.js").write_text("window.STATE =\n" + json.dumps(state, ensure_ascii=False),
                                                  encoding="utf-8")


def finished_run(root, **fields):
    base = dict(finishedAt=stamp(2), result="wc2 считает строки",
                stages=[{"id": "build", "status": "done"}], tickets=[{"id": "01", "status": "done"}],
                gates={"G2": {"ok": True}, "G3": {"ok": True}, "G4": {"ok": True}},
                blind={"checked": 3, "matched": 3, "mismatches": []}, debt={"assumptions": ["вывод — одна строка"]})
    base.update(fields)
    write_run(root, **base)


def commit(root, subject):
    (root / "f.txt").write_text(subject, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", subject)


def write_progress(root, next_step=True):
    text = "# Что осталось\n\n## Не доделано\n\n- M2\n"
    if next_step:
        text += "\n## Следующий шаг\n\n```\n/autopilot-roles\n/autopilot semi: M2\n```\n"
    (root / ".autopilot" / "PROGRESS.md").write_text(text, encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Домашний каталог kit с подменённым gate.py: код выхода — из файла gate_rc рядом."""
    home = tmp_path / "home"
    bin_dir = home / ".autopilot-kit" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "gate_rc").write_text("0", encoding="utf-8")
    (bin_dir / "gate.py").write_text(
        "import pathlib, sys\nrc = int((pathlib.Path(__file__).parent / 'gate_rc').read_text())\n"
        "print('ГЕЙТ ПРОЙДЕН' if rc == 0 else 'ГЕЙТ НЕ ПРОЙДЕН')\nsys.exit(rc)\n", encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    return home


@pytest.fixture
def proj(tmp_path, home):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    commit(root, "init")
    (root / ".autopilot-kit").mkdir()
    (root / ".autopilot-kit" / "project.toml").write_text('[gate]\ncommands = ["python -c 0"]\n', encoding="utf-8")
    program.cmd_init(root, "wc2", "PLAN.md", "semi")
    program.cmd_stage_add(root, "M1", "Ядро", "M1: подсчёт строк", "M1", ["тесты зелёные"])
    program.cmd_stage_add(root, "M2", "Вывод", "M2: формат вывода", "M2", [])
    return root


def set_gate_rc(home, rc):
    (home / ".autopilot-kit" / "bin" / "gate_rc").write_text(str(rc), encoding="utf-8")


def test_init_writes_json_and_view(proj):
    data = json.loads(program.program_path(proj).read_text(encoding="utf-8"))
    assert [s["id"] for s in data["stages"]] == ["M1", "M2"]
    view = program.view_path(proj).read_text(encoding="utf-8")
    assert view.startswith(program.MARKER)
    assert "| M1 | Ядро | ждёт |" in view
    assert "План: `PLAN.md`" in view
    with pytest.raises(program.ProgramError):
        program.cmd_init(proj, "again", None, "semi")
    assert "План: нет" in program.render({**json.loads(program.program_path(proj).read_text(encoding="utf-8")),
                                          "plan": None})


def test_not_started_until_run_of_this_stage_begins(proj):
    write_run(proj, startedAt=stamp(-60), finishedAt=stamp(-30))  # прошлый прогон
    program.cmd_start(proj, "M1", adopt=False)
    assert program.cmd_check(proj, None, record=True, with_gate=False)["verdict"] == "not_started"


def test_waiting_and_unfinished(proj):
    program.cmd_start(proj, "M1", adopt=False)
    write_run(proj, waiting={"kind": "briefing", "note": "формат вывода"})
    verdict = program.cmd_check(proj, None, record=True, with_gate=False)
    assert (verdict["verdict"], verdict["kind"], verdict["note"]) == ("waiting", "briefing", "формат вывода")
    assert program.load(proj)["stages"][0]["status"] == "waiting"
    write_run(proj, stages=[{"id": "build", "status": "active"}])
    verdict = program.cmd_check(proj, None, record=True, with_gate=False)
    assert (verdict["verdict"], verdict["autopilotStage"]) == ("unfinished", "build")
    assert program.load(proj)["stages"][0]["status"] == "running"


def test_passed_when_everything_holds(proj):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj)
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    verdict = program.cmd_check(proj, "M1", record=True, with_gate=True)
    assert verdict["verdict"] == "passed", verdict["reasons"]
    assert "/autopilot semi: M2" in verdict["nextStep"]
    stage = program.load(proj)["stages"][0]
    assert stage["status"] == "passed" and stage["finishedAt"]


@pytest.mark.parametrize("change, reason", [
    (dict(tickets=[{"id": "01", "status": "failed"}]), "таск 01 не сдан"),
    (dict(stages=[{"id": "build", "status": "failed", "note": "упал"}]), "этап Autopilot build провален"),
    (dict(gates={"G2": {"ok": True}, "G3": {"ok": True}}, blind=None), "слепой приёмки (G4) не было"),
    (dict(gates={"G4": {"ok": False}}, blind={"mismatches": ["R07 — статус не виден"]}),
     "расхождение слепой приёмки: R07"),
    (dict(gates={"G3": {"ok": False}, "G4": {"ok": True}}), "G3 (трасса плана) не пройден"),
])
def test_failed_on_run_problems(proj, change, reason):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj, **change)
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    verdict = program.cmd_check(proj, "M1", record=False, with_gate=False)
    assert verdict["verdict"] == "failed"
    assert any(r.startswith(reason) for r in verdict["reasons"]), verdict["reasons"]


def test_failed_on_red_gate_missing_landing_and_next_step(proj, home):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj)
    write_progress(proj, next_step=False)
    set_gate_rc(home, 1)
    verdict = program.cmd_check(proj, "M1", record=True, with_gate=True)
    assert verdict["verdict"] == "failed"
    assert "гейт проекта не пройден" in verdict["reasons"]
    assert "ГЕЙТ НЕ ПРОЙДЕН" in verdict["gate"]
    assert any("Autopilot: сборка сдана" in r for r in verdict["reasons"])
    assert any("Следующий шаг" in r for r in verdict["reasons"])
    assert program.load(proj)["stages"][0]["status"] == "failed"


def test_landing_before_stage_start_does_not_count(proj):
    commit(proj, program.LANDING_SUBJECT)  # сдача прошлого прогона
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj)
    write_progress(proj)
    verdict = program.cmd_check(proj, "M1", record=False, with_gate=False)
    assert any("Autopilot: сборка сдана" in r for r in verdict["reasons"])


def test_last_stage_needs_no_next_step(proj):
    program.cmd_stage_set(proj, "M1", "skipped", None)
    program.cmd_start(proj, "M2", adopt=False)
    finished_run(proj)
    commit(proj, program.LANDING_SUBJECT)
    assert program.cmd_check(proj, "M2", record=False, with_gate=False)["verdict"] == "passed"


def test_one_run_per_folder(proj):
    write_run(proj, startedAt=stamp(-10))  # начатый и не законченный прогон
    with pytest.raises(program.ProgramError, match="--adopt"):
        program.cmd_start(proj, "M1", adopt=False)
    assert "подхвачен" in program.cmd_start(proj, "M1", adopt=True)
    with pytest.raises(program.ProgramError, match="один прогон"):
        program.cmd_start(proj, "M2", adopt=False)


def test_adopt_matches_only_that_run(proj):
    started = stamp(-10)
    write_run(proj, startedAt=started)
    program.cmd_start(proj, "M1", adopt=True)
    assert program.cmd_check(proj, None, record=False, with_gate=False)["verdict"] == "unfinished"
    write_run(proj, startedAt=stamp(5))  # другой прогон — не этот этап
    assert program.cmd_check(proj, None, record=False, with_gate=False)["verdict"] == "not_started"


def test_adopt_without_open_run_and_order_of_stages(proj):
    with pytest.raises(program.ProgramError, match="подхватывать нечего"):
        program.cmd_start(proj, "M1", adopt=True)
    with pytest.raises(program.ProgramError, match="сначала этапы: M1"):
        program.cmd_start(proj, "M2", adopt=False)


def test_retry_after_failure(proj):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj, tickets=[{"id": "01", "status": "failed"}])
    program.cmd_check(proj, "M1", record=True, with_gate=False)
    with pytest.raises(program.ProgramError, match="--status pending"):
        program.cmd_start(proj, "M1", adopt=False)
    program.cmd_stage_set(proj, "M1", "pending", "повтор по решению владельца")
    assert "начат" in program.cmd_start(proj, "M1", adopt=False)


def test_questions_block_next_until_answered(proj):
    program.cmd_autonomy(proj, "ask")  # до D30: этап ждёт ответов владельца
    program.cmd_ask(proj, "Q1", "Платный поиск?", "нет, встроенный поиск хоста", None)
    program.cmd_ask(proj, "Q2", "Формат вывода?", "одна строка", "M2")
    result = program.cmd_next(proj)
    assert not result["ready"] and [q["id"] for q in result["questions"]] == ["Q1"]
    program.cmd_answer(proj, "Q1", None, assumption=False)
    result = program.cmd_next(proj)
    assert result["ready"] and result["stage"] == "M1"
    assert result["brief"].startswith("semi: M1: подсчёт строк — по плану `PLAN.md`, раздел «M1»")
    assert "- Q1. Платный поиск? — нет, встроенный поиск хоста" in result["brief"]
    assert "Q2" not in result["brief"]
    assert "- тесты зелёные" in result["brief"]


def test_next_refuses_while_stage_runs(proj):
    program.cmd_start(proj, "M1", adopt=False)
    assert program.cmd_next(proj) == {"ready": False, "why": "этап M1 ещё идёт (running)"}


def test_report_lists_decisions_and_assumptions(proj):
    program.cmd_ask(proj, "Q1", "Платный поиск?", "нет", None)
    program.cmd_answer(proj, "Q1", "да, до 20 $", assumption=False)
    program.cmd_ask(proj, "Q2", "Лицензия?", "MIT", None)
    program.cmd_answer(proj, "Q2", None, assumption=True)
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj)
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    program.cmd_check(proj, "M1", record=True, with_gate=False)
    report = program.cmd_report(proj)
    assert "- M1 Ядро: wc2 считает строки" in report
    assert "- M2 Вывод — ждёт" in report
    assert "- Q1. Платный поиск? — да, до 20 $" in report
    assert "- Q2. Лицензия? — MIT" in report.split("## Допущения за владельца")[1]
    assert "- M1: вывод — одна строка" in report


def test_cli_check_prints_json(proj, capsys):
    program.cmd_start(proj, "M1", adopt=False)
    write_run(proj, waiting={"kind": "action", "note": "push?"})
    assert program.main(["--project", str(proj), "check"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "waiting"
    assert program.main(["--project", str(proj), "start", "M2"]) == 2


def test_prompt_for_new_and_manual_stage(proj):
    program.cmd_ask(proj, "Q1", "Платный поиск?", "нет", None)
    program.cmd_answer(proj, "Q1", None, assumption=False)
    with pytest.raises(program.ProgramError, match="не начат"):
        program.cmd_prompt(proj, "M1", manual=False)
    program.cmd_start(proj, "M1", adopt=False)
    text = program.cmd_prompt(proj, "M1", manual=False)
    assert "Ты — сессия этапа M1" in text
    assert "1. Вызови навык `autopilot-roles`" in text and "навык `autopilot-stage`" in text
    assert "-----\nsemi: M1: подсчёт строк" in text and "- Q1. Платный поиск? — нет" in text
    assert "не правь и не коммить их" in text
    assert "не интерактивной карточкой" in text and "Отвечать — в чате оркестратора" in text
    assert "«Ответ владельца получен через оркестратора: <ответ кратко>»" in text
    manual = program.cmd_prompt(proj, "M1", manual=True)
    assert manual.startswith("/autopilot-roles\n/autopilot semi: M1: подсчёт строк")


def test_prompt_for_adopted_run_resumes(proj):
    write_run(proj, startedAt=stamp(-10))
    program.cmd_start(proj, "M1", adopt=True)
    text = program.cmd_prompt(proj, "M1", manual=False)
    assert "без аргументов" in text and "продолжит начатый прогон" in text
    assert "-----" not in text
    assert program.cmd_prompt(proj, "M1", manual=True) == "/autopilot-roles\n/autopilot"


def build_run(**fields):
    stages = [{"id": p, "status": "done"} for p, _, _ in program.PHASES[:5]]
    stages += [{"id": "build", "status": "active"}, {"id": "review", "status": "pending"}, {"id": "final", "status": "pending"}]
    run = dict(stages=stages, tickets=[{"id": f"{i:02d}", "status": "done" if i <= 5 else "pending"} for i in range(1, 13)])
    run.update(fields)
    return run


def test_program_js_written_with_phases(proj):
    text = program.data_js_path(proj).read_text(encoding="utf-8")
    assert text.startswith("window.PROGRAM =\n")
    data = json.loads(text.split("=", 1)[1].rstrip().rstrip(";"))
    assert [s["id"] for s in data["stages"]] == ["M1", "M2"]
    assert [p["id"] for p in data["phases"]][5] == "build" and sum(p["weight"] for p in data["phases"]) == 100


def test_percent_and_track(proj):
    program.cmd_start(proj, "M1", adopt=False)
    write_run(proj, **build_run())
    stage = program.load(proj)["stages"][0]
    run = program.read_run(proj)
    # 3+7+5+12+8 = 35 за сданные фазы, разработка 45 × 5/12 = 18 → 53
    assert program.stage_percent(stage, run) == 53
    assert program.cmd_track(proj).startswith("M1 ● Разработка · тикеты 5/12 · 53% → M2 ○ · программа 26%")
    assert "резерв пуст" in program.cmd_track(proj)  # T21.5: M2 ждёт, резерва и чата для очистки нет — предупредить заранее
    write_run(proj, **build_run(waiting={"kind": "briefing", "note": "?"}))
    assert program.cmd_track(proj).startswith("M1 ⏸ ждёт тебя (briefing) → M2 ○")


def test_percent_ignores_other_runs_and_passed_is_full(proj):
    write_run(proj, **build_run(startedAt=stamp(-60), finishedAt=stamp(-30)))  # старый сданный прогон — не этого этапа
    program.cmd_start(proj, "M1", adopt=False)
    stage = program.load(proj)["stages"][0]
    assert program.stage_percent(stage, program.read_run(proj)) == 0
    assert "M1 ● запускается" in program.cmd_track(proj)
    program.cmd_stage_set(proj, "M1", "passed", "принято")
    assert program.cmd_track(proj).startswith("M1 ✓ → M2 ○ · программа 50%")
    assert "резерв пуст" in program.cmd_track(proj)  # сданный чат не привязан (не recyclable), резерв пуст


def test_page_copies_template_ignores_files_and_merges_launch(proj):
    launch = proj / ".claude" / "launch.json"
    launch.parent.mkdir()
    # чужие конфигурации (включая самодельную http.server из пилота, T21.11) сливание не трогает
    launch.write_text(json.dumps({"version": "0.0.1", "configurations": [
        {"name": "web", "port": 3000},
        {"name": "pilot-http", "runtimeExecutable": "python",
         "runtimeArgs": ["-m", "http.server", "8899", "--directory", ".autopilot"], "port": 8899},
    ]}), encoding="utf-8")
    lines = program.cmd_page(proj, launch=True)
    page = proj / ".autopilot" / "program.html"
    assert page.read_text(encoding="utf-8") == program.page_text()  # шаблон с подставленной версией страницы
    port = program.page_port(proj)
    assert 8700 <= port < 8900 and f"http://localhost:{port}/program.html" in "\n".join(lines)
    configs = json.loads(launch.read_text(encoding="utf-8"))["configurations"]
    assert [c["name"] for c in configs] == ["web", "pilot-http", "autopilot-program"]
    assert configs[-1]["runtimeArgs"][1:] == ["--project", ".", "serve", "--foreground"] and configs[-1]["port"] == port
    program.cmd_page(proj, launch=True)  # повторно — без дублей
    assert len(json.loads(launch.read_text(encoding="utf-8"))["configurations"]) == 3
    ignored = (proj / ".autopilot" / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ignored.count("program.html") == 1 and ignored.count("program.js") == 1 and "program-serve.pid" in ignored


def test_page_without_launch_and_broken_launch(proj):
    assert not any("сервер страницы" in line for line in program.cmd_page(proj, launch=False))
    assert not (proj / ".claude" / "launch.json").exists()
    (proj / ".claude").mkdir()
    (proj / ".claude" / "launch.json").write_text("{битый", encoding="utf-8")
    with pytest.raises(program.ProgramError, match="не разбирается"):
        program.cmd_page(proj, launch=True)


def test_page_template_has_live_polling_and_same_phases_logic():
    html = program.page_template().read_text(encoding="utf-8")
    for needle in ('<script src="program.js"></script>', '<script src="state.js"></script>', "POLL_MS = 5000",
                   "function stagePercent", "function belongs", "dashboard.html", "prefers-color-scheme:dark"):
        assert needle in html, needle


def usage(five, week, five_reset="2026-10-23T08:10:00.240Z", week_reset="2026-10-23T19:00:00.240Z"):
    return {"plan": {"status": "ok", "plan": "Max", "windows": [
        {"label": "5-hour limit", "percentUsed": five, "resetsAt": five_reset},
        {"label": "Weekly · all models", "percentUsed": week, "resetsAt": week_reset},
        {"label": "Weekly · Fable", "percentUsed": 0, "resetsAt": week_reset}]}}


@pytest.mark.parametrize("five, week, phase, decision, window", [
    (76, 53, "start", "go", None),
    (85, 53, "start", "pause", "5-hour limit"),
    (60, 90, "start", "pause", "Weekly · all models"),
    (79, 53, "running", "go", None),
    (80, 53, "running", "insure", "5-hour limit"),
    (100, 53, "running", "pause", "5-hour limit"),
    (90, 95, "start", "pause", "Weekly · all models"),  # оба окна — ждём то, что сбросится позже
])
def test_limits_decision(five, week, phase, decision, window):
    result = program.cmd_limits(usage(five, week), phase)
    assert result["decision"] == decision
    assert result.get("window") == window


def test_limits_resume_time_is_reset_plus_two_minutes():
    result = program.cmd_limits(usage(90, 10), "start")
    resume = datetime.fromisoformat(result["resumeAt"])
    gap = resume - datetime.fromisoformat("2026-10-23T08:10:00.240+00:00")
    assert timedelta(seconds=119) <= gap <= timedelta(minutes=2)  # ISO-время — с точностью до секунд
    assert result["resetsAt"] == "2026-10-23T08:10:00.240Z"


def test_limits_unreadable_means_go():
    assert program.cmd_limits({"plan": {"status": "unavailable"}}, "start")["decision"] == "go"
    assert program.cmd_limits({"plan": {"status": "not_applicable"}}, "running")["decision"] == "go"


def test_pause_shows_in_track_and_view_and_resume_clears(proj):
    with pytest.raises(program.ProgramError, match="ISO"):
        program.cmd_pause(proj, "завтра", None)
    text = program.cmd_pause(proj, "2026-10-23T11:12:00+03:00", "5-hour limit")
    assert text.startswith("Пауза до 23.10") and "5-hour limit" in text and "продолжу сам" in text
    assert program.cmd_track(proj).startswith("⏸ Пауза до 23.10")
    assert "**Пауза до 23.10" in program.view_path(proj).read_text(encoding="utf-8")
    assert '"pause"' in program.data_js_path(proj).read_text(encoding="utf-8")
    assert program.cmd_resume(proj).startswith("пауза снята")
    assert not program.cmd_track(proj).startswith("⏸")
    assert program.cmd_resume(proj) == "паузы не было"


def test_cli_limits_reads_json(capsys):
    assert program.main(["limits", "--phase", "start", "--usage", json.dumps(usage(86, 10))]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "pause"


def test_after_signal_prompt_waits_then_runs(proj):
    program.cmd_start(proj, "M1", adopt=False)
    text = program.cmd_prompt(proj, "M1", manual=False, after_signal=True)
    assert text.startswith("Сейчас лимит подписки почти исчерпан")
    assert program.RESUME_SIGNAL in text and "Ты — сессия этапа M1" in text and "autopilot-stage" in text


def test_wake_prompt_signals_stage_session(proj):
    with pytest.raises(program.ProgramError, match="нет идущего этапа"):
        program.cmd_wake_prompt(proj)
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    program.cmd_pause(proj, "2026-10-23T11:12:00+03:00", "5-hour limit", "local_orch")
    text = program.cmd_wake_prompt(proj)
    assert "`mcp__ccd_session_mgmt__send_message`" in text and "SendMessage из этой сессии не работает" in text
    assert "session_id `local_orch`" in text and "сессии этапа `local_stage`" in text
    assert program.RESUME_SIGNAL in text and "resume`" in text and "Запускать новые сессии эта сессия не может" in text
    assert str(proj.as_posix()) in text


TEMPLATE = program.plan_template_path().read_text(encoding="utf-8")


def test_template_parses_into_full_stages():
    plan = program.parse_plan(TEMPLATE)
    assert plan["program"]["goal"].startswith("бот в Telegram") and plan["program"]["mode"] == "full"
    assert [s["id"] for s in plan["stages"]] == ["M1", "M2", "M3"]
    m1, m3 = plan["stages"][0], plan["stages"][2]
    assert m1["deliverable"] == "код" and m1["size"] == "T1" and len(m1["criteria"]) == 3
    assert m1["outScope"].startswith("сводки") and m1["dependsOn"] == [] and m3["dependsOn"] == ["M1", "M2"]
    assert [q["stage"] for q in plan["questions"]] == ["M1", "M2", "все"]
    assert len(plan["constraints"]) == 3
    assert program.check_plan(plan) == {"ok": True, "errors": [], "warnings": [], "stages": 3, "questions": 3}


@pytest.mark.parametrize("edit, error", [
    (lambda t: t.replace("- Размер: T1\n- Источники: `docs/idea.md` §1–2", "- Размер: T4\n- Источники: `docs/idea.md` §1–2"), "M1: «Размер»"),
    (lambda t: t.replace("- Результат: код\n- Цель: бот принимает", "- Результат: прототип\n- Цель: бот принимает"), "M1: «Результат»"),
    (lambda t: t.replace("- Зависит от: M1\n", "- Зависит от: M9\n"), "M2: зависит от M9"),
    (lambda t: t.replace("### M2. Недельная сводка", "### M1. Недельная сводка"), "M1: ID повторяется"),
    (lambda t: t.replace("| понедельник, 9:00 по Москве | M2 |", "| — | M2 |"), "вопрос Q02: нет рекомендуемого"),
    (lambda t: t.replace("| понедельник, 9:00 по Москве | M2 |", "| понедельник | M7 |"), "вопрос Q02: этапа M7"),
    (lambda t: t.split("## Этапы")[0], "нет этапов"),
])
def test_plan_check_errors(edit, error):
    result = program.check_plan(program.parse_plan(edit(TEMPLATE)))
    assert not result["ok"] and any(e.startswith(error) for e in result["errors"]), result["errors"]


def test_plan_check_criteria_required_and_warnings():
    text = TEMPLATE.replace("  - команда /summary присылает суммы по категориям за последние 7 дней\n", "") \
        .replace("  - сводка по расписанию приходит в день и час из Q02 (проверено тестом с подменой времени)\n", "") \
        .replace("  - `python -m pytest -q` — зелёный\n- Зависит от: M1", "- Зависит от: M1") \
        .replace("- Размер: T0", "- Размер: T3").replace("- Не входит: мониторинг, CI\n", "")
    result = program.check_plan(program.parse_plan(text))
    assert "M2: нет критериев сдачи — без них этап нельзя принять" in result["errors"]
    assert any(w.startswith("M3: размер T3") for w in result["warnings"])
    assert any(w.startswith("M3: нет «Не входит»") for w in result["warnings"])


def test_plan_load_creates_program_and_rich_brief(tmp_path):
    root = tmp_path / "p"
    (root / ".autopilot").mkdir(parents=True)
    plan_file = root / ".autopilot" / "PROGRAM-PLAN.md"
    plan_file.write_text(TEMPLATE, encoding="utf-8")
    lines = program.cmd_plan_load(root, plan_file)
    assert lines[0] == "программа создана" and "этап M3 добавлен" in lines
    data = program.load(root)
    assert data["plan"] == ".autopilot/PROGRAM-PLAN.md" and len(data["constraints"]) == 3
    assert [q["stage"] for q in data["questions"]] == ["M1", "M2", None]
    m2 = data["stages"][1]
    assert m2["deliverable"] == "code" and m2["size"] == "T1" and m2["dependsOn"] == ["M1"]
    text = program.brief(data, m2)
    assert text.startswith("full: M2. Недельная сводка — раз в неделю бот присылает")
    for needle in ("Не входит в этап: графики", "Критерии сдачи этапа:", "Опирается на сданные этапы:\n- M1: таблица `expenses`",
                   "Передаёт следующим этапам: функция `weekly_summary`", "Прочитать до спецификации: `docs/idea.md` §3",
                   "Ограничения и решения программы:\n- Python 3.11+"):
        assert needle in text, needle
    assert "Результат этапа — документы" not in text


def test_plan_load_merges_without_touching_started(proj):
    plan_file = proj / "PLAN2.md"
    plan_file.write_text(TEMPLATE, encoding="utf-8")
    program.cmd_start(proj, "M1", adopt=False)
    lines = program.cmd_plan_load(proj, plan_file)
    assert "этап M1 не тронут (идёт)" in lines and "этап M2 обновлён" in lines and "этап M3 добавлен" in lines
    data = program.load(proj)
    assert data["stages"][0]["task"] == "M1: подсчёт строк" and data["stages"][1]["title"] == "Недельная сводка"


def test_plan_load_refuses_broken_plan(proj):
    plan_file = proj / "bad.md"
    plan_file.write_text("# План программы: x\n", encoding="utf-8")
    with pytest.raises(program.ProgramError, match="не прошёл проверку"):
        program.cmd_plan_load(proj, plan_file)


def test_partial_delivery_and_continuation(proj):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj, reqList=[{"id": "R01", "text": "считает строки", "status": "done"},
                                {"id": "R02", "text": "считает символы Unicode", "status": "deferred", "why": "не уместилось"},
                                {"id": "R03", "text": "токен бота", "status": "placeholder", "why": "ждёт владельца"}])
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    verdict = program.cmd_check(proj, "M1", record=True, with_gate=False)
    assert verdict["verdict"] == "passed" and verdict["partial"] is True
    assert verdict["deferred"] == [{"id": "R02", "text": "считает символы Unicode", "why": "не уместилось"}]
    assert verdict["placeholders"][0]["id"] == "R03"
    assert program.cmd_stage_continue(proj, "M1") == "этап M1: часть 2 — доделать отложенное (1)"
    stage = program.load(proj)["stages"][0]
    assert stage["status"] == "pending" and stage["part"] == 2 and stage["parts"][0]["part"] == 1
    program.cmd_start(proj, "M1", adopt=False)
    text = program.cmd_prompt(proj, "M1", manual=False)
    assert "Это продолжение этапа M1 (часть 2)" in text and "- R02: считает символы Unicode (отложено: не уместилось)" in text


def test_continue_refuses_full_delivery_and_fourth_part(proj):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj)
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    program.cmd_check(proj, "M1", record=True, with_gate=False)
    with pytest.raises(program.ProgramError, match="не сдан частично"):
        program.cmd_stage_continue(proj, "M1")
    data = program.load(proj)
    data["stages"][0].update(part=3, verdict={"partial": True, "deferred": []})
    program.save(proj, data)
    with pytest.raises(program.ProgramError, match="дальше решает владелец"):
        program.cmd_stage_continue(proj, "M1")


def test_cli_plan_check_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text(TEMPLATE, encoding="utf-8")
    assert program.main(["plan-check", str(good)]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text("# x\n", encoding="utf-8")
    assert program.main(["plan-check", str(bad)]) == 1
    capsys.readouterr()
    assert program.main(["plan-template"]) == 0
    assert capsys.readouterr().out.startswith("# План программы:")


def codex_session(home, name, rate_limits, mtime=None):
    folder = home / ".codex" / "sessions" / "2026" / "10" / "23"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    event = {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": rate_limits}}
    path.write_text(json.dumps({"type": "session_meta"}) + "\n" + json.dumps(event) + "\n", encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


def test_codex_usage_reads_latest_rate_limits(home, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert program.codex_usage()["plan"]["status"] == "unavailable"
    codex_session(home, "old.jsonl", {"primary": {"used_percent": 10.0, "window_minutes": 10080, "resets_at": 1793082797}}, mtime=1)
    codex_session(home, "new.jsonl", {"plan_type": "pro",
                                      "primary": {"used_percent": 91.0, "window_minutes": 300, "resets_at": 1793000000},
                                      "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 1793082797}})
    usage = program.codex_usage()
    assert usage["plan"]["status"] == "ok" and usage["plan"]["source"] == "new.jsonl"
    assert [(w["label"], w["percentUsed"]) for w in usage["plan"]["windows"]] == [("5-hour limit (Codex)", 91.0), ("Weekly (Codex)", 40.0)]
    decision = program.cmd_limits(usage, "start")
    assert decision["decision"] == "pause" and decision["window"] == "5-hour limit (Codex)"
    assert decision["resetsAt"].startswith("2026-")


def test_cli_limits_codex(home, monkeypatch, capsys):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    codex_session(home, "s.jsonl", {"primary": {"used_percent": 12.0, "window_minutes": 10080, "resets_at": 1793082797}})
    assert program.main(["limits", "--phase", "running", "--codex"]) == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "go"}


def test_links_line_points_to_both_dashboards(proj):
    port = program.page_port(proj)
    assert program.links_line(proj) == (f"Дашборд: [программа](http://localhost:{port}/program.html) · "
                                        f"[текущий прогон](http://localhost:{port}/dashboard.html)")


def test_cli_track_prints_links(proj, capsys):
    assert program.main(["--project", str(proj), "track"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("M1 ○") and out[1].startswith("Дашборд: [программа](http://localhost:")


def test_ensure_server_starts_once_and_is_ours(proj, monkeypatch):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(program, "page_port", lambda root: port)
    assert program.server_state(port) == "down"
    try:
        assert program.ensure_server(proj).startswith("сервер дашборда поднят")
        assert program.server_state(port) == "ours"
        assert program.ensure_server(proj).startswith("сервер дашборда работает")
        # T21.11: панель открывает конфигурацию по origin без пути — корень редиректит на program.html
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as reply:
            assert reply.geturl().endswith("/program.html")
            assert program.PAGE_MARKER in reply.read(8192).decode("utf-8", "replace")
    finally:
        pid = int((proj / ".autopilot" / "program-serve.pid").read_text(encoding="utf-8"))
        import os, signal
        os.kill(pid, signal.SIGTERM)


def test_serve_foreground_waits_instead_of_replacing_the_kit_server(proj, monkeypatch):
    # D25/T21.11: пока порт держит фоновый сервер kit, конфигурация launch.json (serve --foreground) просто ждёт
    import http.server
    import socket
    import time as time_module
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(program, "page_port", lambda root: port)
    states = iter(["ours", "ours", "down"])  # если ours — ждём; как только «освободился» — пошли bind'ить
    monkeypatch.setattr(program, "server_state", lambda p: next(states, "down"))
    sleeps = []
    monkeypatch.setattr(time_module, "sleep", lambda seconds: sleeps.append(seconds))
    bound = []

    class StubServer(http.server.ThreadingHTTPServer):
        def __init__(self, address, *args, **kwargs):
            bound.append(address)
            raise OSError("test: до bind не должно дойти, пока сервер kit «ours»")

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", StubServer)
    with pytest.raises(OSError, match="test"):
        program.cmd_serve_foreground(proj)
    assert sleeps == [30] and bound == [("127.0.0.1", port)]


def test_watch_survives_an_unreadable_program_folder(proj, tmp_path, monkeypatch):
    # D45: «Access is denied» на одной программе (сетевой диск) ронял сторожа для всех — сутки без пробуждений и серверов
    program.cmd_start(proj, "M1", adopt=False)
    program.register_program(proj, "ok")
    program.register_program(tmp_path / "locked", "locked")
    real = program.program_path

    def guarded(root):
        if root.name == "locked":
            raise PermissionError(5, "Access is denied")
        return real(root)

    monkeypatch.setattr(program, "program_path", guarded)
    results = program.cmd_watch()
    locked = [r for r in results if r["root"].endswith("locked")][0]
    assert locked["action"] == "none" and "папка недоступна" in locked["note"]
    assert any(r["root"] == str(proj.resolve()) for r in results)


def test_server_state_tells_a_hung_server_from_a_free_port(proj):
    # D45: зависший сервер ("stuck") не считается свободным портом — иначе рядом копились дубли (6 штук на Strata)
    import socket
    import threading
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def drop():  # принять соединение и оборвать его, не ответив
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=drop, daemon=True).start()
    try:
        assert program.server_state(port) == "stuck"
    finally:
        listener.close()
    assert program.server_state(port) == "down"


def test_stage_prompt_tells_stage_to_message_orchestrator_and_notify(proj):
    program.cmd_start(proj, "M1", adopt=False)
    text = program.cmd_prompt(proj, "M1", manual=False)
    assert '`session_id: "parent"`' in text and "«Вопрос этапа M1 · " in text
    assert "«Этап M1 спрашивает — ответь в чате оркестратора»" in text
    assert "«Этап M1 сдан: <итог одной строкой>»" in text and "{stage}" not in text


def test_stage_prompt_opens_run_dashboard_in_its_panel(proj):
    program.cmd_start(proj, "M1", adopt=False)
    text = program.cmd_prompt(proj, "M1", manual=False)
    url = f"http://localhost:{program.page_port(proj)}/dashboard.html"
    assert f"`mcp__Claude_Browser__preview_start` с `url` = {url}" in text and "{dashboard}" not in text
    assert "`mcp__ccd_view__show_pane` с `pane: \"preview\"`" in text and "В конце каждого своего хода".lower() in text.lower()
    assert url in program.cmd_prompt(proj, "M1", manual=False, after_signal=True)


def deliver_m1(proj, **run):
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj, **run)
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    return program.cmd_check(proj, "M1", record=True, with_gate=False)


def test_leftovers_listed_and_block_next_until_triaged(proj):
    deliver_m1(proj, concerns=["facade.py:427 — гонка"], report=["robots не проверяется у редиректа"])
    left = program.cmd_leftovers(proj, "M1", done=False, note=None)
    assert left["count"] == 2 and not left["acceptedAsIs"]  # замечание и «осталось»; допущения — не остаток
    assert left["concerns"] == ["facade.py:427 — гонка"] and left["left"] == ["robots не проверяется у редиректа"]
    result = program.cmd_next(proj)
    assert not result["ready"] and result["untriaged"] == ["M1"] and "program.py leftovers M1" in result["why"]
    with pytest.raises(program.ProgramError, match="--note"):
        program.cmd_leftovers(proj, "M1", done=True, note=None)
    assert program.cmd_leftovers(proj, "M1", done=True, note="robots — в M2; гонка — в M2").startswith("остаток этапа M1 разобран")
    assert program.cmd_next(proj)["ready"] is True


def test_accepted_as_is_keeps_failures_and_blind_mismatches(proj):
    verdict = deliver_m1(proj, gates={"G4": {"ok": False}}, blind={"mismatches": ["R07 — статус не виден"]})
    assert verdict["verdict"] == "failed"
    program.cmd_stage_set(proj, "M1", "passed", "принято владельцем: как есть")
    left = program.cmd_leftovers(proj, "M1", done=False, note=None)
    assert left["acceptedAsIs"] is True and left["blind"] == ["R07 — статус не виден"]
    assert "G4 (слепая приёмка) не пройден" in left["failures"]
    assert "расхождений приёмки 1" in left["summary"]
    with pytest.raises(program.ProgramError, match="не сдан"):
        program.cmd_leftovers(proj, "M2", done=False, note=None)


def test_stage_without_leftovers_needs_no_triage(proj):
    deliver_m1(proj)
    assert program.cmd_leftovers(proj, "M1", done=False, note=None)["count"] == 0
    assert program.cmd_next(proj)["ready"] is True


def test_flaky_tests_of_the_stage_become_leftovers(proj):
    tests = {"tests/test_a.py::test_net": {"count": 2, "first": stamp(5), "last": stamp(5)},
             "tests/test_b.py::test_old": {"count": 1, "first": stamp(-600), "last": stamp(-600)}}  # до старта этапа
    (proj / ".autopilot-kit" / "flaky.json").write_text(json.dumps({"tests": tests}), encoding="utf-8")
    verdict = deliver_m1(proj)
    assert verdict["verdict"] == "passed"
    assert verdict["flaky"] == ["tests/test_a.py::test_net (упал и прошёл при повторе: 2 раз)"]
    left = program.cmd_leftovers(proj, "M1", done=False, note=None)
    assert left["count"] == 1 and left["summary"] == "нестабильных тестов 1"
    assert program.cmd_next(proj)["ready"] is False


FAKE_CODEX = '''
import json, sys, pathlib
argv = sys.argv[1:]
pathlib.Path(__file__).with_name("calls.jsonl").open("a", encoding="utf-8").write(json.dumps(argv, ensure_ascii=False) + chr(10))
out = argv[argv.index("-o") + 1]
resume = argv[:2] == ["exec", "resume"]
if not resume:
    print(json.dumps({"type": "thread.started", "thread_id": "t-123"}))
print(json.dumps({"type": "turn.started"}))
print(json.dumps({"type": "turn.completed"}))
pathlib.Path(out).write_text("Продолжил" if resume else "Вопрос этапа M1 · брифинг: формат вывода?", encoding="utf-8")
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    path = tmp_path / "fakebin" / "codex.py"
    path.parent.mkdir()
    path.write_text(FAKE_CODEX, encoding="utf-8")
    monkeypatch.setenv("CODEX_CLI_PATH", str(path))
    return path.with_name("calls.jsonl")


def wait_exit(proj, sid):
    import time
    for _ in range(100):
        status = program.cmd_codex_status(proj, sid)
        if status["process"] == "exited":
            return status
        time.sleep(0.1)
    raise AssertionError("fake codex did not exit")


def test_codex_prompt_uses_dollar_skills_and_text_questions(proj):
    program.cmd_start(proj, "M1", adopt=False)
    data = program.load(proj)
    text = program.codex_stage_prompt(data, data["stages"][0])
    assert "$autopilot-roles" in text and "$autopilot с аргументами" in text and "autopilot-stage" not in text
    assert "последним сообщением хода" in text and "request_user_input" in text and "codex exec resume" in text
    assert "«Этап M1 сдан: <итог одной строкой>»" in text and "-----\nsemi: M1: подсчёт строк" in text


def test_codex_stage_registers_long_jobs_and_status_reports_them(proj, fake_codex):
    # D47 для Codex: этап регистрирует долгую работу, оркестратор видит её состояние в codex-status и возобновляет этап
    program.cmd_start(proj, "M1", adopt=False)
    data = program.load(proj)
    text = program.codex_stage_prompt(data, data["stages"][0])
    assert "job set --label" in text and "{program_py}" not in text and "D47" in text
    program.cmd_codex_run(proj, "M1")
    program.cmd_job(proj, "set", "drv", probe_exit(1), stamp(600))
    program.cmd_job(proj, "set", "ok", probe_exit(0), stamp(600))
    program.cmd_job(proj, "set", "old", probe_exit(1), stamp(-5))
    jobs = {j["label"]: j for j in wait_exit(proj, "M1")["jobs"]}
    assert set(jobs) == {"drv", "ok", "old"} and jobs["ok"]["state"] == "alive"
    assert jobs["drv"]["state"] == "dead" and "job clear drv" in jobs["drv"]["message"]
    # D50: срок вышел при несданном этапе — «expired» с готовым текстом, а не молчание
    assert jobs["old"]["state"] == "expired" and "срок наблюдения" in jobs["old"]["message"] and "job clear old" in jobs["old"]["message"]


def test_codex_run_status_answer_cycle(proj, fake_codex):
    with pytest.raises(program.ProgramError, match="не начат"):
        program.cmd_codex_run(proj, "M1")
    program.cmd_start(proj, "M1", adopt=False)
    assert "codex exec запущен" in program.cmd_codex_run(proj, "M1")
    status = wait_exit(proj, "M1")
    assert status["threadId"] == "t-123" and status["lastEvent"] == "turn.completed"
    assert status["lastMessage"].startswith("Вопрос этапа M1") and status["check"]["verdict"] == "not_started"
    first = json.loads(fake_codex.read_text(encoding="utf-8").splitlines()[0])
    assert first[:5] == ["exec", "--json", "--sandbox", "workspace-write", "--approve-for-me"] and first[5] == "-o"
    assert "$autopilot-roles" in first[-1]
    assert "ответ отправлен (codex exec resume t-123" in program.cmd_codex_answer(proj, "M1", "одна строка")
    status = wait_exit(proj, "M1")
    assert status["lastMessage"] == "Продолжил"
    second = json.loads(fake_codex.read_text(encoding="utf-8").splitlines()[1])
    assert second[:4] == ["exec", "resume", "t-123", "--json"] and second[-1] == "одна строка"
    assert "program-runs/" in (proj / ".autopilot" / ".gitignore").read_text(encoding="utf-8")


def test_codex_run_custom_exec_args_kept_for_resume(proj, fake_codex):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_codex_run(proj, "M1", ["--sandbox", "workspace-write", "-c", "approval_policy=never"])
    wait_exit(proj, "M1")
    program.cmd_codex_answer(proj, "M1", "да")
    wait_exit(proj, "M1")
    calls = [json.loads(line) for line in fake_codex.read_text(encoding="utf-8").splitlines()]
    assert calls[0][2:6] == ["--sandbox", "workspace-write", "-c", "approval_policy=never"]
    assert calls[1][4:8] == ["--sandbox", "workspace-write", "-c", "approval_policy=never"]


def test_codex_answer_needs_a_finished_run(proj, monkeypatch):
    program.cmd_start(proj, "M1", adopt=False)
    with pytest.raises(program.ProgramError, match="не было запуска codex"):
        program.cmd_codex_answer(proj, "M1", "x")
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(program.ProgramError, match="codex не найден"):
        program.cmd_codex_run(proj, "M1")


def test_pid_alive_is_safe_on_this_os():
    import os
    assert program.pid_alive(os.getpid()) is True
    assert program.pid_alive(None) is False


def set_program_field(proj, **fields):
    path = program.program_path(proj)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def watched(proj):
    program.register_program(proj, "wc2")
    return [r for r in program.cmd_watch() if r["root"] == str(proj.resolve())][0]


def test_watch_wakes_an_interrupted_stage_once_then_notifies(proj):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-90))
    first = watched(proj)
    assert first["action"] == "wake_stage" and first["sessionId"] == "local_stage"
    assert "продолжай прогон Autopilot с места остановки" in first["message"] and "фонового субагента" in first["message"]
    again = watched(proj)
    assert again["action"] == "none" and "уже будили" in again["note"]
    memory_path = program.kit_home() / ".autopilot-kit" / "watch.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    for value in memory.values():
        value["at"] = stamp(-70)
    memory_path.write_text(json.dumps(memory), encoding="utf-8")
    third = watched(proj)
    assert third["action"] == "notify_owner" and "напишите «продолжай»" in third["message"]
    assert watched(proj)["action"] == "none"


@pytest.mark.parametrize("run, note", [
    (dict(stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-2)), "этап работает"),
    (dict(waiting={"kind": "briefing", "note": "?"}, updatedAt=stamp(-90)), "ждёт ответа владельца"),
])
def test_watch_leaves_working_and_waiting_stages(proj, run, note):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, **run)
    result = watched(proj)
    assert result["action"] == "none" and note in result["note"]


def probe_exit(code):
    import sys
    return f'"{sys.executable}" -c "import sys; sys.exit({code})"'


def memory_file():
    return program.kit_home() / ".autopilot-kit" / "watch.json"


def start_long_job(proj, code):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-3000))  # прогон молчит: тест идёт на сервере
    program.cmd_job(proj, "set", "r2", probe_exit(code), stamp(600))


def test_watch_trusts_a_live_long_job_over_a_silent_run(proj):
    # D47: Strata S2 — тест сутками на сервере, state прогона не меняется; живая работа не повод будить этап
    start_long_job(proj, 0)
    result = watched(proj)
    assert result["action"] == "none" and "«r2» жива" in result["note"]


def test_watch_wakes_the_stage_when_the_long_job_died_then_reminds_owner(proj):
    # D47: драйвер встал в 08:30, этап закончил ход без наблюдения — сторож сам видит остановку, будит, затем напоминает
    start_long_job(proj, 1)
    first = watched(proj)
    assert first["action"] == "wake_stage" and first["sessionId"] == "local_stage"
    assert "«r2»" in first["message"] and "job clear r2" in first["message"]
    assert watched(proj)["action"] == "none"
    memory = json.loads(memory_file().read_text(encoding="utf-8"))
    memory[f"{proj.resolve()}#job:r2"]["woken"] = stamp(-70)
    memory_file().write_text(json.dumps(memory), encoding="utf-8")
    second = watched(proj)
    assert second["action"] == "notify_owner" and "стоит уже" in second["message"]
    assert watched(proj)["action"] == "none"
    memory = json.loads(memory_file().read_text(encoding="utf-8"))
    memory[f"{proj.resolve()}#job:r2"]["remindedAt"] = stamp(-130)
    memory_file().write_text(json.dumps(memory), encoding="utf-8")
    assert watched(proj)["action"] == "notify_owner"  # не один пуш и тишина навсегда


def test_watch_does_not_wake_on_unreachable_server_and_job_expires(proj):
    # ssh не дозвонился (255) — это «не знаю», а не «упала»; срок работы вышел — снова обычные правила тишины
    start_long_job(proj, 255)
    result = watched(proj)
    assert result["action"] == "none" and "проверить не вышло" in result["note"]
    program.cmd_job(proj, "set", "r2", probe_exit(1), stamp(-5))
    expired = watched(proj)  # D50: срок вышел при несданном этапе — не «возможно, прерывание», а явное «срок наблюдения вышел»
    assert expired["action"] == "wake_stage" and "срок наблюдения" in expired["note"] and "job set" in expired["message"]


def test_watch_expired_job_wakes_then_reminds_owner_and_resets_on_extend(proj):
    # D50 (Strata S2, 07.11): наблюдение заведено до 18:30Z, цепочка работ идёт до 01:30Z — после срока никто бы не следил
    start_long_job(proj, 0)
    program.cmd_job(proj, "set", "r2", probe_exit(0), stamp(-5))  # проверка «жива», но срок вышел — всё равно не молчим
    first = watched(proj)
    assert first["action"] == "wake_stage" and first["sessionId"] == "local_stage"
    assert "вышел" in first["message"] and "отвечает «жива»" in first["message"] and "job clear r2" in first["message"]
    assert watched(proj)["action"] == "none"
    memory = json.loads(memory_file().read_text(encoding="utf-8"))
    memory[f"{proj.resolve()}#job:r2"]["woken"] = stamp(-70)
    memory_file().write_text(json.dumps(memory), encoding="utf-8")
    second = watched(proj)
    assert second["action"] == "notify_owner" and "не продлено" in second["message"]
    # продлил (job set — новая запись) — состояние начинается заново: упала после продления будит этап сразу
    program.cmd_job(proj, "set", "r2", probe_exit(1), stamp(600))
    assert watched(proj)["action"] == "wake_stage"
    program.cmd_job(proj, "clear", "r2", None, None)
    assert "срок наблюдения" not in (watched(proj).get("note") or "")


def test_watch_ignores_expired_job_of_an_earlier_stage_or_a_working_run(proj):
    start_long_job(proj, 0)
    program.cmd_job(proj, "clear", "r2", None, None)
    program.cmd_job(proj, "set", "old", probe_exit(1), stamp(-5))
    data = program.load(proj)
    data["jobs"][0]["since"] = stamp(-100000)  # заведена до начала этого этапа
    program.save(proj, data)
    assert "срок наблюдения" not in (watched(proj).get("note") or "")
    data = program.load(proj)
    data["jobs"][0]["since"] = program.now()
    program.save(proj, data)
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-2))  # прогон идёт — этап и так виден
    assert watched(proj)["action"] == "none"


def test_job_set_from_cli_checks_probe_and_warns(proj):
    program.cmd_start(proj, "M1", adopt=False)
    with pytest.raises(program.ProgramError, match="не проходит"):
        program.cmd_job(proj, "set", "r2", probe_exit(1), stamp(60), check=True)
    with pytest.raises(program.ProgramError, match="в прошлом"):
        program.cmd_job(proj, "set", "r2", probe_exit(0), stamp(-5), check=True)
    text = program.cmd_job(proj, "set", "r2", probe_exit(0), stamp(60), check=True)
    assert "ВНИМАНИЕ" in text and "признак движения" in text and "срок вышел" in text
    assert json.loads(program.cmd_job(proj, "list", None, None, None))[0]["label"] == "r2"
    assert any("саму проверку" in w for w in program.probe_warnings("pgrep -f dfab"))
    assert not any("саму проверку" in w for w in program.probe_warnings("pgrep -f '[d]fab'"))
    assert not any("саму проверку" in w for w in program.probe_warnings("tmux has-session -t dfab"))
    assert program.probe_warnings("pgrep -f '[d]fab' && find run.log -mmin -15 | grep -q .") == []


def test_job_commands_validate_and_clear(proj):
    program.cmd_start(proj, "M1", adopt=False)
    with pytest.raises(program.ProgramError, match="--probe"):
        program.cmd_job(proj, "set", "r2", None, None)
    with pytest.raises(program.ProgramError, match="не дата"):
        program.cmd_job(proj, "set", "r2", "true", "завтра")
    program.cmd_job(proj, "set", "r2", "true", stamp(60))
    assert "r2" in program.cmd_job(proj, "list", None, None, None)
    program.cmd_job(proj, "clear", "r2", None, None)
    assert program.cmd_job(proj, "list", None, None, None).strip() == "[]"
    assert "job set" in program.stage_prompt(program.load(proj), program.stage_of(program.load(proj), "M1"))


def test_watch_wakes_the_delivered_stage_when_next_did_not_start(proj):
    deliver_m1(proj)
    program.cmd_bind(proj, "M1", "local_m1")
    set_program_field(proj, updatedAt=stamp(-25))
    result = watched(proj)
    assert result["action"] == "wake_stage" and result["sessionId"] == "local_m1"
    assert "сообщи оркестратору итог этапа" in result["message"]


def test_watch_respects_pause_codex_and_missing_programs(proj, tmp_path):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "codex-exec:123")
    assert "оркестратор Codex следит сам" in watched(proj)["note"]
    program.cmd_pause(proj, stamp(60), "5-hour limit")
    assert "пауза по лимиту" in watched(proj)["note"]
    program.register_program(tmp_path / "gone", "x")
    gone = [r for r in program.cmd_watch() if r["root"].endswith("gone")][0]
    assert gone["action"] == "none" and "нет на диске" in gone["note"]


def test_watch_prompt_executes_only_script_decisions():
    text = program.watch_prompt()
    assert "watch --json" in text and "`mcp__ccd_session_mgmt__send_message`" in text
    assert "`isRunning: true` — пропусти" in text and "не запускаешь сессии" in text


def test_watch_wakes_at_once_after_a_reboot(proj, monkeypatch):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-5))
    assert watched(proj)["action"] == "none"  # 5 минут тишины без перезагрузки — работает
    monkeypatch.setattr(program, "boot_time", lambda: datetime.now(timezone.utc) - timedelta(minutes=2))
    result = watched(proj)
    assert result["action"] == "wake_stage" and "(с перезагрузки)" in result["note"]


def test_watch_wakes_the_registered_orchestrator_between_stages(proj):
    # D31: оркестратор начнёт этап через резерв и из хода, начатого сообщением сторожа
    deliver_m1(proj)
    program.cmd_bind(proj, "M1", "local_m1")
    program.cmd_orchestrator(proj, "local_orch")
    set_program_field(proj, updatedAt=stamp(-25))
    result = watched(proj)
    assert result["action"] == "wake_orchestrator" and result["sessionId"] == "local_orch"
    assert "pool take" in result["message"] and "Ничего у владельца не спрашивай" in result["message"]
    assert watched(proj)["action"] == "none"  # один раз, дальше — эскалация как у wake_stage


def test_watch_wakes_orchestrator_when_a_delivered_run_is_not_recorded(proj):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    program.cmd_orchestrator(proj, "local_orch")
    finished_run(proj, updatedAt=stamp(-20))
    write_progress(proj)
    commit(proj, program.LANDING_SUBJECT)
    result = watched(proj)
    assert result["action"] == "wake_orchestrator" and "программа не учла" in result["note"]


def test_pool_keeps_reserve_sessions_and_signal_carries_the_stage_brief(proj):
    assert program.cmd_pool(proj, "need", None) == str(program.pool_target(program.load(proj)))
    program.cmd_pool(proj, "add", "local_r1")
    program.cmd_pool(proj, "add", "local_r1")  # повтор не дублирует
    program.cmd_pool(proj, "add", "local_r2")
    assert program.cmd_pool(proj, "need", None) == "0"
    assert program.cmd_pool(proj, "take", None) == "local_r1"
    assert program.cmd_pool(proj, "need", None) == "1"
    program.cmd_pool(proj, "take", None)
    with pytest.raises(program.ProgramError, match="резерв пуст"):
        program.cmd_pool(proj, "take", None)
    program.cmd_start(proj, "M1", adopt=False)
    signal = program.cmd_signal(proj, "M1")
    assert signal.startswith("Задание этапа M1: ") and program.cmd_prompt(proj, "M1", manual=False) in signal
    pool_text = program.pool_prompt(program.load(proj))
    assert "«Резерв готов»" in pool_text and "«Задание этапа»" in pool_text and "set_session_title" in pool_text


def test_watch_prompt_archives_its_own_chat():
    text = program.watch_prompt()
    assert "`wake_stage` или `wake_orchestrator`" in text
    assert "archive_session" in text and '"self"' in text


def test_boot_time_is_in_the_past():
    boot = program.boot_time()
    assert boot is None or boot < datetime.now(timezone.utc)


def test_mode_switches_next_stages_and_init_defaults_to_full(proj, tmp_path):
    assert program.cmd_mode(proj, "full") == "режим прогонов: semi → full (для этапов, которые ещё не начаты)"
    program.cmd_start(proj, "M1", adopt=False)
    assert program.cmd_prompt(proj, "M1", manual=False).count("full: M1: подсчёт строк") == 1
    with pytest.raises(program.ProgramError):
        program.cmd_mode(proj, "turbo")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert program.main(["--project", str(fresh), "init", "--goal", "x"]) == 0
    assert program.load(fresh)["mode"] == "full"


def test_mode_updates_the_plan_line_too(tmp_path):
    root = tmp_path / "p"
    (root / ".autopilot").mkdir(parents=True)
    plan_file = root / ".autopilot" / "PROGRAM-PLAN.md"
    plan_file.write_text(TEMPLATE.replace("- Режим прогонов: full", "- Режим прогонов: semi"), encoding="utf-8")
    program.cmd_plan_load(root, plan_file)
    assert program.load(root)["mode"] == "semi"
    assert program.cmd_mode(root, "full").endswith("; в .autopilot/PROGRAM-PLAN.md тоже")
    assert "- Режим прогонов: full" in plan_file.read_text(encoding="utf-8")


def test_full_autonomy_answers_open_questions_by_recommendation(proj):
    program.cmd_ask(proj, "Q1", "Платный поиск?", "нет, встроенный поиск хоста", None)
    result = program.cmd_next(proj)
    assert result["ready"] is True and result["autoAnswered"] == [
        {"id": "Q1", "question": "Платный поиск?", "answer": "нет, встроенный поиск хоста"}]
    assert "(автоответ по рекомендации, владелец может поменять)" in result["brief"]
    assert program.load(proj)["questions"][0]["by"] == "auto"


def test_failed_stage_repair_once_then_accept(proj):
    deliver_m1(proj, tickets=[{"id": "01", "status": "failed"}])
    assert program.load(proj)["stages"][0]["status"] == "failed"
    assert program.cmd_stage_repair(proj, "M1").startswith("этап M1: ремонт 1")
    stage = program.load(proj)["stages"][0]
    assert stage["status"] == "running" and stage["failures"][0]["verdict"] == "failed"
    finished_run(proj, tickets=[{"id": "01", "status": "failed"}], startedAt=stamp(1))
    program.cmd_check(proj, "M1", record=True, with_gate=False)
    with pytest.raises(program.ProgramError, match="уже ремонтировали"):
        program.cmd_stage_repair(proj, "M1")
    assert "принят автоматически" in program.cmd_stage_accept(proj, "M1", None)
    left = program.cmd_leftovers(proj, "M1", done=False, note=None)
    assert left["acceptedAsIs"] is True and any("таск 01" in f for f in left["failures"])


def test_owner_tasks_do_not_block_and_show_in_view_and_report(proj):
    assert program.cmd_owner_task(proj, "add", "поставить библиотеки Chromium в WSL (sudo)", "M1") == \
        "задача владельца T1: поставить библиотеки Chromium в WSL (sudo)"
    assert program.cmd_next(proj)["ready"] is True
    view = program.view_path(proj).read_text(encoding="utf-8")
    assert "- T1 (этап M1). поставить библиотеки Chromium в WSL (sudo)" in view
    assert "## Задачи для владельца" in program.cmd_report(proj)
    program.cmd_owner_task(proj, "done", "T1", None)
    assert "## Задачи для владельца\n\n—" in program.view_path(proj).read_text(encoding="utf-8")


@pytest.fixture
def bare_git(tmp_path, monkeypatch):
    """git без глобального автора коммитов, как на машине владельца."""
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo


def test_git_identity_is_set_locally_when_missing(bare_git):
    assert program.ensure_git_identity(bare_git) == ["user.name=Autopilot", "user.email=autopilot@localhost"]
    out = program.git(bare_git, "config", "--local", "user.name")
    assert out.strip() == "Autopilot"
    # теперь коммит проходит без -c
    (bare_git / "a.txt").write_text("x", encoding="utf-8")
    assert program.git(bare_git, "add", "a.txt") is not None
    assert program.git(bare_git, "commit", "-q", "-m", "c") is not None
    assert program.ensure_git_identity(bare_git) == []


def test_git_identity_keeps_existing_values(bare_git):
    program.git(bare_git, "config", "--local", "user.name", "Owner")
    assert program.ensure_git_identity(bare_git) == ["user.email=autopilot@localhost"]
    assert program.git(bare_git, "config", "user.name").strip() == "Owner"


def test_git_identity_outside_repo_does_nothing(tmp_path, bare_git):
    folder = tmp_path / "plain"
    folder.mkdir()
    assert program.ensure_git_identity(folder) == []


def test_cli_sets_identity_before_any_program_command(bare_git, home, capsys):
    program.cmd_init(bare_git, "g", "PLAN.md", "full")
    assert program.main(["--project", str(bare_git), "status"]) == 0
    assert "поставлен локально" in capsys.readouterr().err
    assert program.git(bare_git, "config", "--local", "user.email").strip() == "autopilot@localhost"


def test_pool_drop_removes_dead_session_and_refills_need(proj):
    program.cmd_pool(proj, "add", "local_old1")
    program.cmd_pool(proj, "add", "local_old2")
    assert program.cmd_pool(proj, "need", None) == "0"  # мёртвые записи считались бы полным резервом
    assert "убрана local_old1" in program.cmd_pool(proj, "drop", "local_old1")
    assert program.cmd_pool(proj, "drop", "local_old1").endswith("не было)")  # повтор безопасен
    program.cmd_pool(proj, "drop", "local_old2")
    assert program.cmd_pool(proj, "need", None) == str(program.pool_target(program.load(proj)))
    assert json.loads(program.cmd_pool(proj, "list", None)) == []
    with pytest.raises(program.ProgramError):
        program.cmd_pool(proj, "drop", None)


def test_watch_reports_reserve_ids_and_prompt_drops_dead_ones(proj, monkeypatch):
    program.cmd_pool(proj, "add", "local_r1")
    item = program.watch_program(proj, {})
    assert item["pool"] == ["local_r1"]
    prompt = program.watch_prompt()
    assert "pool drop" in prompt and "get_session" in prompt and "isArchived" in prompt
    assert "6. Ответь одной строкой" in prompt and "7. Затем убери этот чат" in prompt
    assert "foreign: true" in prompt  # D48: программу чужого профиля сторож не трогает


def start_unbound(proj, minutes_ago):
    program.cmd_start(proj, "M1", adopt=False)  # `start` без `bind`: сессии у этапа нет
    path = program.program_path(proj)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["stages"][0]["startedAt"] = stamp(-minutes_ago)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_watch_wakes_orchestrator_for_a_started_stage_without_session(proj):
    program.cmd_orchestrator(proj, "local_orch")
    start_unbound(proj, 20)
    result = watched(proj)
    assert result["action"] == "wake_orchestrator" and result["sessionId"] == "local_orch"
    assert result["stage"] == "M1" and "сессии у него нет" in result["message"] and "bind" in result["message"]
    again = watched(proj)  # одного пробуждения достаточно, дальше — ждём и эскалируем
    assert again["action"] == "none" and "уже будили" in again["note"]


def test_watch_notifies_owner_when_the_unbound_stage_stays_unbound(proj):
    program.cmd_orchestrator(proj, "local_orch")
    start_unbound(proj, 20)
    assert watched(proj)["action"] == "wake_orchestrator"
    registry = program.kit_home() / ".autopilot-kit" / "watch.json"
    memory = json.loads(registry.read_text(encoding="utf-8"))
    key = str(proj.resolve())
    memory[key]["at"] = stamp(-(program.WATCH_ESCALATE_MIN + 5))
    registry.write_text(json.dumps(memory), encoding="utf-8")
    result = watched(proj)
    assert result["action"] == "notify_owner" and "продолжай" in result["message"]
    assert watched(proj)["action"] == "none"  # уведомление — один раз


@pytest.mark.parametrize("minutes_ago, orchestrator", [(5, True), (30, False)])
def test_watch_leaves_a_fresh_or_unregistered_unbound_stage(proj, minutes_ago, orchestrator):
    if orchestrator:
        program.cmd_orchestrator(proj, "local_orch")
    start_unbound(proj, minutes_ago)
    result = watched(proj)
    assert result["action"] == "none" and result["note"] == "этап работает"


def test_setup_check_reports_what_init_would_install(tmp_path, home):
    folder = tmp_path / "newproj"
    folder.mkdir()
    fresh = json.loads(program.cmd_setup_check(folder))
    assert fresh["configured"] is False and fresh["git"] is False and fresh["kitRepository"] is False
    assert ".autopilot-kit/project.toml" in fresh["missing"] and "AGENTS.md" in fresh["missing"]

    from kit import project
    project.init_project("generic", folder)
    done = json.loads(program.cmd_setup_check(folder))
    assert done["configured"] is True and done["missing"] == []  # шаблон кладёт всё, включая хуки Claude и Codex
    git(folder, "init", "-q", "-b", "main")
    assert json.loads(program.cmd_setup_check(folder))["git"] is True


def test_setup_check_is_a_cli_command_and_flags_the_kit_repository(tmp_path, home, capsys):
    folder = tmp_path / "kitlike"
    (folder / "kit").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("", encoding="utf-8")
    assert program.main(["--project", str(folder), "setup-check"]) == 0
    assert json.loads(capsys.readouterr().out)["kitRepository"] is True


def test_pool_take_json_recycles_a_delivered_stage_chat_before_the_reserve(proj):
    # D40: сессию из хода по сообщению не запустить — чат сданного этапа очищают и отдают следующему этапу
    program.cmd_orchestrator(proj, "local_orch")
    program.cmd_pool(proj, "add", "local_r1")
    deliver_m1(proj)
    program.cmd_bind(proj, "M1", "local_m1")
    first = json.loads(program.cmd_pool(proj, "take", None, as_json=True))
    assert first == {"sessionId": "local_m1", "clear": True, "from": "этап M1"}
    second = json.loads(program.cmd_pool(proj, "take", None, as_json=True))  # тот же чат второй раз не отдаётся
    assert second == {"sessionId": "local_r1", "clear": False, "from": "резерв"}
    with pytest.raises(program.ProgramError, match="резерв пуст и чатов сданных этапов нет"):
        program.cmd_pool(proj, "take", None, as_json=True)


def test_recyclable_skips_busy_codex_and_orchestrator_chats(proj):
    program.cmd_orchestrator(proj, "local_orch")
    deliver_m1(proj)
    for session in ("local_orch", "codex-exec:7"):
        program.cmd_bind(proj, "M1", session)
        assert program.recyclable(program.load(proj)) == []
    program.cmd_bind(proj, "M1", "local_m1")
    program.cmd_start(proj, "M2", adopt=False)
    program.cmd_bind(proj, "M2", "local_m1")  # чат уже работает на M2 — не отдаётся
    assert program.recyclable(program.load(proj)) == []


def test_signal_tells_a_cleared_chat_to_rename_itself(proj):
    program.cmd_start(proj, "M1", adopt=False)
    signal = program.cmd_signal(proj, "M1")
    assert "Переименуй этот чат в «Этап M1: Ядро»" in signal and "set_session_title" in signal


def test_watch_tells_owner_once_when_no_chat_can_take_the_next_stage(proj):
    # D40: ни резерва, ни чата сданного этапа — будить оркестратора бесполезно, сразу владельцу, один раз
    program.cmd_orchestrator(proj, "local_orch")
    deliver_m1(proj)
    program.cmd_bind(proj, "M1", "local_m1")
    program.cmd_pool(proj, "take", None, as_json=True)  # чат M1 уже отдан
    set_program_field(proj, updatedAt=stamp(-25))
    result = watched(proj)
    assert result["action"] == "notify_owner" and result["stage"] == "M2"
    assert "свободных чатов нет" in result["message"] and "«продолжай»" in result["message"]
    assert watched(proj)["action"] == "none"


def test_watch_messages_teach_clear_before_signal():
    for text in (program.CONTINUE_PROGRAM, program.UNBOUND_STAGE):
        assert "pool take --json" in text and "clear_session" in text and "start_session` в этом ходе" in text


def test_report_metrics_from_gate_log(proj, capsys):
    program.cmd_ask(proj, "Q1", "Формат?", "одна строка", "M1")
    program.cmd_answer(proj, "Q1", "две строки", assumption=False)
    program.cmd_ask(proj, "Q2", "Кодировка?", "UTF-8", "M1")
    program.cmd_answer(proj, "Q2", None, assumption=True)
    log = [{"at": stamp(1), "stage": "M1", "result": "block", "commands": [{"command": "pytest", "code": 1, "seconds": 30}]},
           {"at": stamp(2), "stage": "M1", "result": "loop-release", "flaky": ["t.py::a"]},
           {"at": stamp(3), "stage": "M1", "result": "pass", "flaky": ["t.py::a", "t.py::b"]},
           {"at": stamp(4), "stage": None, "result": "skip-program-chat"}]
    (proj / ".autopilot-kit" / "gate_log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in log) + "\nне json\n", encoding="utf-8")
    deliver_m1(proj)
    data = json.loads(program.program_path(proj).read_text(encoding="utf-8"))
    data["stages"][0]["repairs"] = 1
    data["stages"].append({**data["stages"][1], "id": "M1f", "title": "Долг M1"})
    program.program_path(proj).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    row = program.stage_metrics(data, data["stages"][0], program.read_gate_log(proj))
    assert row["runs"] == 3 and row["blocks"] == 1 and row["releases"] == 1 and row["flaky"] == 2
    assert row["owner"] == 1 and row["auto"] == 1 and row["repairs"] == 1 and row["debt"] is True
    assert row["verdict"] == "сдан" and "мин" in row["duration"]
    text = program.cmd_metrics(proj)
    assert "| M1 | сдан |" in text and "| **Итого** | сдано 1 из 3 |" in text
    assert "Записей 4" in text and "вне этапов программы — 1" in text and "block 1" in text
    assert program.main(["--project", str(proj), "report", "--metrics"]) == 0
    assert "# Метрики программы" in capsys.readouterr().out


def test_report_metrics_without_log(proj):
    deliver_m1(proj)
    assert "Журнала нет" in program.cmd_metrics(proj)


def test_approval_question_is_never_answered_by_recommendation(proj):
    # D41: разрешение для проверки режима auto — только словами владельца; этап без него не начинается
    program.cmd_mode(proj, "full")
    program.cmd_ask(proj, "Q9", "скачать и запустить install.sh на сервере", "да", "M1", approval=True)
    decision = program.cmd_next(proj)
    assert decision["ready"] is False and decision["approvals"][0]["id"] == "Q9"
    for answer, assumption in ((None, False), (None, True), ("да", True)):
        with pytest.raises(program.ProgramError, match="разрешение владельца"):
            program.cmd_answer(proj, "Q9", answer, assumption)
    program.cmd_answer(proj, "Q9", "да, разрешаю", False)
    assert program.cmd_next(proj)["ready"] is True


def test_approve_writes_owner_auto_mode_settings_with_defaults_and_backup(proj, home):
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"theme": "dark", "autoMode": {"environment": ["моя запись"]}}), encoding="utf-8")
    out = program.cmd_approve(proj, "add", "на server-1 запустить install.sh из github.com/x/y", ["server-1 — доверенный"], "M1")
    assert "разрешение A1 записано" in out
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert data["autoMode"]["environment"] == ["моя запись", "server-1 — доверенный"]  # свой список без $defaults не трогаем
    assert data["autoMode"]["allow"][0] == "$defaults" and "install.sh" in data["autoMode"]["allow"][1]
    assert list(settings.parent.glob("settings.json.bak-*"))
    assert "уже были" in program.cmd_approve(proj, "add", "на server-1 запустить install.sh из github.com/x/y",
                                             ["server-1 — доверенный"], "M1")
    program.cmd_start(proj, "M1", adopt=False)
    assert "Заранее разрешено владельцем" in program.cmd_prompt(proj, "M1", manual=False)
    assert json.loads(program.cmd_approve(proj, "list", None, [], None))[0]["id"] == "A1"


def test_stage_rules_tell_stage_how_to_report_an_auto_mode_denial(proj):
    program.cmd_start(proj, "M1", adopt=False)
    text = program.cmd_prompt(proj, "M1", manual=False)
    assert "блок проверки прав (D41)" in text and "готовую фразу" in text


def test_watch_reminds_owner_every_two_hours_while_a_stage_waits(proj):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, waiting={"kind": "action", "note": "?"}, updatedAt=stamp(-30))
    assert watched(proj)["action"] == "none"
    write_run(proj, waiting={"kind": "action", "note": "?"}, updatedAt=stamp(-150))
    first = watched(proj)
    assert first["action"] == "notify_owner" and "ждёт вашего ответа уже 2 ч" in first["message"]
    assert watched(proj)["action"] == "none"  # следующее напоминание — через 2 часа


def test_page_polling_survives_lost_requests_and_shows_lost_link():
    # D44: скрытую панель приложение замораживает, запрос теряется без onload/onerror — раньше опрос обрывался навсегда
    html = program.page_template().read_text(encoding="utf-8")
    for needle in ("LOAD_TIMEOUT_MS = 8000", "setTimeout(() => end(false), LOAD_TIMEOUT_MS)", "setInterval(() => pull(), POLL_MS)",
                   "'visibilitychange'", "'resume'", "'pageshow'", "нет связи уже"):
        assert needle in html, needle
    assert "setTimeout(loop" not in html  # цепочка «следующий опрос после предыдущего» — та самая, что обрывалась


def test_page_is_refreshed_with_program_js_and_carries_its_build(proj):
    # открытая вкладка со старым кодом страницы узнаёт новую версию из program.js и перезагружается
    program.cmd_page(proj, launch=False)
    page = proj / ".autopilot" / program.PAGE_NAME
    build = program.page_build()
    assert build and f"const BUILD = '{build}'" in page.read_text(encoding="utf-8")
    assert f'"pageBuild": "{build}"' in (proj / ".autopilot" / "program.js").read_text(encoding="utf-8")
    page.write_text("старая страница", encoding="utf-8")
    program.cmd_orchestrator(proj, "local_orch")  # любая команда, что сохраняет программу
    assert f"const BUILD = '{build}'" in page.read_text(encoding="utf-8")
    assert "location.reload()" in page.read_text(encoding="utf-8") and "pageReloadAt" in page.read_text(encoding="utf-8")


# ── паузы и ожидание владельца (D46) ─────────────────────────────────────────

FAKE_ANSWERED_AP = '''import json, pathlib, sys
path = pathlib.Path(__file__).with_name("state.js")
state = json.loads(path.read_text(encoding="utf-8").split("=", 1)[1])
if sys.argv[1] == "answered" and state.get("waiting"):
    state.setdefault("waits", []).append({"kind": state["waiting"]["kind"]})
    state["waiting"] = None
    state["updatedAt"] = "2099-01-01T00:00:00+00:00"
path.write_text("window.STATE =\\n" + json.dumps(state, ensure_ascii=False), encoding="utf-8")
'''


@pytest.fixture
def waiting_stage(proj):
    """M1 идёт, сессия привязана, Autopilot четыре дня ждёт владельца (`ask action`), ap.py подставной."""
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-60 * 24 * 4),
              waiting={"kind": "action", "since": stamp(-60 * 24 * 4), "note": "пауза: ждём решения владельца"})
    (proj / ".autopilot" / "ap.py").write_text(FAKE_ANSWERED_AP, encoding="utf-8")
    return proj


def test_far_pause_date_shows_its_year_not_a_bare_day_month(proj):
    text = program.cmd_pause(proj, "2099-01-01T00:00:00Z", None)
    assert "2098" in text or "2099" in text  # местный пояс может сдвинуть на 31.12.2098 — год обязан быть виден
    assert program.cmd_pause(proj, "2026-10-23T11:12:00+03:00", "5-hour limit").startswith("Пауза до 23.10 ")


def test_owner_pause_has_reason_text_and_no_auto_resume(proj):
    text = program.cmd_pause(proj, None, None, "local_orch", reason="owner", text="останови все разработки")
    assert "по слову владельца" in text and "останови все разработки" in text
    assert "продолжу сам" not in text and "лимит" not in text and "resume" in text
    pause = program.load(proj)["pause"]
    assert (pause["reason"], pause["until"], pause["text"]) == ("owner", None, "останови все разработки")
    assert not program.auto_resumes(pause)
    assert program.cmd_track(proj).startswith("⏸ Пауза по слову владельца")
    assert "**Пауза по слову владельца" in program.view_path(proj).read_text(encoding="utf-8")
    with pytest.raises(program.ProgramError, match="--until"):
        program.cmd_pause(proj, None, None)
    with pytest.raises(program.ProgramError, match="--reason"):
        program.cmd_pause(proj, None, None, reason="кто-то")


def test_old_pause_record_without_reason_is_a_limit(proj):
    data = program.load(proj)
    data["pause"] = {"until": "2026-10-23T11:12:00+03:00", "window": "5-hour limit", "since": stamp(), "orchestrator": None}
    program.save(proj, data)
    assert program.pause_reason(data["pause"]) == "limit" and program.auto_resumes(data["pause"])
    assert "продолжу сам" in program.cmd_track(proj)


def test_watch_does_not_touch_owner_pause_even_without_until(proj):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_pause(proj, None, None, reason="owner", text="стоп")
    result = watched(proj)
    assert "пауза по слову владельца" in result["note"] and result["action"] == "none"


def test_resume_clears_pause_pause_tasks_and_stage_wait_in_one_command(waiting_stage):
    proj = waiting_stage
    program.cmd_pause(proj, None, None, "local_orch", reason="owner", text="стоп")
    program.cmd_owner_task(proj, "add", "ждём разрешения", "M1", kind="pause")
    assert "ждёт тебя (action)" in program.cmd_track(proj)
    out = program.cmd_resume(proj)
    assert "пауза снята" in out and "закрыты задачи владельца «ожидание паузы»: T1" in out
    assert "ожидание action этапа M1 снято" in out
    assert program.wake_task_id(proj) in out and "local_stage" in out and program.OWNER_RESUME_SIGNAL in out
    track = program.cmd_track(proj)
    assert "ждёт тебя" not in track and not track.startswith("⏸")
    assert program.read_run(proj)["waiting"] is None
    assert program.load(proj)["stages"][0]["status"] == "running"
    assert "Явных причин нет" in program.cmd_why_paused(proj)


def test_resume_keeps_wait_when_owner_task_still_holds_it(waiting_stage):
    proj = waiting_stage
    program.cmd_owner_task(proj, "add", "поставить пароль", "M1")
    out = program.cmd_resume(proj)
    assert "осталось" in out and "задача владельца T1" in out
    assert program.read_run(proj)["waiting"] is not None
    assert "ждёт тебя (action)" in program.cmd_track(proj)
    done = program.cmd_owner_task(proj, "done", "T1", None)
    assert "stage unwait M1" in done  # без --unwait только подсказка
    assert program.read_run(proj)["waiting"] is not None


def test_resume_does_not_touch_a_stage_that_is_writing_and_keep_wait_skips(waiting_stage):
    proj = waiting_stage
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(0),
              waiting={"kind": "action", "since": stamp(-5), "note": "х"})
    assert "писал в state.js" in program.cmd_resume(proj)
    assert program.read_run(proj)["waiting"] is not None
    assert "снято" in program.cmd_stage_unwait(proj, "M1", force=True)
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-90 * 24),
              waiting={"kind": "action", "since": stamp(-5), "note": "х"})
    program.cmd_pause(proj, None, None, reason="owner")
    assert "ожидание" not in program.cmd_resume(proj, keep_wait=True)
    assert program.read_run(proj)["waiting"] is not None


def test_owner_task_done_with_unwait_clears_stale_flag(waiting_stage):
    proj = waiting_stage
    program.cmd_owner_task(proj, "add", "Strata работает на :18090, остановить?", "M1")
    out = program.cmd_owner_task(proj, "done", "T1", None, unwait=True)
    assert "ожидание action этапа M1 снято" in out
    assert program.read_run(proj)["waiting"] is None


def test_track_marks_a_wait_nothing_in_the_program_explains(waiting_stage):
    proj = waiting_stage
    assert "флаг мог устареть: `why-paused`" in program.cmd_track(proj)
    program.cmd_owner_task(proj, "add", "что-то", None)
    assert "ждёт тебя (action)" in program.cmd_track(proj) and "why-paused" not in program.cmd_track(proj)


def test_unwait_refuses_an_idle_stage_and_repairs_a_stale_status(proj):
    with pytest.raises(program.ProgramError, match="не идёт"):
        program.cmd_stage_unwait(proj, "M1")
    program.cmd_start(proj, "M1", adopt=False)
    assert "нет ожидания" in program.cmd_stage_unwait(proj, "M1")
    data = program.load(proj)
    data["stages"][0]["status"] = "waiting"
    program.save(proj, data)
    assert "waiting → running" in program.cmd_stage_unwait(proj, "M1")


def test_why_paused_lists_every_reason_with_a_remedy(waiting_stage):
    proj = waiting_stage
    program.cmd_pause(proj, None, None, reason="owner", text="стоп")
    program.cmd_ask(proj, "Q01", "формат?", "json", "M1")
    program.cmd_owner_task(proj, "add", "ждём", "M1", kind="pause")
    program.cmd_owner_task(proj, "add", "Strata на :18090", "M1")
    text = program.cmd_why_paused(proj)
    for needle in ("Пауза программы (owner)", "снять: `program.py resume`", "Вопрос владельцу Q01", "program.py answer Q01",
                   "Задача владельца T1 [ожидание паузы]", "Задача владельца T2", "owner-task done T2",
                   "Этап M1 ждёт владельца в state.js (action", "stage unwait M1", program.wake_task_id(proj)):
        assert needle in text, needle
    program.cmd_resume(proj)
    assert "Вопрос владельцу Q01" in program.cmd_why_paused(proj)  # вопрос resume сам не отвечает


def test_why_paused_flags_a_limit_pause_whose_time_has_passed(proj):
    program.cmd_pause(proj, stamp(-5), "5-hour limit")
    assert "срок вышел, но не снята" in program.cmd_why_paused(proj)


def test_cli_pause_reason_resume_and_why_paused(proj, capsys):
    root = ["--project", str(proj)]
    assert program.main(root + ["pause", "--reason", "owner", "--text", "стоп до утра"]) == 0
    assert "по слову владельца" in capsys.readouterr().out
    assert program.main(root + ["why-paused"]) == 0 and "Пауза программы (owner)" in capsys.readouterr().out
    assert program.main(root + ["owner-task", "add", "ждём", "--kind", "pause"]) == 0
    capsys.readouterr()
    assert program.main(root + ["resume"]) == 0 and "закрыты задачи" in capsys.readouterr().out
    assert program.main(root + ["pause"]) == 2  # лимит без --until


def test_stage_rules_tell_the_stage_to_clear_its_own_wait():
    assert "ap.py answered" in program.STAGE_RULES and "--note" in program.STAGE_RULES
    assert "ap.py answered" in program.CODEX_RULES


REAL_AP = Path.home() / ".claude" / "skills" / "autopilot" / "tools" / "ap.py"


@pytest.mark.skipif(not REAL_AP.is_file(), reason="Autopilot не установлен")
def test_unwait_with_the_real_ap_py(proj):
    import shutil
    import subprocess
    import sys
    shutil.copy2(REAL_AP, proj / ".autopilot" / "ap.py")
    program.cmd_start(proj, "M1", adopt=False)
    ap = [sys.executable, str(proj / ".autopilot" / "ap.py")]
    subprocess.run([*ap, "init", "--slug", "demo", "--title", "Demo", "--no-serve"], cwd=proj, check=True, capture_output=True)
    subprocess.run([*ap, "ask", "action", "--note", "ждём", "--no-serve"], cwd=proj, check=True, capture_output=True)
    run = program.read_run(proj)
    assert run["waiting"]["kind"] == "action"
    run["updatedAt"] = stamp(-60)  # этап давно не пишет
    (proj / ".autopilot" / "state.js").write_text("window.STATE =\n" + json.dumps(run, ensure_ascii=False), encoding="utf-8")
    assert "снято" in program.cmd_stage_unwait(proj, "M1")
    after = program.read_run(proj)
    assert after["waiting"] is None and after["waits"][-1]["kind"] == "action"


def test_docs_stage_check_runs_gate_with_allow_no_tests(proj, monkeypatch):
    # T21.1: документный прогон (deliverable docs) — гейт с --allow-no-tests; кодовый — строгий (D14 как в хуке)
    calls = []
    monkeypatch.setattr(program, "run_gate",
                        lambda root, allow_no_tests=False: (calls.append(allow_no_tests), (True, "ГЕЙТ ПРОЙДЕН"))[1])
    program.cmd_start(proj, "M1", adopt=False)
    finished_run(proj, deliverable="docs")
    program.cmd_check(proj, None, record=False, with_gate=True)
    assert calls == [True]
    finished_run(proj, deliverable="code")
    program.cmd_check(proj, None, record=False, with_gate=True)
    assert calls == [True, False]
    # deliverable этапа из плана тоже считается, даже если прогон его не записал
    data = program.load(proj)
    program.stage_of(data, "M1")["deliverable"] = "docs"
    (proj / ".autopilot" / "program.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    finished_run(proj)
    program.cmd_check(proj, None, record=False, with_gate=True)
    assert calls == [True, False, True]


def test_stage_requeue_remembers_previous_session_and_warns(proj):
    # T21.3: живой инцидент пилота — прежняя сессия этапа пережила перезапуск и ломала сдачу
    program.cmd_start(proj, "M1", adopt=False)
    assert "ПРЕДУПРЕЖДЕНИЕ" not in program.cmd_bind(proj, "M1", "local_old")
    out = program.cmd_stage_set(proj, "M1", "pending", "доверие к папке не выдано")
    assert "local_old" in out and "stop_session" in out and "prev-done" in out
    prev = program.load(proj)["stages"][0]["previousSessions"]
    assert prev[0]["sessionId"] == "local_old" and prev[0]["closed"] is None
    program.cmd_start(proj, "M1", adopt=False)
    out = program.cmd_bind(proj, "M1", "local_new")
    assert "local_old" in out and "prev-done" in out  # bind новой сессии предупреждает о непогашенной
    finished_run(proj)
    verdict = program.cmd_check(proj, None, record=False, with_gate=False)
    assert any("local_old" in w and "prev-done" in w for w in verdict["warnings"])
    note = program.watch_program(proj, {})["note"]
    assert "прежняя сессия не погашена" in note and "local_old" in note
    assert "закрыты" in program.cmd_stage_prev_done(proj, "M1", None)
    assert "ПРЕДУПРЕЖДЕНИЕ" not in program.cmd_bind(proj, "M1", "local_new")
    assert not any("local_old" in w for w in program.cmd_check(proj, None, record=False, with_gate=False)["warnings"])
    assert "прежняя сессия" not in program.watch_program(proj, {})["note"]


def test_reserve_empty_flag_and_dashboard_alert(proj):
    # T21.5: пустой резерв виден заранее — в program.js, в пульте и в track, а не в момент перехода
    program.cmd_start(proj, "M1", adopt=False)
    data = program.load(proj)
    assert program.reserve_empty(data)
    js = (proj / ".autopilot" / "program.js").read_text(encoding="utf-8")
    assert '"reserveEmpty": true' in js
    from kit import dashboard
    stage = program.active_stage(data)
    alerts = dashboard._program_alerts({"name": "proj", "registered": True}, data, stage, None)
    assert any("Резерв чатов пуст" in a["what"] for a in alerts)
    program.cmd_pool(proj, "add", "local_r1")
    data = program.load(proj)
    assert not program.reserve_empty(data)
    assert '"reserveEmpty": false' in (proj / ".autopilot" / "program.js").read_text(encoding="utf-8")
    alerts = dashboard._program_alerts({"name": "proj", "registered": True}, data,
                                       program.active_stage(data), None)
    assert not any("Резерв" in a["what"] for a in alerts)
    assert "резерв пуст" not in program.cmd_track(proj)


def test_reserve_not_empty_while_delivered_chat_is_recyclable(proj):
    deliver_m1(proj)
    program.cmd_bind(proj, "M1", "local_m1")
    assert not program.reserve_empty(program.load(proj))  # чат сданного этапа ещё можно очистить (D40)
    assert "резерв пуст" not in program.cmd_track(proj)


def test_register_program_refuses_to_erase_broken_registry(tmp_path, monkeypatch, capsys):
    # T21.6: битый реестр больше не перезаписывается одной новой записью и не теряется
    home = tmp_path / "reg-home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    reg = home / ".autopilot-kit" / "programs.json"
    reg.parent.mkdir(parents=True)
    reg.write_text("{oops", encoding="utf-8")
    with pytest.raises(program.ProgramError, match="не читается"):
        program.register_program(tmp_path / "proj", "цель")
    assert reg.read_text(encoding="utf-8") == "{oops"  # файл не тронут
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.delenv("AUTOPILOT_KIT_NO_SERVE", raising=False)  # init регистрирует программу вне тестового режима
    assert program.main(["--project", str(fresh), "init", "--goal", "x"]) != 0  # CLI: ненулевой выход
    assert reg.read_text(encoding="utf-8") == "{oops"
    err = capsys.readouterr().err
    assert "создана, но НЕ зарегистрирована" in err  # program.json создан до регистрации — владелец должен знать
    assert (fresh / ".autopilot" / "program.json").exists()


def test_register_program_writes_registry_with_backup(tmp_path, monkeypatch):
    home = tmp_path / "reg-home2"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    reg = home / ".autopilot-kit" / "programs.json"
    program.register_program(tmp_path / "p1", "a")
    assert reg.exists() and not list(reg.parent.glob("programs.json.bak-*"))  # новый файл — без бэкапа
    program.register_program(tmp_path / "p1", "a")
    assert not list(reg.parent.glob("programs.json.bak-*"))  # дубль — без записи
    program.register_program(tmp_path / "p2", "b")
    backups = list(reg.parent.glob("programs.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["programs"][-1]["root"].endswith("p1")
    assert [p["root"] for p in json.loads(reg.read_text(encoding="utf-8"))["programs"]] == \
        [os.path.abspath(tmp_path / "p1"), os.path.abspath(tmp_path / "p2")]


def test_owner_task_done_accepts_note(proj):
    # T21.7: закрытие задачи с пояснением — как у leftovers --done --note
    program.cmd_owner_task(proj, "add", "выдать доступ к серверу", "M1")
    out = program.cmd_owner_task(proj, "done", "T1", None, note="владелец выдал доступ в чате")
    assert "выполнена" in out and "владелец выдал доступ в чате" in out
    task = program.load(proj)["ownerTasks"][0]
    assert task["done"] and task["note"] == "владелец выдал доступ в чате"
    report = program.cmd_report(proj)
    assert "## Закрытые задачи владельца" in report and "выдать доступ к серверу — владелец выдал доступ в чате" in report
    # без --note поведение прежнее
    program.cmd_owner_task(proj, "add", "вторая", None)
    program.cmd_owner_task(proj, "done", "T2", None)
    assert "note" not in program.load(proj)["ownerTasks"][1]


# ── Волна 21: T21.4б (permissions.allow) и T21.9 (квота гейтвея) ────────────

def test_approve_add_permission_writes_exact_tool_rule(proj, home):
    # T21.4б (решение владельца: вариант а): только явный флаг, только точное имя MCP-инструмента, слияние + .bak
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"permissions": None}), encoding="utf-8")  # прод-кейс: permissions null
    out = program.cmd_approve(proj, "add", "очистка чата этапа", [], None,
                              permission="mcp__ccd_session_mgmt__clear_session")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["mcp__ccd_session_mgmt__clear_session"]
    assert "permissions.allow += mcp__ccd_session_mgmt__clear_session" in out and str(settings) in out
    assert list(settings.parent.glob("settings.json.bak-*"))  # копия прежнего
    assert program.load(proj)["approvals"][0]["permission"] == "mcp__ccd_session_mgmt__clear_session"
    program.cmd_approve(proj, "add", "очистка чата этапа", [], None, permission="mcp__ccd_session_mgmt__clear_session")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"].count("mcp__ccd_session_mgmt__clear_session") == 1  # повтор без дубля


def test_approve_permission_refuses_broad_rules(proj, home):
    for bad in ("mcp__ccd_*", "Bash(*)", "Bash", "clear_session", "mcp__onlyserver", "mcp__server__tool with space"):
        with pytest.raises(program.ProgramError, match="--permission"):
            program.cmd_approve(proj, "add", "x", [], None, permission=bad)
    settings = home / ".claude" / "settings.json"
    assert not settings.exists()  # отказ до всякой записи


def test_approve_without_permission_leaves_allow_untouched(proj, home):
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git status *)"]}}), encoding="utf-8")
    program.cmd_approve(proj, "add", "скачать установщик", [], None)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["Bash(git status *)"]  # автоматически nothing не появляется
    assert "autoMode" in data  # прежнее поведение — текст в autoMode


def test_program_skill_hands_permission_rule_to_the_owner():
    # T21.14: оркестратор не запускает approve add --permission сам — команду выполняет владелец (Self-Modification)
    from kit import commands
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**A durable tool permission (T21.4b, T21.14).**", "**Never run this command yourself**",
                   "wait until they say it is done", "count the rule as active\nonly when".replace("\n", " "),
                   "refused as too broad"):
        assert phrase in text, phrase


QUOTA_TEXT = ("API Error: Request rejected (429) · Your token-plan 1-month quota has been exhausted. "
              "The quota will reset at 12-07 16:00:00 UTC.")


def test_parse_quota_reset():
    moment = program.parse_quota_reset(QUOTA_TEXT)
    assert moment and (moment.month, moment.day, moment.hour, moment.minute) == (12, 7, 16, 0)
    assert moment.tzinfo == timezone.utc and moment > datetime.now(timezone.utc)
    assert program.parse_quota_reset("обычный сбой без дат") is None
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%m-%d %H:%M:%S UTC")
    rolled = program.parse_quota_reset(f"quota will reset at {yesterday}")
    assert rolled and rolled > datetime.now(timezone.utc)  # года в тексте нет — ближайший будущий


def test_quota_pause_sets_limit_pause_until_reset(proj):
    out = program.cmd_quota_pause(proj, QUOTA_TEXT, orchestrator="local_orch")
    pause = program.load(proj)["pause"]
    assert pause["reason"] == "limit" and pause["window"] == program.GATEWAY_WINDOW
    expected = (program.parse_quota_reset(QUOTA_TEXT) + timedelta(minutes=program.RESUME_DELAY_MIN)).astimezone()
    assert pause["until"] == expected.isoformat(timespec="seconds")
    assert pause["orchestrator"] == "local_orch"
    assert "Идущего этапа с сессией нет" in out  # M1 не начат — задача продолжения не нужна
    assert "сменить тариф" in out  # сброс может быть за месяц — уведомление с вариантами обязательно
    program.cmd_resume(proj)
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    program.cmd_job(proj, "set", "ночной прогон", "python -c 0", stamp(180))
    out = program.cmd_quota_pause(proj, QUOTA_TEXT)
    assert program.wake_task_id(proj) in out and "wake-prompt" in out
    assert "Не повторяй запросы" in out
    # остановка по квоте рвёт фоновых исполнителей — долгие работы помечены для перепроверки
    jobs = program.load(proj)["jobs"]
    assert jobs[0]["quotaSuspect"] and "«ночной прогон»" in out and "перепроверки" in out
    assert "quotaSuspect" in program.cmd_job(proj, "list", None, None, None)


def test_quota_pause_refuses_unknown_text(proj):
    with pytest.raises(program.ProgramError, match="время сброса"):
        program.cmd_quota_pause(proj, "API Error: Request rejected (429) · quota exhausted, когда сбросят — неизвестно")
    with pytest.raises(program.ProgramError, match="не похож на отказ квоты"):
        program.cmd_quota_pause(proj, "connection reset at 12-07 16:00:00 UTC")
    assert program.load(proj).get("pause") is None


def test_quota_pause_cli(proj, capsys):
    assert program.main(["--project", str(proj), "quota-pause", "--text", QUOTA_TEXT]) == 0
    assert program.load(proj)["pause"]["reason"] == "limit"


def test_program_skill_pauses_on_gateway_quota():
    from kit import commands
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Gateway quota (T21.9).**", "`program.py quota-pause --text '<the refusal",
                   "**Never retry the refused request**", "«Gateway quota» (`quota-pause`, T21.9)",
                   "The quota is **monthly**", "quotaSuspect", "never trust a stage's «works in the background» word for it"):
        assert phrase in text, phrase


def test_stage_rules_forbid_ending_turn_with_live_background_agent():
    # T21.10: фоновые субагенты приложения умирают на границе хода (пилот S1/S2)
    rules = program.STAGE_RULES
    assert "Background agent" in rules and "didn't finish before the previous session ended" in rules
    assert "не заканчивай " in rules or "не заканчивай\n" in rules or "**не заканчивай " in rules
    assert "Заявил фоновую работу и закончил ход" in rules
    assert "работа НЕ считается сделанной" in rules


def test_program_skill_verifies_background_claims_by_events_and_tree():
    from kit import commands
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("it **claims a background executor is working**", "verify, do not take its word (T21.10)",
                   "didn't finish before the previous session ended", "the tree facts — fresh commits/files, the test count, the gate",
                   "**one** ping to the stage naming what has already landed in the tree",
                   "STAGE_RULES forbids ending a turn with a live background executor"):
        assert phrase in text, phrase


def test_approve_permission_accepts_real_tool_names_with_hyphen(proj, home):
    # T21.13 (дефект с боевого запуска 08.11): сервер scheduled-tasks с дефисом — легитимное точное имя
    settings = home / ".claude" / "settings.json"
    out = program.cmd_approve(proj, "add", "задача продолжения", [], None,
                              permission="mcp__scheduled-tasks__create_scheduled_task")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["mcp__scheduled-tasks__create_scheduled_task"]
    assert "permissions.allow +=" in out
    program.cmd_approve(proj, "add", "дашборд", [], None, permission="mcp__Claude_Browser__preview_start")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "mcp__Claude_Browser__preview_start" in data["permissions"]["allow"]


def test_approve_permission_still_refuses_templates(proj, home, capsys):
    settings = home / ".claude" / "settings.json"
    for bad in ("mcp__scheduled-tasks__*", "mcp__ccd_*", "mcp__ccd_session_mgmt__clear*", "Bash(*)", "Bash",
                "clear_session", "mcp__-bad__tool", "mcp__server__tool-", "mcp__server__tool with space"):
        with pytest.raises(program.ProgramError, match="mcp__<сервер>__<инструмент>"):
            program.cmd_approve(proj, "add", "x", [], None, permission=bad)
    assert not settings.exists()  # отказ до всякой записи
    assert program.main(["--project", str(proj), "approve", "add", "x", "--permission", "mcp__scheduled-tasks__*"]) == 2
    assert not settings.exists()
    assert "mcp__scheduled-tasks__create_scheduled_task" in capsys.readouterr().err  # отказ подсказывает верный формат


def test_page_launch_frees_the_port_for_the_panel(proj, monkeypatch):
    # T21.15: панель не стартует на занятом порту — page --launch останавливает только свой фоновый сервер
    # T21.15a: и только проверив личность процесса (образ python + командная строка сервера kit)
    import subprocess as subprocess_module
    (proj / ".autopilot").mkdir(exist_ok=True)
    (proj / ".autopilot" / "program-serve.pid").write_text("4321", encoding="utf-8")
    port = program.page_port(proj)
    monkeypatch.setattr(program, "server_state", lambda p: "ours")
    monkeypatch.setattr(program, "pid_alive", lambda pid: True)
    ran = []

    def fake_run(args, *a, **k):
        ran.append(args)
        name = str(args[0]).lower()
        if name.endswith("tasklist"):
            return subprocess_module.CompletedProcess(args, 0, stdout='"python.exe","4321","Console","1","10 000 K"\n', stderr="")
        if "powershell" in name:
            return subprocess_module.CompletedProcess(
                args, 0, stdout=f"import sys; ...serve_forever() {port} {proj / '.autopilot'}\n", stderr="")
        return subprocess_module.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(program.subprocess, "run", fake_run)
    lines = program.cmd_page(proj, launch=True)
    assert any("освобождён" in line for line in lines) and any("preview_start" in line for line in lines)
    killed = [c for c in ran if str(c[0]).lower().endswith("taskkill")]
    assert killed and "4321" in killed[0]  # taskkill по pid своего фонового сервера
    assert not (proj / ".autopilot" / "program-serve.pid").exists()  # pid-файл убран
    # pid мёртв (порт держит панель или файл устарел) — никого не убиваем
    (proj / ".autopilot" / "program-serve.pid").write_text("4321", encoding="utf-8")
    monkeypatch.setattr(program, "pid_alive", lambda pid: False)
    ran.clear()
    lines = program.cmd_page(proj, launch=True)
    assert not ran and not any("освобождён" in line for line in lines)
    # без --launch порт не трогается
    monkeypatch.setattr(program, "pid_alive", lambda pid: True)
    ran.clear()
    program.cmd_page(proj, launch=False)
    assert not ran


def test_release_port_refuses_to_kill_a_foreign_process(proj, monkeypatch):
    # T21.15a: pid переиспользован системой — образ не python: не убивать, pid-файл на месте, предупреждение
    import subprocess as subprocess_module
    (proj / ".autopilot").mkdir(exist_ok=True)
    pid_file = proj / ".autopilot" / "program-serve.pid"
    pid_file.write_text("4321", encoding="utf-8")
    monkeypatch.setattr(program, "server_state", lambda p: "ours")
    monkeypatch.setattr(program, "pid_alive", lambda pid: True)
    ran = []

    def make_run(image: str, cmdline: str):
        def fake_run(args, *a, **k):
            ran.append(args)
            name = str(args[0]).lower()
            if name.endswith("tasklist"):
                return subprocess_module.CompletedProcess(args, 0, stdout=f'"{image}","4321","Console","1","1 K"\n', stderr="")
            if "powershell" in name:
                return subprocess_module.CompletedProcess(args, 0, stdout=cmdline + "\n", stderr="")
            return subprocess_module.CompletedProcess(args, 0, stdout="", stderr="")
        return fake_run

    # образ не python (переиспользованный pid постороннего процесса)
    monkeypatch.setattr(program.subprocess, "run", make_run("notepad.exe", ""))
    lines = program.cmd_page(proj, launch=True)
    assert not any(str(c[0]).lower().endswith("taskkill") for c in ran)
    assert pid_file.exists() and any("не похож" in line for line in lines)
    # образ python, но командная строка чужая (например, сервер панели serve --foreground или чужой скрипт)
    ran.clear()
    monkeypatch.setattr(program.subprocess, "run", make_run("python.exe", "C:/x/program.py --project . serve --foreground"))
    lines = program.cmd_page(proj, launch=True)
    assert not any(str(c[0]).lower().endswith("taskkill") for c in ran)
    assert pid_file.exists() and any("не похож" in line for line in lines)
    # tasklist не нашёл процесс — тоже не убиваем
    ran.clear()

    def empty_tasklist(args, *a, **k):
        ran.append(args)
        return subprocess_module.CompletedProcess(args, 0, stdout="INFO: No tasks are running which match the specified criteria.\n", stderr="")

    monkeypatch.setattr(program.subprocess, "run", empty_tasklist)
    lines = program.cmd_page(proj, launch=True)
    assert not any(str(c[0]).lower().endswith("taskkill") for c in ran) and pid_file.exists()
    assert any("не похож" in line for line in lines)


def test_cmdline_is_kit_server_matches_only_background_server():
    port = 8826
    assert program._cmdline_is_kit_server(f"python -c import...serve_forever() {port} D:/p/.autopilot", port)
    assert not program._cmdline_is_kit_server("python C:/x/program.py --project . serve --foreground", port)  # панель — не трогать
    assert not program._cmdline_is_kit_server("python my_script.py", port)
    assert program._cmdline_is_kit_server(f"python -m http.server {port} --directory D:/p/.autopilot", port)


def test_serve_foreground_never_binds_while_the_kit_server_holds_the_port(proj, monkeypatch):
    # T21.15: ветка «конфигурация kit + уже работающий фоновый сервер» — ждём, ошибки «Port … in use» не будет
    import http.server
    import socket
    import time as time_module
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(program, "page_port", lambda root: port)
    monkeypatch.setattr(program, "server_state", lambda p: "ours")  # порт навсегда держит сервер kit
    calls = {"n": 0}

    def counting_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(time_module, "sleep", counting_sleep)
    bound = []

    class StubServer(http.server.ThreadingHTTPServer):
        def __init__(self, address, *args, **kwargs):
            bound.append(address)
            raise OSError("не должны дойти до bind, пока порт «ours»")

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", StubServer)
    with pytest.raises(KeyboardInterrupt):
        program.cmd_serve_foreground(proj)
    assert bound == [] and calls["n"] == 3


def test_watch_gap_restart_detects_closed_app(home):
    # T21.16: задача сторожа ходит каждые 15 мин; разрыв с watch_last ≥ 30 мин ⇒ приложение было закрыто/спало
    path = program.watch_last_path()
    assert program.watch_gap_restart() is None  # первый проход — не перезапуск (иначе будил бы всё подряд)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stamp(-20), encoding="utf-8")
    assert program.watch_gap_restart() is None  # обычный ритм
    path.write_text(stamp(-45), encoding="utf-8")
    moment = program.watch_gap_restart()
    assert moment is not None and moment < datetime.now(timezone.utc)
    path.write_text("мусор", encoding="utf-8")
    assert program.watch_gap_restart() is None  # нечитаемая метка — не перезапуск


def test_watch_wakes_at_once_after_app_restart(proj, monkeypatch):
    monkeypatch.setattr(program, "boot_time", lambda: datetime(2000, 1, 1, tzinfo=timezone.utc))  # ОС не перезагружалась
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-50))
    restart = datetime.fromisoformat(stamp(-20))  # прошлый проход сторожа был 20 мин назад, приложение стояло
    result = program.watch_program(proj, {}, app_restart=restart)
    assert result["action"] == "wake_stage" and "(с перезапуска приложения)" in result["note"]
    assert "перезапуск приложения" in result["message"]  # INTERRUPTED перечисляет обе причины
    # без признака перезапуска 50 мин < 60 — прежний порог, этап работает
    assert program.watch_program(proj, {})["action"] == "none"
    # прогон моложе прошлого прохода — перезапуск его не прерывал
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-5))
    assert program.watch_program(proj, {}, app_restart=restart)["action"] == "none"


def test_machine_reboot_wins_over_app_restart(proj, monkeypatch):
    monkeypatch.setattr(program, "boot_time", lambda: datetime.now(timezone.utc) - timedelta(minutes=10))
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-50))
    result = program.watch_program(proj, {}, app_restart=datetime.fromisoformat(stamp(-45)))
    assert result["action"] == "wake_stage" and "(с перезагрузки)" in result["note"]


def test_cmd_watch_takes_restart_from_watch_last(proj, home, monkeypatch):
    monkeypatch.setattr(program, "boot_time", lambda: datetime(2000, 1, 1, tzinfo=timezone.utc))
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-50))
    program.register_program(proj, "демо")
    path = program.watch_last_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stamp(-45), encoding="utf-8")  # разрыв 45 мин — приложение было закрыто
    results = program.cmd_watch()
    item = [r for r in results if r["root"].endswith("proj")][0]
    assert item["action"] == "wake_stage" and "(с перезапуска приложения)" in item["note"]
    assert program.watch_gap_restart() is None  # проход обновил watch_last — следующий запуск без признака


def test_watch_prompt_states_exact_wake_thresholds():
    # T21.16: текст задачи сторожа называет точные пороги побудки, а не «после перезапуска»
    text = program.watch_prompt()
    assert "после перезагрузки машины — сразу" in text
    assert "≥ 30 мин" in text and "60 мин" in text and "15 мин между этапами" in text


def test_watch_rewakes_a_stage_whose_session_died_after_the_first_wake(proj):
    # D52 (DeerFlow D2, 11.11): первое пробуждение пришло, пока этап работал; в 20:11 процесс чата упал (код 3221226505),
    # а сторож «ждал» — программа стояла часами. Теперь пробуждение повторяется, пока прогон не сдвинулся
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    write_run(proj, stages=[{"id": "build", "status": "active"}], updatedAt=stamp(-90))
    assert watched(proj)["action"] == "wake_stage"
    assert watched(proj)["action"] == "none"  # сразу после пробуждения — ждём
    memory_path = program.kit_home() / ".autopilot-kit" / "watch.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    key = str(proj.resolve())
    memory[key]["at"] = stamp(-(program.WATCH_REWAKE_MIN + 5))
    memory_path.write_text(json.dumps(memory), encoding="utf-8")
    again = watched(proj)
    assert again["action"] == "wake_stage" and again["sessionId"] == "local_stage" and "повторное" in again["note"]
    assert "процесс чата упал" in again["message"]
    assert watched(proj)["action"] == "none"  # и повтор не чаще раза в WATCH_REWAKE_MIN
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    memory[key]["wokeAt"] = stamp(-(program.WATCH_REWAKE_MIN + 5))
    memory[key]["at"] = stamp(-(program.WATCH_ESCALATE_MIN + 5))
    memory_path.write_text(json.dumps(memory), encoding="utf-8")
    assert watched(proj)["action"] == "notify_owner"  # владелец по-прежнему узнаёт через час тишины


def test_pool_target_grows_with_pending_stages_and_release_returns_a_chat(proj):
    # D57: резерв из двух сессий кончался через два этапа (боевой проект, 12.11): пополнить можно только в ходе владельца
    data = program.load(proj)
    pending = sum(1 for s in data["stages"] if s["status"] == "pending")
    assert program.pool_target(data) == min(program.POOL_CAP, max(program.POOL_SIZE, pending))
    for number in range(8):
        data["stages"].append({**data["stages"][0], "id": f"X{number}", "status": "pending", "sessionId": None})
    program.save(proj, data)
    assert program.pool_target(program.load(proj)) == program.POOL_CAP
    assert program.cmd_pool(proj, "need", None) == str(program.POOL_CAP)
    program.cmd_pool(proj, "add", "local_r1")
    assert program.cmd_pool(proj, "need", None) == str(program.POOL_CAP - 1)
    # очистку отказали временно: отметка «использован» снимается, чат снова годится к следующему этапу
    deliver_m1(proj)
    program.cmd_bind(proj, "M1", "local_m1")
    taken = json.loads(program.cmd_pool(proj, "take", None, as_json=True))
    assert taken == {"sessionId": "local_m1", "clear": True, "from": "этап M1"}
    assert [s["id"] for s in program.recyclable(program.load(proj))] == []
    assert "снова доступен" in program.cmd_pool(proj, "release", "local_m1")
    assert json.loads(program.cmd_pool(proj, "take", None, as_json=True))["sessionId"] == "local_m1"
    assert "не было" in program.cmd_pool(proj, "release", "local_none")
    with pytest.raises(program.ProgramError):
        program.cmd_pool(proj, "release", None)
