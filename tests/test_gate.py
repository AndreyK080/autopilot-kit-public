import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kit import gate

GATE_SCRIPT = Path(gate.__file__)


def py(code: str, tmp_path: Path, name: str = "s.py") -> str:
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{script}"'


def configure(project: Path, commands: list[str], timeout: int = 60) -> None:
    folder = project / ".autopilot-kit"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.toml").write_text(
        f"[gate]\ncommands = {json.dumps(commands)}\ntimeout_seconds = {timeout}\n", encoding="utf-8"
    )


def test_not_configured_passes(tmp_path):
    ok, report = gate.run_gate(tmp_path)
    assert ok and "гейт не настроен" in report
    assert gate.main(["--project", str(tmp_path)]) == 0


def test_passing_and_failing_commands(tmp_path):
    configure(tmp_path, [py("print('fine')", tmp_path)])
    ok, report = gate.run_gate(tmp_path)
    assert ok and "fine" in report and "ГЕЙТ ПРОЙДЕН" in report

    configure(tmp_path, [py("print('boom'); raise SystemExit(1)", tmp_path, "bad.py"), py("print('never')", tmp_path)])
    ok, report = gate.run_gate(tmp_path)
    assert not ok and "boom" in report and "never" not in report and "ГЕЙТ НЕ ПРОЙДЕН" in report
    assert gate.main(["--project", str(tmp_path)]) == 1


def test_output_tail_is_limited(tmp_path):
    configure(tmp_path, [py("print('x' * 20000 + 'END')", tmp_path)])
    code, tail = gate.run_command(gate.load_config(tmp_path)["commands"][0], tmp_path, 60)
    assert code == 0 and len(tail) <= gate.TAIL_CHARS and tail.rstrip().endswith("END")


def test_timeout(tmp_path):
    configure(tmp_path, [py("import time; time.sleep(30)", tmp_path)], timeout=1)
    started = time.monotonic()
    ok, report = gate.run_gate(tmp_path)
    assert not ok and "таймаут" in report
    assert time.monotonic() - started < 20


def test_bad_config_is_error(tmp_path):
    folder = tmp_path / ".autopilot-kit"
    folder.mkdir()
    (folder / "project.toml").write_text("[gate\n", encoding="utf-8")
    assert gate.main(["--project", str(tmp_path)]) == 1


