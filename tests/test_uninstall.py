import builtins

import pytest

from kit import commands, profile, render, uninstall, upstream


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(path))
    return path


@pytest.fixture
def installed(home, remote, tmp_path):
    pin = tmp_path / "upstream.pin"
    pin.write_text(remote["first"] + "\n", encoding="utf-8")
    assert commands.cmd_install(remote["url"], pin) == 0
    return home


def test_uninstall_removes_what_kit_installed(installed, capsys):
    mine = installed / ".claude" / "agents" / "my-own.md"
    mine.write_text("мой агент", encoding="utf-8")
    other_skill = installed / ".claude" / "skills" / "other"
    other_skill.mkdir()
    (other_skill / "SKILL.md").write_text("чужой навык", encoding="utf-8")
    (installed / ".autopilot-kit" / "profile.toml").write_text('preset = "quality"\n', encoding="utf-8")

    assert uninstall.cmd_uninstall(assume_yes=True) == 0
    for target in upstream.default_targets():
        assert not target.exists()
    assert not (installed / ".claude" / "skills" / "autopilot-roles").exists()
    assert not list((installed / ".claude" / "agents").glob("autopilot-*"))
    assert mine.read_text(encoding="utf-8") == "мой агент"
    assert (other_skill / "SKILL.md").exists()
    # настройки владельца остались, служебные файлы — нет
    assert (installed / ".autopilot-kit" / "profile.toml").exists()
    assert not (installed / ".autopilot-kit" / "upstream.lock.json").exists()
    assert not (installed / ".autopilot-kit" / "bin").exists()
    assert not (installed / ".autopilot-kit" / "kit_path").exists()
    assert not (installed / ".claude" / "skills" / "autopilot-init").exists()


def test_modified_files_are_kept(installed):
    target = upstream.default_targets()[0]
    (target / "SKILL.md").write_text("моя правка", encoding="utf-8")
    skill = installed / ".claude" / "skills" / "autopilot-roles" / "SKILL.md"
    skill.write_text("моя правка навыка", encoding="utf-8")
    report = "\n".join(uninstall.uninstall())
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "моя правка"
    assert "SKILL.md" in report and skill.exists()
    assert not (target / "phases").exists()


def test_user_agent_restored_from_backup(home):
    agents = render.claude_agents_dir()
    agents.mkdir(parents=True)
    original = "---\nname: autopilot-executor\n---\nмой собственный агент\n"
    (agents / "autopilot-executor.md").write_text(original, encoding="utf-8")
    models = profile.load_models()
    resolved = profile.resolve(profile.preset_profile("quality"), "claude", models)
    render.write_claude_agents(resolved, agents)  # копия оригинала
    render.write_claude_agents(profile.resolve(profile.preset_profile("economy"), "claude", models), agents)  # копия версии kit

    uninstall.uninstall()
    assert (agents / "autopilot-executor.md").read_text(encoding="utf-8") == original
    assert not (agents / "autopilot-reviewer-spec.md").exists()
    assert not [p for p in agents.iterdir() if "kit" in p.read_text(encoding="utf-8")]


def test_without_lock_autopilot_is_untouched(home):
    target = upstream.default_targets()[0]
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("не от kit", encoding="utf-8")
    uninstall.uninstall()
    assert (target / "SKILL.md").exists()


def test_confirmation_can_cancel(installed, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _: "n")
    assert uninstall.cmd_uninstall() == 1
    assert upstream.default_targets()[0].exists()
