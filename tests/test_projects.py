import json
import subprocess
from pathlib import Path

import pytest

from kit import __main__ as cli
from kit import program, projects

OLD_HOOK = 'python "C:/Users/olduser/.autopilot-kit/bin/gate.py" --hook claude-stop'


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".autopilot-kit" / "bin").mkdir(parents=True)
    (home / ".autopilot-kit" / "bin" / "gate.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    monkeypatch.setenv("AUTOPILOT_KIT_NO_SERVE", "1")
    return home


def real_python(which_path="C:/Python312/python.exe"):
    return (lambda _exe: which_path,
            lambda args: subprocess.CompletedProcess(args, 0, stdout="kit-ok\n", stderr=""))


def moved_project(tmp_path: Path, name="proj", hook=OLD_HOOK, gitignore=None) -> Path:
    """Проект, приехавший со старой машины: хук на домашний каталог olduser, git без .gitignore, сессии в program.json."""
    root = tmp_path / name
    (root / ".claude").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    settings = {"permissions": {"allow": ["Bash(git status *)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": hook, "timeout": 1200}]}]}}
    (root / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    (root / ".autopilot-kit").mkdir()
    (root / ".autopilot-kit" / "project.toml").write_text(
        "[gate]\ncommands = ['.venv\\\\Scripts\\\\python.exe -m pytest -q']\n", encoding="utf-8")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    (root / ".autopilot").mkdir()
    data = {"version": program.VERSION, "goal": "g", "mode": "full", "stages": [], "questions": [], "orchestrator": "local_old",
            "pool": [{"sessionId": "local_spare", "at": "2026-10-20T10:00:00Z"}]}
    (root / ".autopilot" / "program.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def statuses(rows):
    return {name.split(": ", 1)[-1]: status for name, status, _ in rows}


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_doctor_flags_moved_project(home, tmp_path):
    root = moved_project(tmp_path)
    which, run = real_python()
    rows = statuses(projects.check_project(root, which, run))
    assert rows["хук гейта"] == projects.FAIL and rows[".gitignore"] == projects.FAIL
    assert rows["команды гейта"] == projects.OK and rows["`python` хуков"] == projects.OK


def test_python_stub_is_failure_with_hint():
    stub = "C:/Users/x/AppData/Local/Microsoft/WindowsApps/python.exe"
    status, message = projects.python_works("python", lambda _e: stub,
                                            lambda args: subprocess.CompletedProcess(args, 9009, stdout="", stderr="Python was not found"))
    assert status == projects.FAIL and "Псевдонимы" in message
    assert projects.python_works("python", lambda _e: None)[0] == projects.FAIL


def test_missing_gate_tool_fails(home, tmp_path):
    root = moved_project(tmp_path)
    (root / ".autopilot-kit" / "project.toml").write_text("[gate]\ncommands = ['uv run pytest -q']\n", encoding="utf-8")
    which = lambda exe: None if exe == "uv" else "C:/Python312/python.exe"
    rows = projects.check_project(root, which, real_python()[1])
    assert [m for n, s, m in rows if n.endswith("команды гейта")] == ["не найдена программа: uv run pytest -q"]


def test_dry_run_changes_nothing(home, tmp_path):
    root = moved_project(tmp_path)
    before, home_before = snapshot(root), snapshot(home)
    lines = projects.relocate([root], dry_run=True)
    assert snapshot(root) == before and snapshot(home) == home_before
    assert any("путь гейта" in line for line in lines) and any("previous" in line for line in lines)
    assert lines[-1] == "(--dry-run: ничего не изменено)"


def test_relocate_fixes_moved_project(home, tmp_path):
    root = moved_project(tmp_path)
    lines = projects.relocate([root])
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert command == f'python "{projects.gate_path()}" --hook claude-stop'
    assert settings["permissions"] == {"allow": ["Bash(git status *)"]}  # остальное не тронуто
    assert list((root / ".claude").glob("settings.json.bak-*"))
    assert ".autopilot-kit/gate_log.jsonl" in (root / ".gitignore").read_text(encoding="utf-8")
    data = json.loads((root / ".autopilot" / "program.json").read_text(encoding="utf-8"))
    assert data["orchestrator"] is None and data["pool"] == []
    assert data["previous"][0]["orchestrator"] == "local_old" and data["previous"][0]["pool"][0]["sessionId"] == "local_spare"
    assert (home / ".autopilot-kit" / "kit_path").exists() and any(line.startswith("kit_path:") for line in lines)
    which, run = real_python()
    assert all(status == projects.OK for _, status, _ in projects.check_project(root, which, run))
    assert all("без изменений" in line for line in projects.relocate([root]))  # повтор ничего не меняет


def test_sessions_of_this_machine_stay(home, tmp_path):
    root = moved_project(tmp_path, hook=f'python "{(home / ".autopilot-kit" / "bin" / "gate.py").as_posix()}" --hook claude-stop')
    program.cmd_orchestrator(root, "local_here")
    projects.relocate([root])
    data = json.loads((root / ".autopilot" / "program.json").read_text(encoding="utf-8"))
    assert data["orchestrator"] == "local_here" and "previous" not in data
    data["orchestratorMachine"] = "old-pc|C:\\Users\\olduser"  # оркестратор записан на другой машине
    (root / ".autopilot" / "program.json").write_text(json.dumps(data), encoding="utf-8")
    projects.relocate([root])
    data = json.loads((root / ".autopilot" / "program.json").read_text(encoding="utf-8"))
    assert data["orchestrator"] is None and data["previous"][0]["machine"] == "old-pc|C:\\Users\\olduser"


def test_gitignore_covering_whole_folder_is_enough(home, tmp_path):
    root = moved_project(tmp_path, gitignore="node_modules/\n/.autopilot-kit/\n/.claude/\n*.bak-20*\n")
    assert projects._gitignored(root) == []
    (root / ".git").rmdir()
    assert projects._gitignored(moved_project(tmp_path, name="nogit")) != []
    assert projects._gitignored(root) == []  # не git — в коммит ничего не попадёт


def test_gitignore_needs_launch_json_line(home, tmp_path):
    # T21.11: .claude/launch.json машинно-зависим — строка проверяется наравне со служебными файлами kit
    root = moved_project(tmp_path, gitignore="*.bak-20*\n.autopilot-kit/last_host\n.autopilot-kit/gate_state.json\n"
                                             ".autopilot-kit/gate_log.jsonl\n.autopilot-kit/flaky.json\n")
    assert projects._gitignored(root) == [".claude/launch.json"]
    projects.relocate([root])
    assert ".claude/launch.json" in (root / ".gitignore").read_text(encoding="utf-8")
    assert projects._gitignored(root) == []


def test_tracked_launch_json_is_a_warning_not_a_fail(home, tmp_path):
    # T21.11: файл уже отслеживается (старый проект, force-add) — WARN «решение владельца», kit его не переписывает
    from tests.conftest import git
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "launch.json").write_text("{}", encoding="utf-8")
    (root / ".gitignore").write_text("*.bak-20*\n/.autopilot-kit/\n.claude/launch.json\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    subprocess.run(["git", "add", "-f", ".claude/launch.json"], cwd=root, check=True, capture_output=True)
    which, run = real_python()
    rows = projects.check_project(root, which, run)
    launch_rows = [r for r in rows if r[0].endswith(".claude/launch.json")]
    assert launch_rows and launch_rows[0][1] == projects.WARN and "решение владельца" in launch_rows[0][2]
    gitignore_rows = [r for r in rows if r[0].endswith(".gitignore")]
    assert gitignore_rows[0][1] == projects.OK  # строка на месте — отсутствие в git не вменяется
    before = (root / ".claude" / "launch.json").read_text(encoding="utf-8")
    projects.relocate([root])
    assert (root / ".claude" / "launch.json").read_text(encoding="utf-8") == before  # не переписали


def test_registry_without_unc_duplicates(home, tmp_path):
    root = moved_project(tmp_path)
    reg = {"programs": [{"root": str(root), "goal": "g"}, {"root": str(root).upper() + "\\", "goal": "g"}]}
    program.registry_path().write_text(json.dumps(reg), encoding="utf-8")
    assert len(projects.project_list()) == 1
    projects.relocate()
    kept = json.loads(program.registry_path().read_text(encoding="utf-8"))["programs"]
    assert len(kept) == 1 and list(program.registry_path().parent.glob("programs.json.bak-*"))


def test_cli_doctor_projects_and_relocate(home, tmp_path, capsys):
    root = moved_project(tmp_path)
    assert cli.main(["relocate", "--dry-run", "--project", str(root)]) == 0
    assert "ничего не изменено" in capsys.readouterr().out
    cli.main(["doctor", "--project", str(root)])
    assert "proj: хук гейта" in capsys.readouterr().out


# ── D51: время гейта в хуке ──

def test_doctor_warns_when_gate_timeout_exceeds_hook_timeout(home, tmp_path):
    root = moved_project(tmp_path, hook='python "$HOME/.autopilot-kit/bin/gate.py" --hook claude-stop')
    (root / ".autopilot-kit" / "project.toml").write_text(
        "[gate]\ncommands = ['.venv\\Scripts\\python.exe -m pytest -q']\ntimeout_seconds = 3600\n", encoding="utf-8")
    which, run = real_python()
    rows = projects.check_project(root, which, run)
    time_rows = [r for r in rows if r[0].endswith("время гейта")]
    assert time_rows and time_rows[0][1] == projects.WARN and "3600" in time_rows[0][2] and "1200" in time_rows[0][2]
    (root / ".autopilot-kit" / "project.toml").write_text(
        "[gate]\ncommands = ['.venv\\Scripts\\python.exe -m pytest -q']\ntimeout_seconds = 600\n", encoding="utf-8")
    assert not [r for r in projects.check_project(root, which, run) if r[0].endswith("время гейта")]


def test_doctor_warns_about_slow_hook_runs_in_the_last_day(home, tmp_path):
    from datetime import datetime, timedelta, timezone
    root = moved_project(tmp_path)
    now = datetime.now(timezone.utc)

    def entry(age_h, seconds, mode="hook"):
        return json.dumps({"at": (now - timedelta(hours=age_h)).isoformat(), "mode": mode, "result": "pass",
                           "commands": [{"command": "x", "code": 0, "seconds": seconds}]})

    lines = [entry(1, 1200.0), entry(2, 950.0), entry(3, 100.0), entry(30, 1500.0), entry(1, 2000.0, "manual")]
    (root / ".autopilot-kit" / "gate_log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert projects.slow_gate_runs(root, now) == (2, 1200)  # старше суток и ручные запуски не считаются
    rows = projects.gate_time_rows(root, None, now)
    assert rows and rows[0][1] == projects.WARN and "2 запусков" in rows[0][2] and "Try again" in rows[0][2]
    (root / ".autopilot-kit" / "gate_log.jsonl").write_text(entry(1, 100.0) + "\n", encoding="utf-8")
    assert projects.gate_time_rows(root, None, now) == []


def test_gate_time_rows_use_hook_timeout_when_fast_set_exists(home, tmp_path):
    root = moved_project(tmp_path, hook='python "$HOME/.autopilot-kit/bin/gate.py" --hook claude-stop')  # предел хука 1200
    toml = root / ".autopilot-kit" / "project.toml"
    toml.write_text("[gate]\ncommands = ['x']\nhook_commands = ['y']\ntimeout_seconds = 3600\n", encoding="utf-8")
    config = projects.gate.load_config(root)
    assert projects.gate_time_rows(root, config) == []  # у быстрого набора свой предел (900 с) — укладывается в 1200
    toml.write_text("[gate]\ncommands = ['x']\nhook_commands = ['y']\nhook_timeout_seconds = 1500\n", encoding="utf-8")
    rows = projects.gate_time_rows(root, projects.gate.load_config(root))
    assert rows and "hook_timeout_seconds" in rows[0][2]