def test_hook_loop_protection(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    # первая остановка: блокируем
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 2
    # Claude продолжил и снова остановился с провалом: пропускаем, чтобы не зациклиться
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": True}) == 0
    assert "ГЕЙТ НЕ ПРОЙДЕН" in capsys.readouterr().out
    # счётчик сброшен: новый ход снова блокируется
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 2


def test_hook_success_resets_counter(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    gate.hook_claude_stop(tmp_path, {"stop_hook_active": False})
    configure(tmp_path, [py("print('ok')", tmp_path, "ok.py")])
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": True}) == 0
    assert json.loads(gate.state_path(tmp_path).read_text(encoding="utf-8"))["consecutive_failures"] == 0


def test_hook_as_script_reads_stdin(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = json.dumps({"cwd": str(tmp_path), "stop_hook_active": False})
    # без PYTHONIOENCODING: так хук запускает Claude Code, вывод всё равно должен быть UTF-8
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--hook", "claude-stop"],
        input=event.encode("utf-8"), capture_output=True, env=env,
    )
    assert result.returncode == 2
    assert "ГЕЙТ НЕ ПРОЙДЕН" in result.stderr.decode("utf-8")


def write_autopilot_state(project: Path, waiting) -> None:
    folder = project / ".autopilot"
    folder.mkdir(parents=True, exist_ok=True)
    state = {"version": 2, "waiting": waiting}
    (folder / "state.js").write_text("window.STATE =\n" + json.dumps(state, indent=2) + "\n", encoding="utf-8")


def test_hook_allows_stop_while_autopilot_waits(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    write_autopilot_state(tmp_path, {"kind": "briefing", "since": "2026-10-21T20:00:00+03:00", "note": None})
    assert gate.autopilot_waiting(tmp_path) == "briefing"
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 0
    assert "ждёт владельца (briefing)" in capsys.readouterr().err
    assert not gate.state_path(tmp_path).exists()  # тесты не запускались, счётчик не тронут
    # ожидание закончилось — гейт снова блокирует
    write_autopilot_state(tmp_path, None)
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 2


@pytest.mark.parametrize("text", ["", "window.STATE = {broken", "window.STATE = []", '{"waiting": "yes"}'])
def test_unreadable_autopilot_state_means_not_waiting(tmp_path, text):
    (tmp_path / ".autopilot").mkdir()
    (tmp_path / ".autopilot" / "state.js").write_text(text, encoding="utf-8")
    assert gate.autopilot_waiting(tmp_path) is None


def test_no_tests_yet_passes_only_in_hook(tmp_path):
    (tmp_path / "test_nothing.py").write_text("", encoding="utf-8")  # pytest соберёт 0 тестов → код 5
    configure(tmp_path, [f'"{sys.executable}" -m pytest -q -p no:cacheprovider'])
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 0
    ok, report = gate.run_gate(tmp_path)
    assert not ok and "ГЕЙТ НЕ ПРОЙДЕН" in report  # обычный запуск строгий


def test_exit_code_5_of_other_command_is_failure(tmp_path):
    configure(tmp_path, [py("raise SystemExit(5)", tmp_path)])
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 2


@pytest.mark.parametrize("command, expected", [
    ("python -m pytest -q", True),
    ("pytest", True),
    (r'"C:\p\.venv\Scripts\pytest.exe" -q', True),
    (r'.venv\Scripts\python -m pytest -q', True),
    (r'"python" "C:\Temp\pytest-of-user\s.py"', False),
    ("npm test", False),
])
def test_is_pytest(command, expected):
    assert gate.is_pytest(command) is expected


def test_find_project_root_walks_up(tmp_path):
    configure(tmp_path, [py("print('ok')", tmp_path)])
    deep = tmp_path / ".autopilot" / "run--wip" / "tickets"
    deep.mkdir(parents=True)
    assert gate.find_project_root(deep) == tmp_path.resolve()
    assert gate.find_project_root(tmp_path) == tmp_path.resolve()


def test_find_project_root_without_config_returns_start(tmp_path):
    folder = tmp_path / "a" / "b"
    folder.mkdir(parents=True)
    assert gate.find_project_root(folder) == folder.resolve()


def test_hook_from_subfolder_checks_project(tmp_path):
    # T7.2: оболочка Claude стояла в .autopilot\…--wip, и гейт отвечал «гейт не настроен»
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    sub = tmp_path / ".autopilot" / "2026-10-21-demo--wip"
    sub.mkdir(parents=True)
    event = json.dumps({"cwd": str(sub), "stop_hook_active": False})
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--hook", "claude-stop"],
        input=event.encode("utf-8"), capture_output=True,
    )
    assert result.returncode == 2
    assert "ГЕЙТ НЕ ПРОЙДЕН" in result.stderr.decode("utf-8")
    assert gate.state_path(tmp_path).exists() and not gate.state_path(sub).exists()


def test_hook_from_subfolder_sees_autopilot_waiting(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    write_autopilot_state(tmp_path, {"kind": "plan", "since": "x", "note": None})
    sub = tmp_path / "src"
    sub.mkdir()
    event = json.dumps({"cwd": str(sub), "stop_hook_active": False})
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--hook", "claude-stop"],
        input=event.encode("utf-8"), capture_output=True,
    )
    assert result.returncode == 0 and "ждёт владельца (plan)" in result.stderr.decode("utf-8")


def test_plain_run_from_subfolder(tmp_path, monkeypatch):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    sub = tmp_path / "pkg"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert gate.main([]) == 1


def write_transcript(path: Path, first_user: str) -> str:
    rows = [
        {"type": "user", "isMeta": True, "message": {"content": "служебное"}},
        {"type": "user", "message": {"content": first_user}},
        {"type": "assistant", "message": {"content": "ответ"}},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("first_user", [
    "<command-message>autopilot-program</command-message>\n<command-name>/autopilot-program</command-name>",
    '<scheduled-task name="autopilot-program-watchdog" file="x">\nThis is an automated run',
])
def test_hook_skips_orchestrator_and_watchdog_chats(tmp_path, capsys, first_user):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = {"stop_hook_active": False, "transcript_path": write_transcript(tmp_path / "t.jsonl", first_user)}
    assert gate.hook_claude_stop(tmp_path, event) == 0
    assert "оркестратор" in capsys.readouterr().err
    assert not gate.state_path(tmp_path).exists()


@pytest.mark.parametrize("first_user", [
    "Background (from the session that started this one):\nПрограмма прогонов Autopilot",
    "Давай посмотрим, что делает /autopilot-program в этом проекте",
])
def test_hook_still_checks_stage_and_ordinary_chats(tmp_path, first_user):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = {"stop_hook_active": False, "transcript_path": write_transcript(tmp_path / "t.jsonl", first_user)}
    assert gate.hook_claude_stop(tmp_path, event) == 2


@pytest.mark.parametrize("transcript", [None, "нет-такого-файла.jsonl"])
def test_hook_without_readable_transcript_checks(tmp_path, transcript):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = {"stop_hook_active": False}
    if transcript:
        event["transcript_path"] = str(tmp_path / transcript)
    assert gate.hook_claude_stop(tmp_path, event) == 2


def write_codex_transcript(path: Path, first_real: str) -> str:
    def message(text):
        return {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}
    rows = [
        {"type": "session_meta", "payload": {"id": "x"}},
        message("# AGENTS.md instructions for P:/proj\n\n<INSTRUCTIONS>$autopilot-program в тексте правил</INSTRUCTIONS>"),
        message("<environment_context>\n  <cwd>P:/proj</cwd>\n</environment_context>"),
        message(first_real),
        {"type": "event_msg", "payload": {"type": "user_message", "message": first_real}},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return str(path)


def test_codex_hook_skips_orchestrator_chat(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = {"stop_hook_active": False, "transcript_path": write_codex_transcript(tmp_path / "r.jsonl", "$autopilot-program")}
    assert gate.is_program_chat(event)
    assert gate.hook_claude_stop(tmp_path, event) == 0
    assert "оркестратор" in capsys.readouterr().err


@pytest.mark.parametrize("first_real", ["$autopilot-roles", "$autopilot full: M2", "Сделай задачу, не трогая $autopilot-program"])
def test_codex_hook_checks_stage_and_ordinary_chats(tmp_path, first_real):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = {"stop_hook_active": False, "transcript_path": write_codex_transcript(tmp_path / "r.jsonl", first_real)}
    assert not gate.is_program_chat(event)
    assert gate.hook_claude_stop(tmp_path, event) == 2


def test_codex_stop_hook_as_script(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    event = json.dumps({"cwd": str(tmp_path), "stop_hook_active": False, "transcript_path": None})
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--hook", "codex-stop"], input=event.encode("utf-8"), capture_output=True,
    )
    assert result.returncode == 2
    assert "ГЕЙТ НЕ ПРОЙДЕН" in result.stderr.decode("utf-8")


def agy_event(project: Path, **fields) -> dict:
    return {"conversationId": "c1", "workspacePaths": [str(project)], "fullyIdle": True, "terminationReason": "model_stop", **fields}


def agy_answer(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_agy_hook_continues_on_red_gate_and_allows_green(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    assert gate.hook_agy_stop(tmp_path, agy_event(tmp_path)) == 0
    answer = agy_answer(capsys)
    assert answer["decision"] == "continue" and "ГЕЙТ НЕ ПРОЙДЕН" in answer["reason"]
    configure(tmp_path, [py("print('ok')", tmp_path, "ok.py")])
    assert gate.hook_agy_stop(tmp_path, agy_event(tmp_path)) == 0
    assert agy_answer(capsys)["decision"] == "allow"


def test_agy_hook_loop_protection_counts_per_conversation(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    gate.hook_agy_stop(tmp_path, agy_event(tmp_path))
    assert agy_answer(capsys)["decision"] == "continue"
    # другая беседа не наследует чужой счётчик
    gate.hook_agy_stop(tmp_path, agy_event(tmp_path, conversationId="c2"))
    assert agy_answer(capsys)["decision"] == "continue"
    # та же беседа снова провалилась: остановку пропускаем и счётчик сбрасываем
    gate.hook_agy_stop(tmp_path, agy_event(tmp_path, conversationId="c2"))
    answer = agy_answer(capsys)
    assert answer["decision"] == "allow" and "повторный провал" in answer["reason"]
    gate.hook_agy_stop(tmp_path, agy_event(tmp_path, conversationId="c2"))
    assert agy_answer(capsys)["decision"] == "continue"


def test_agy_hook_does_not_block_background_error_or_waiting(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    for fields in ({"fullyIdle": False}, {"terminationReason": "error", "error": "boom"}):
        gate.hook_agy_stop(tmp_path, agy_event(tmp_path, **fields))
        assert agy_answer(capsys)["decision"] == "allow"
    write_autopilot_state(tmp_path, {"kind": "briefing", "since": "2026-10-21T20:00:00+03:00", "note": None})
    gate.hook_agy_stop(tmp_path, agy_event(tmp_path))
    assert agy_answer(capsys)["decision"] == "allow"


def test_agy_stop_hook_as_script_uses_workspace_paths_and_ascii_json(tmp_path):
    project = tmp_path / "proj"
    configure(project, [py("raise SystemExit(1)", tmp_path)])
    event = json.dumps(agy_event(project, workspacePaths=[str(project / "sub")]))
    (project / "sub").mkdir()
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--hook", "agy-stop"], input=event.encode("utf-8"), capture_output=True,
    )
    assert result.returncode == 0
    raw = result.stdout.decode("ascii")  # только ASCII: кодовая страница не влияет
    assert json.loads(raw)["decision"] == "continue"


def test_agy_stop_hook_bad_config_does_not_block(tmp_path):
    folder = tmp_path / ".autopilot-kit"
    folder.mkdir()
    (folder / "project.toml").write_text("[gate\n", encoding="utf-8")
    event = json.dumps(agy_event(tmp_path))
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--hook", "agy-stop"], input=event.encode("utf-8"), capture_output=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout.decode("ascii"))["decision"] == "allow"


ORCHESTRATOR_START = "<command-message>autopilot-program</command-message>\n<command-name>/autopilot-program</command-name>"


def orchestrator_transcript(path: Path, *turns) -> str:
    """Транскрипт чата оркестратора: после /autopilot-program ходы. Ход — (реплика, [вызовы инструментов])."""
    rows = [{"type": "user", "message": {"content": ORCHESTRATOR_START}}]
    for number, (prompt, calls) in enumerate(turns):
        if prompt:
            rows.append({"type": "user", "message": {"content": prompt}})
        for index, (name, args) in enumerate(calls):
            call_id = f"c{number}-{index}"
            rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": args}]}})
            rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": "ok"}]}})
        rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "готово"}]}})
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return str(path)


SHOW_PANE = ("mcp__ccd_view__show_pane", {"pane": "preview"})
BASH = ("Bash", {"command": "program.py track"})


def program_project(tmp_path: Path) -> Path:
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    (tmp_path / ".autopilot").mkdir()
    (tmp_path / ".autopilot" / "program.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_orchestrator_turn_without_show_pane_is_returned_to_work(tmp_path, capsys):
    project = program_project(tmp_path)
    event = {"stop_hook_active": False, "transcript_path": orchestrator_transcript(tmp_path / "t.jsonl", ("продолжай", [BASH]))}
    assert gate.hook_claude_stop(project, event) == 2
    err = capsys.readouterr().err
    assert "show_pane" in err and "preview" in err and "ГЕЙТ" not in err
    assert not gate.state_path(project).exists()  # проверки гейта в этом чате по-прежнему не идут


def test_orchestrator_turn_with_show_pane_may_stop(tmp_path):
    project = program_project(tmp_path)
    event = {"stop_hook_active": False, "transcript_path": orchestrator_transcript(tmp_path / "t.jsonl", ("продолжай", [BASH, SHOW_PANE]))}
    assert gate.hook_claude_stop(project, event) == 0


def test_show_pane_of_an_earlier_turn_does_not_count(tmp_path):
    project = program_project(tmp_path)
    transcript = orchestrator_transcript(tmp_path / "t.jsonl", ("первый ход", [SHOW_PANE]), ("уведомление этапа", [BASH]))
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": transcript}) == 2


def test_other_panes_do_not_count(tmp_path):
    project = program_project(tmp_path)
    other = ("mcp__ccd_view__show_pane", {"pane": "terminal"})
    transcript = orchestrator_transcript(tmp_path / "t.jsonl", ("продолжай", [other]))
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": transcript}) == 2


def test_pane_is_required_once_per_turn_loop_protection(tmp_path):
    project = program_project(tmp_path)
    transcript = orchestrator_transcript(tmp_path / "t.jsonl", ("продолжай", [BASH]))
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": transcript}) == 2
    # модель продолжила, но show_pane не вызвала (приложение отказало или она ошиблась) — второй раз не держим
    assert gate.hook_claude_stop(project, {"stop_hook_active": True, "transcript_path": transcript}) == 0


def test_show_pane_is_not_required_for_other_chats_or_without_program(tmp_path):
    project = program_project(tmp_path)
    watchdog = write_transcript(tmp_path / "w.jsonl", '<scheduled-task name="autopilot-program-watchdog" file="x">\nprompt')
    codex = write_codex_transcript(tmp_path / "c.jsonl", "$autopilot-program")
    stage = write_transcript(tmp_path / "s.jsonl", "Background (from the session that started this one):\nПрограмма")
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": watchdog}) == 0
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": codex}) == 0  # у Codex нет show_pane
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": stage}) == 2  # этап — обычный гейт
    (project / ".autopilot" / "program.json").unlink()  # программы нет (ещё до init) — панели нечего показывать
    orchestrator = orchestrator_transcript(tmp_path / "o.jsonl", ("продолжай", [BASH]))
    assert gate.hook_claude_stop(project, {"stop_hook_active": False, "transcript_path": orchestrator}) == 0


def test_claude_stop_hook_as_script_requires_show_pane(tmp_path):
    project = program_project(tmp_path)
    event = {"cwd": str(project), "stop_hook_active": False,
             "transcript_path": orchestrator_transcript(tmp_path / "t.jsonl", ("продолжай", [BASH]))}
    result = subprocess.run([sys.executable, str(GATE_SCRIPT), "--hook", "claude-stop"],
                            input=json.dumps(event).encode("utf-8"), capture_output=True)
    assert result.returncode == 2 and b"show_pane" in result.stderr


# --- T17.1: защита тестов от подгонки (D41) ---

PYTEST_CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider tests'


def git(project: Path, *args: str) -> str:
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                         cwd=project, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def make_tests_repo(tmp_path: Path, base_in: str = "program") -> Path:
    """Проект в git: два файла тестов, гейт — pytest; база этапа в program.json (или в state.js прогона)."""
    project = tmp_path / "proj"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_math.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n\n\ndef test_mul():\n    assert 2 * 2 == 4\n", encoding="utf-8")
    (project / "tests" / "test_text.py").write_text("def test_upper():\n    assert 'a'.upper() == 'A'\n", encoding="utf-8")
    (project / ".gitignore").write_text(".autopilot-kit/gate_state.json\n__pycache__/\n", encoding="utf-8")
    configure(project, [PYTEST_CMD])
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "base")
    base = git(project, "rev-parse", "HEAD")
    (project / ".autopilot" / "run1").mkdir(parents=True)
    (project / ".autopilot" / "run1" / "spec.md").write_text("# Spec\n", encoding="utf-8")
    if base_in == "program":
        stage = {"id": "S1", "status": "running", "baseCommit": base, "startedAt": "2026-10-26T10:00:00Z", "runDir": "run1"}
        (project / ".autopilot" / "program.json").write_text(json.dumps({"stages": [stage]}), encoding="utf-8")
    else:
        state = {"version": 2, "dir": "run1", "baseCommit": base[:7], "finishedAt": None, "waiting": None}
        (project / ".autopilot" / "state.js").write_text("window.STATE =\n" + json.dumps(state) + "\n", encoding="utf-8")
    return project


def add_decision(project: Path, text: str) -> None:
    with (project / ".autopilot" / "run1" / "spec.md").open("a", encoding="utf-8") as spec:
        spec.write(f"| D01 | {text} |\n")


def test_untouched_tests_pass_with_base_noted(tmp_path):
    project = make_tests_repo(tmp_path)
    ok, report = gate.run_gate(project)
    assert ok and "Тесты сверены с базой: старт этапа S1" in report


def test_deleted_test_file_blocks(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "test_text.py").unlink()
    ok, report = gate.run_gate(project)
    assert not ok and "удалён файл тестов: tests/test_text.py" in report and "тестов стало меньше: 3 → 2" in report
    assert gate.main(["--project", str(project)]) == 1


def test_deleted_test_named_in_decision_passes(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "test_text.py").unlink()
    add_decision(project, "test_text.py удалён: проверка перенесена в test_math.py")
    ok, report = gate.run_gate(project)
    assert ok, report


def test_new_skip_blocks_without_decision_and_passes_with_it(tmp_path):
    project = make_tests_repo(tmp_path)
    path = project / "tests" / "test_math.py"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "def test_mul", "import pytest\n\n\n@pytest.mark.skip(reason='later')\ndef test_mul"), encoding="utf-8")
    ok, report = gate.run_gate(project)
    assert not ok and "новый пропуск теста: tests/test_math.py:" in report and "mark.skip" in report
    add_decision(project, "test_mul пропущен до исправления округления")
    ok, report = gate.run_gate(project)
    assert ok, report


def test_skip_of_new_test_passes(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "test_new.py").write_text(
        "import pytest\n\n\n@pytest.mark.skipif(True, reason='no model')\ndef test_model():\n    pass\n", encoding="utf-8")
    path = project / "tests" / "test_math.py"
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n\ndef test_slow():\n    import pytest\n    pytest.skip('slow')\n", encoding="utf-8")
    ok, report = gate.run_gate(project)
    assert ok, report


def test_focus_only_blocks_even_in_new_test(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "web.test.js").write_text("it.only('renders', () => {});\n", encoding="utf-8")
    ok, report = gate.run_gate(project)
    assert not ok and "tests/web.test.js:1" in report


def test_module_skip_in_existing_file_blocks(tmp_path):
    project = make_tests_repo(tmp_path)
    path = project / "tests" / "test_text.py"
    path.write_text("import pytest\npytestmark = pytest.mark.skip('later')\n\n\n" + path.read_text(encoding="utf-8"),
                    encoding="utf-8")
    ok, report = gate.run_gate(project)
    assert not ok and "tests/test_text.py:2" in report


def test_removed_test_function_blocks_unless_named(tmp_path):
    project = make_tests_repo(tmp_path)
    path = project / "tests" / "test_math.py"
    path.write_text("def test_add():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    ok, report = gate.run_gate(project)
    assert not ok and "тестов стало меньше: 3 → 2" in report and "test_math.py::test_mul" in report
    add_decision(project, "test_mul удалён: дублировал test_add")
    assert gate.run_gate(project)[0]


def test_renamed_test_file_passes(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "test_text.py").rename(project / "tests" / "test_strings.py")
    ok, report = gate.run_gate(project)
    assert ok, report


def test_base_count_is_cached(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "test_text.py").rename(project / "tests" / "test_strings.py")
    assert gate.run_gate(project)[0]
    cache = json.loads(gate.state_path(project).read_text(encoding="utf-8"))["testBase"]
    assert cache["counts"][PYTEST_CMD]["count"] == 3
    gate._write_state(project, 1)  # счётчик провалов не стирает кэш
    assert "testBase" in json.loads(gate.state_path(project).read_text(encoding="utf-8"))


def test_base_from_unfinished_autopilot_run(tmp_path):
    project = make_tests_repo(tmp_path, base_in="state")
    (project / "tests" / "test_text.py").unlink()
    ok, report = gate.run_gate(project)
    assert not ok and "начало прогона Autopilot" in report


def test_no_base_only_warns(tmp_path):
    project = make_tests_repo(tmp_path, base_in="state")
    state = {"version": 2, "dir": "run1", "baseCommit": "abc1234", "finishedAt": "2026-10-26T12:00:00Z"}
    (project / ".autopilot" / "state.js").write_text("window.STATE = " + json.dumps(state), encoding="utf-8")
    (project / "tests" / "test_text.py").unlink()
    ok, report = gate.run_gate(project)
    assert ok and "Проверка подгонки тестов пропущена: нет базы этапа" in report


def test_unknown_base_commit_only_warns(tmp_path):
    project = make_tests_repo(tmp_path)
    data = json.loads((project / ".autopilot" / "program.json").read_text(encoding="utf-8"))
    data["stages"][0]["baseCommit"] = "0" * 40
    (project / ".autopilot" / "program.json").write_text(json.dumps(data), encoding="utf-8")
    ok, report = gate.run_gate(project)
    assert ok and "Проверка подгонки тестов пропущена" in report


def test_hook_blocks_weakened_tests(tmp_path):
    project = make_tests_repo(tmp_path)
    (project / "tests" / "test_text.py").unlink()
    assert gate.hook_claude_stop(project, {"stop_hook_active": False}) == 2


@pytest.mark.parametrize("path, expected", [
    ("tests/test_a.py", True), ("pkg/a_test.py", True), ("src/a.test.ts", True), ("web/b.spec.js", True),
    ("tests/helpers/util.py", True), ("conftest.py", True), ("tests/data/golden.json", False), ("src/app.py", False),
])
def test_is_test_path(path, expected):
    assert gate.is_test_path(path) is expected

@pytest.mark.parametrize("output, expected", [
    ("....\n5 passed, 2 skipped, 1 xfailed, 3 warnings in 1.20s\n", 8),
    ("===== 4 passed, 1 deselected in 0.5s =====", 4),
    ("no summary here", None),
])
def test_summary_count(output, expected):
    assert gate._summary_count(output) == expected

# --- T17.2: повтор упавших тестов pytest (D41) ---

FLAKY_TEST = """from pathlib import Path


def test_flaky():
    counter = Path(__file__).with_name("count.txt")
    runs = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(runs + 1))
    assert runs >= {passes_after}


def test_steady():
    pass
"""


def flaky_project(tmp_path: Path, passes_after: int) -> Path:
    project = tmp_path / "proj"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_flaky.py").write_text(FLAKY_TEST.format(passes_after=passes_after), encoding="utf-8")
    configure(project, [f'"{sys.executable}" -m pytest -q tests'])
    return project


def test_flaky_test_passes_on_retry_and_is_recorded(tmp_path):
    project = flaky_project(tmp_path, passes_after=1)
    ok, report = gate.run_gate(project)
    assert ok, report
    assert "--lf  (повтор только упавших)" in report
    assert "ГЕЙТ ПРОЙДЕН (нестабильные: tests/test_flaky.py::test_flaky)" in report
    recorded = json.loads(gate.flaky_path(project).read_text(encoding="utf-8"))["tests"]
    assert list(recorded) == ["tests/test_flaky.py::test_flaky"] and recorded["tests/test_flaky.py::test_flaky"]["count"] == 1
    assert (project / "tests" / "count.txt").read_text() == "2"  # повтор запускал только упавший тест


def test_test_failing_twice_blocks(tmp_path):
    project = flaky_project(tmp_path, passes_after=2)
    ok, report = gate.run_gate(project)
    assert not ok and "--lf" in report and "ГЕЙТ НЕ ПРОЙДЕН" in report
    assert not gate.flaky_path(project).exists()


def test_other_commands_are_not_retried(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    ok, report = gate.run_gate(tmp_path)
    assert not ok and "--lf" not in report


def test_failed_tests_parsed_from_summary():
    out = ("FAILED tests/a.py::test_x - AssertionError: 1 != 2\nERROR tests/b.py::test_y[p 1]\n"
           "FAILED tests/a.py::test_x - again\n1 failed, 1 error in 0.1s")
    assert gate.failed_tests(out) == ["tests/a.py::test_x", "tests/b.py::test_y[p 1]"]

# --- T17.3: журнал гейта ---

def log_results(project: Path) -> list[dict]:
    path = gate.log_path(project)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_log_records_every_outcome(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    gate.hook_claude_stop(tmp_path, {"stop_hook_active": False})           # блок
    gate.hook_claude_stop(tmp_path, {"stop_hook_active": True})            # отпуск по защите
    configure(tmp_path, [py("print('ok')", tmp_path, "ok.py")])
    gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}, "codex")  # проход
    write_autopilot_state(tmp_path, {"kind": "spec"})
    gate.hook_claude_stop(tmp_path, {"stop_hook_active": False})           # ждёт владельца
    write_autopilot_state(tmp_path, None)
    orchestrator = write_transcript(tmp_path / "o.jsonl", "<command-name>/autopilot-program</command-name>")
    gate.hook_claude_stop(tmp_path, {"stop_hook_active": False, "transcript_path": orchestrator})
    gate.main(["--project", str(tmp_path)])                                 # вручную
    gate.hook_agy_stop(tmp_path, agy_event(tmp_path))
    log = log_results(tmp_path)
    assert [e["result"] for e in log] == ["block", "loop-release", "pass", "skip-waiting", "skip-program-chat", "pass", "pass"]
    assert [e["mode"] for e in log][-2:] == ["manual", "hook"] and [e["host"] for e in log][2] == "codex"
    assert log[-1]["host"] == "agy" and log[3]["waiting"] == "spec"
    first = log[0]["commands"][0]
    assert first["code"] == 1 and first["seconds"] >= 0 and first["retry"] is False and "at" in log[0]


def test_log_has_stage_retry_and_flaky(tmp_path):
    project = flaky_project(tmp_path, passes_after=1)
    (project / ".autopilot").mkdir()
    stage = {"id": "S2", "status": "running", "startedAt": "2026-10-27T10:00:00Z"}
    (project / ".autopilot" / "program.json").write_text(json.dumps({"stages": [stage]}), encoding="utf-8")
    assert gate.main(["--project", str(project)]) == 0
    entry = log_results(project)[-1]
    assert entry["stage"] == "S2" and entry["result"] == "pass"
    assert entry["flaky"] == ["tests/test_flaky.py::test_flaky"] and [c["retry"] for c in entry["commands"]] == [False, True]


def test_log_config_error_and_unconfigured_folder(tmp_path):
    folder = tmp_path / ".autopilot-kit"
    folder.mkdir()
    (folder / "project.toml").write_text("[gate\n", encoding="utf-8")
    assert gate.main(["--project", str(tmp_path)]) == 1
    assert log_results(tmp_path)[-1]["result"] == "config-error"
    bare = tmp_path / "bare"
    bare.mkdir()
    assert gate.main(["--project", str(bare)]) == 0
    assert not (bare / ".autopilot-kit").exists()  # в чужую папку журнал не пишется


# ── Волна 21: документный прогон и host ручных прогонов ─────────────────────

@pytest.fixture
def clean_drive_env(monkeypatch, tmp_path):
    """Ни настоящего профиля (pinned_drive читает ~/.autopilot-kit/profile.toml), ни окружения приложения."""
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "kit-home"))
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def test_manual_mode_allow_no_tests(tmp_path):
    # T21.1: pytest-код 5 («тестов нет») в строгом режиме — провал, с --allow-no-tests — проход (как в хуке по D14)
    script = tmp_path / "empty_suite.py"
    script.write_text("import sys; sys.exit(5)", encoding="utf-8")
    configure(tmp_path, [f'"{sys.executable}" "{script}" -m pytest -q'])
    ok, report = gate.run_gate(tmp_path)
    assert not ok and "ГЕЙТ НЕ ПРОЙДЕН" in report
    ok, report = gate.run_gate(tmp_path, allow_no_tests=True)
    assert ok and "тестов пока нет" in report
    assert gate.main(["--project", str(tmp_path)]) == 1
    assert gate.main(["--project", str(tmp_path), "--allow-no-tests"]) == 0


