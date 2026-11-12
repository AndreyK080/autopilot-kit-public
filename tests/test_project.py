import json

import pytest

from kit import __main__ as cli
from kit import project


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(path))
    return path


def read_settings(folder):
    return json.loads((folder / ".claude" / "settings.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("template", ["python-cli", "small-web", "generic"])
def test_clean_folder(template, home, tmp_path):
    target = tmp_path / "proj"
    report = project.init_project(template, target)
    assert all(line.startswith("создан") for line in report)
    for rel in ("CLAUDE.md", "AGENTS.md", ".claude/settings.json", ".autopilot-kit/project.toml"):
        assert (target / rel).exists()
    command = read_settings(target)["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert command == 'python "$HOME/.autopilot-kit/bin/gate.py" --hook claude-stop'  # D48: машинно-независимый путь
    assert "<~>" not in command
    assert "<~>" not in (target / "AGENTS.md").read_text(encoding="utf-8")


def test_repeat_init_changes_nothing(home, tmp_path):
    target = tmp_path / "proj"
    project.init_project("python-cli", target)
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    report = project.init_project("python-cli", target)
    assert all(line.startswith("без изменений") for line in report)
    assert before == {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}


def test_existing_settings_are_merged_not_replaced(home, tmp_path):
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    original = {
        "model": "opus",
        "permissions": {"allow": ["Bash(git status *)", "Bash(make *)"], "deny": ["Read(./private/**)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]},
    }
    (target / ".claude" / "settings.json").write_text(json.dumps(original), encoding="utf-8")

    report = project.init_project("python-cli", target)
    assert any(line.startswith("слит") for line in report)
    merged = read_settings(target)
    assert merged["model"] == "opus"
    allow = merged["permissions"]["allow"]
    assert allow[:2] == ["Bash(git status *)", "Bash(make *)"] and allow.count("Bash(git status *)") == 1
    assert "Read(./private/**)" in merged["permissions"]["deny"] and "Read(./.env)" in merged["permissions"]["deny"]
    commands = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
    assert commands[0] == "echo mine" and len(commands) == 2 and "gate.py" in commands[1]
    assert list((target / ".claude").glob("settings.json.bak-*"))

    project.init_project("python-cli", target)  # повтор: хук не дублируется
    again = [h["command"] for g in read_settings(target)["hooks"]["Stop"] for h in g["hooks"]]
    assert again == commands


def test_existing_gitignore_gets_missing_lines(home, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".gitignore").write_text("__pycache__/\n.autopilot-kit/flaky.json", encoding="utf-8")
    report = project.init_project("python-cli", target)
    text = (target / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("__pycache__/\n.autopilot-kit/flaky.json\n")
    assert ".autopilot-kit/gate_log.jsonl" in text and text.count(".autopilot-kit/flaky.json") == 1
    assert any(line.startswith("дописан: .gitignore") for line in report)
    assert list(target.glob(".gitignore.bak-*")) and not (target / ".gitignore.kit-new").exists()
    assert "без изменений: .gitignore" in project.init_project("python-cli", target)


def test_existing_files_get_kit_new(home, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "AGENTS.md").write_text("мои правила", encoding="utf-8")
    report = project.init_project("python-cli", target)
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "мои правила"
    assert (target / "AGENTS.md.kit-new").exists()
    assert any("AGENTS.md.kit-new" in line for line in report)


def test_broken_settings_json_is_kept(home, tmp_path):
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    (target / ".claude" / "settings.json").write_text("{oops", encoding="utf-8")
    report = project.init_project("python-cli", target)
    assert (target / ".claude" / "settings.json").read_text(encoding="utf-8") == "{oops"
    assert (target / ".claude" / "settings.json.kit-new").exists()
    assert any("не удалось прочитать" in line for line in report)


def test_unknown_template_and_cli(home, tmp_path, capsys):
    with pytest.raises(ValueError, match="python-cli"):
        project.init_project("nope", tmp_path)
    assert cli.main(["project", "init", "--template", "nope", "--path", str(tmp_path)]) == 2
    assert cli.main(["project", "init", "--template", "small-web", "--path", str(tmp_path / "p")]) == 0
    assert (tmp_path / "p" / "AGENTS.md").exists()


def test_generic_template_has_empty_gate_and_stack_placeholder(home, tmp_path):
    import tomllib

    target = tmp_path / "proj"
    project.init_project("generic", target)
    config = tomllib.loads((target / ".autopilot-kit" / "project.toml").read_text(encoding="utf-8"))
    assert config["gate"]["commands"] == []
    assert "## Стек и запуск" in (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "generic" in project.available_templates()


def read_codex_hooks(folder):
    return json.loads((folder / ".codex" / "hooks.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("template", ["python-cli", "small-web", "generic"])
def test_codex_stop_hook_is_installed(template, home, tmp_path):
    target = tmp_path / "proj"
    project.init_project(template, target)
    hook = read_codex_hooks(target)["hooks"]["Stop"][0]["hooks"][0]
    assert hook["type"] == "command" and "--hook codex-stop" in hook["command"]
    assert home.as_posix() in hook["command"] and "<~>" not in hook["command"]


def test_existing_codex_hooks_are_merged(home, tmp_path):
    target = tmp_path / "proj"
    (target / ".codex").mkdir(parents=True)
    original = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}], "SessionStart": []}}
    (target / ".codex" / "hooks.json").write_text(json.dumps(original), encoding="utf-8")

    report = project.init_project("generic", target)
    assert any(line.startswith("слит: .codex/hooks.json") for line in report)
    merged = read_codex_hooks(target)["hooks"]
    commands = [h["command"] for g in merged["Stop"] for h in g["hooks"]]
    assert commands[0] == "echo mine" and len(commands) == 2 and "codex-stop" in commands[1]
    assert "SessionStart" in merged
    again = project.init_project("generic", target)
    assert any(line.startswith("без изменений: .codex/hooks.json") for line in again)


def read_agy_hooks(folder):
    return json.loads((folder / ".agents" / "hooks.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("template", ["python-cli", "small-web", "generic"])
def test_agy_stop_hook_is_installed(template, home, tmp_path):
    target = tmp_path / "proj"
    project.init_project(template, target)
    hook = read_agy_hooks(target)["autopilot-gate"]["Stop"][0]
    assert hook["type"] == "command" and "--hook agy-stop" in hook["command"] and hook["timeout"] == 1200
    assert home.as_posix() in hook["command"] and "<~>" not in hook["command"]


def test_existing_agy_hooks_are_merged(home, tmp_path):
    target = tmp_path / "proj"
    (target / ".agents").mkdir(parents=True)
    original = {"my-lint": {"PostToolUse": [{"matcher": "run_command", "hooks": [{"command": "echo mine"}]}]}}
    (target / ".agents" / "hooks.json").write_text(json.dumps(original), encoding="utf-8")

    report = project.init_project("generic", target)
    assert any(line.startswith("слит: .agents/hooks.json") for line in report)
    merged = read_agy_hooks(target)
    assert merged["my-lint"] == original["my-lint"] and "--hook agy-stop" in merged["autopilot-gate"]["Stop"][0]["command"]
    again = project.init_project("generic", target)
    assert any(line.startswith("без изменений: .agents/hooks.json") for line in again)


def test_templates_keep_launch_json_out_of_git():
    # T21.11: конфигурация панели машинно-зависима (абсолютный путь program.py) — вне git, page --launch создаёт её заново
    from kit import project as project_module
    for template in project_module.available_templates():
        text = (project_module.TEMPLATES_DIR / template / ".gitignore").read_text(encoding="utf-8")
        assert ".claude/launch.json" in text, template