def test_manual_run_records_drive_host(tmp_path, monkeypatch, clean_drive_env):
    # T21.2: ручной прогон пишет привод тем же определением, что и хук
    configure(tmp_path, [])
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop-3p")
    assert gate.main(["--project", str(tmp_path)]) == 0
    assert log_results(tmp_path)[-1]["host"] == "claude-gate"
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT")
    assert gate.main(["--project", str(tmp_path)]) == 0
    assert log_results(tmp_path)[-1]["host"] == "claude"
    monkeypatch.delenv("CLAUDECODE")
    assert gate.main(["--project", str(tmp_path)]) == 0
    assert log_results(tmp_path)[-1]["host"] == "unknown"  # из терминала — честный ответ


def test_manual_run_host_follows_project_pin(tmp_path, monkeypatch, clean_drive_env):
    project = tmp_path / "p"
    (project / ".autopilot-kit").mkdir(parents=True)
    (project / ".autopilot-kit" / "project.toml").write_text(
        'drive = "claude-gate"\n[gate]\ncommands = []\n', encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert gate.main(["--project", str(project)]) == 0
    assert log_results(project)[-1]["host"] == "claude-gate"


def test_loop_release_carries_tests_first_hint(tmp_path, capsys):
    # T21.8: блок не слабеет, но второй подряд провал несёт подсказку про тесты раньше реализации
    configure(tmp_path, [py("print('boom'); raise SystemExit(1)", tmp_path, "bad.py")])
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 2
    err = capsys.readouterr().err
    assert "ГЕЙТ НЕ ПРОЙДЕН" in err and gate.LOOP_HINT not in err  # первый провал — без подсказки
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": True}) == 0
    out = capsys.readouterr()
    assert "раньше реализации" in out.err
    payload = json.loads(out.out.strip())
    assert "systemMessage" in payload and "раньше реализации" in payload["systemMessage"]


# ── D51: сжатие контекста не должно превращать оркестратор в «обычный чат» ──

ORCH_FIRST = "<command-message>autopilot-program</command-message>\n<command-name>/autopilot-program</command-name>"


def continued(previous: Path | None, body: str = "Summary: ...") -> str:
    tail = f"\nIf you need specific details from before compaction, read the full transcript at: {previous}\nContinue." if previous else "\nContinue."
    return "This session is being continued from a previous conversation that ran out of context.\n" + body + tail


def test_compacted_orchestrator_is_still_an_orchestrator_by_the_previous_transcript(tmp_path, capsys):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    old = Path(write_transcript(tmp_path / "old.jsonl", ORCH_FIRST))
    mid = Path(write_transcript(tmp_path / "mid.jsonl", continued(old)))
    new = write_transcript(tmp_path / "new.jsonl", continued(mid))  # два сжатия подряд
    event = {"stop_hook_active": False, "transcript_path": new}
    assert gate.program_chat_kind(event) == "orchestrator"
    assert gate.hook_claude_stop(tmp_path, event) == 0  # красные тесты и 10 минут гейта оркестратору не нужны
    assert "оркестратор" in capsys.readouterr().err


def test_compacted_stage_and_ordinary_chats_stay_gated(tmp_path):
    configure(tmp_path, [py("raise SystemExit(1)", tmp_path)])
    old = Path(write_transcript(tmp_path / "old.jsonl", "Ты — сессия этапа M2. Вызови навык autopilot-stage"))
    event = {"stop_hook_active": False, "transcript_path": write_transcript(tmp_path / "new.jsonl", continued(old))}
    assert gate.program_chat_kind(event) is None
    assert gate.hook_claude_stop(tmp_path, event) == 2
    own = tmp_path / "self.jsonl"  # сжатие «на месте»: ссылка на тот же файл; пересказ без вызова навыка — обычный чат
    assert gate.program_chat_kind({"transcript_path": write_transcript(own, continued(own))}) is None


def test_compacted_orchestrator_without_previous_file_is_recognised_by_the_summary(tmp_path):
    gone = tmp_path / "deleted.jsonl"
    summary = "Summary:\n1. Primary Request and Intent:\n   The owner invoked `/autopilot-program docs/PLAN.md`: I am the program orchestrator"
    path = write_transcript(tmp_path / "new.jsonl", continued(gone, summary))
    assert gate.program_chat_kind({"transcript_path": path}) == "orchestrator"
    other = write_transcript(tmp_path / "other.jsonl", continued(gone, "Summary: чиню kit, упомянуты /autopilot-program и program.py"))
    assert gate.program_chat_kind({"transcript_path": other}) is None


def test_slow_hook_gate_is_marked_and_warned(tmp_path, capsys):
    configure(tmp_path, [py("pass", tmp_path)])
    record = {"commands": [{"command": "x", "code": 0, "seconds": 1200.0}]}
    assert "Try again" in gate.mark_slow(record) and record["slow"] is True
    fast = {"commands": [{"command": "x", "code": 0, "seconds": 30.0}]}
    assert gate.mark_slow(fast) is None and "slow" not in fast


# ── D51: повторный гейт на неизменённом проекте пропускается ──

def git_project(tmp_path: Path, code: str) -> Path:
    def git(*args):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    configure(tmp_path, [py(code, tmp_path)])
    (tmp_path / ".gitignore").write_text(".autopilot-kit/\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    return tmp_path


COUNT = "from pathlib import Path\np = Path(__file__).parent / 'runs.txt'\np.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"


def runs(project: Path) -> int:
    path = project / "runs.txt"
    return len(path.read_text()) if path.exists() else 0


def test_hook_skips_repeated_gate_on_unchanged_project(tmp_path, capsys):
    project = git_project(tmp_path, COUNT)
    event = {"stop_hook_active": False}
    assert gate.hook_claude_stop(project, event) == 0 and runs(project) == 1
    assert gate.hook_claude_stop(project, event) == 0 and runs(project) == 1  # второй ход без изменений — гейт не запускался
    assert "не менялся" in capsys.readouterr().err
    (project / ".autopilot").mkdir()
    (project / ".autopilot" / "program.json").write_text("{}", encoding="utf-8")  # служебные файлы программы — не изменение
    assert gate.hook_claude_stop(project, event) == 0 and runs(project) == 1
    (project / "app.py").write_text("x = 2\n", encoding="utf-8")
    assert gate.hook_claude_stop(project, event) == 0 and runs(project) == 2  # изменили код — проверяем снова
    (project / "new.py").write_text("y = 1\n", encoding="utf-8")  # новый неотслеживаемый файл тоже изменение
    assert gate.hook_claude_stop(project, event) == 0 and runs(project) == 3
    last = [json.loads(line) for line in gate.log_path(project).read_text(encoding="utf-8").splitlines()][-1]
    assert last["result"] == "pass"


def test_skip_unchanged_needs_a_green_run_and_a_fresh_one(tmp_path, monkeypatch):
    project = git_project(tmp_path, "import sys\nfrom pathlib import Path\nPath(__file__).parent.joinpath('r.txt').write_text('x')\nsys.exit(1)\n")
    assert gate.hook_claude_stop(project, {"stop_hook_active": False}) == 2  # красный гейт зелёным не помечается
    assert gate.hook_claude_stop(project, {"stop_hook_active": False}) == 2
    ok_project = tmp_path / "ok"
    ok_project.mkdir()
    ok = git_project(ok_project, COUNT)
    assert gate.hook_claude_stop(ok, {"stop_hook_active": False}) == 0
    state = json.loads(gate.state_path(ok).read_text(encoding="utf-8"))
    state["green"]["at"] = "2020-01-01T00:00:00+00:00"  # прошло больше срока годности — проверяем заново
    gate.state_path(ok).write_text(json.dumps(state), encoding="utf-8")
    assert gate.hook_claude_stop(ok, {"stop_hook_active": False}) == 0 and runs(ok) == 2
    monkeypatch.setenv("AUTOPILOT_KIT_GATE_ALWAYS", "1")
    assert gate.hook_claude_stop(ok, {"stop_hook_active": False}) == 0 and runs(ok) == 3


def test_fingerprint_is_none_outside_git_so_gate_always_runs(tmp_path):
    configure(tmp_path, [py(COUNT, tmp_path)])
    assert gate.tree_fingerprint(tmp_path) is None
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 0
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 0 and runs(tmp_path) == 2


# ── D51: быстрый набор для хука (hook_commands) ──

def test_hook_runs_fast_set_while_manual_gate_runs_the_full_one(tmp_path):
    fast = py("from pathlib import Path\nPath(__file__).parent.joinpath('fast.txt').write_text('1')\n", tmp_path, "fast.py")
    full = py("from pathlib import Path\nPath(__file__).parent.joinpath('full.txt').write_text('1')\n", tmp_path, "full.py")
    (tmp_path / ".autopilot-kit").mkdir()
    (tmp_path / ".autopilot-kit" / "project.toml").write_text(
        f"[gate]\ncommands = {json.dumps([full])}\nhook_commands = {json.dumps([fast])}\ntimeout_seconds = 3600\n", encoding="utf-8")
    config = gate.load_config(tmp_path)
    assert config["hook_commands"] == [fast] and config["hook_timeout"] == gate.HOOK_SLOW_SECONDS
    assert gate.hook_claude_stop(tmp_path, {"stop_hook_active": False}) == 0
    assert (tmp_path / "fast.txt").exists() and not (tmp_path / "full.txt").exists()  # в хуке — быстрый
    assert gate.main(["--project", str(tmp_path)]) == 0
    assert (tmp_path / "full.txt").exists()  # вручную и на приёмке — полный


def test_hook_commands_must_be_a_nonempty_list_and_timeout_is_overridable(tmp_path):
    (tmp_path / ".autopilot-kit").mkdir()
    cfg = tmp_path / ".autopilot-kit" / "project.toml"
    cfg.write_text("[gate]\ncommands = ['x']\nhook_commands = []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hook_commands"):
        gate.load_config(tmp_path)
    cfg.write_text("[gate]\ncommands = ['x']\nhook_commands = ['y']\ntimeout_seconds = 3600\nhook_timeout_seconds = 300\n", encoding="utf-8")
    assert gate.load_config(tmp_path)["hook_timeout"] == 300
