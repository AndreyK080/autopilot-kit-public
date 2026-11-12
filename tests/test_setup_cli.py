import json

import pytest

from kit import __main__ as cli
from kit import profile, setup_cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(path))
    return path


def test_parse_role():
    assert setup_cli.parse_role("executor=balanced:medium") == ("executor", ("balanced", "medium"))
    for bad in ("executor", "executor=balanced", "janitor=fast:low", "executor=huge:low", "executor=fast:turbo"):
        with pytest.raises(ValueError):
            setup_cli.parse_role(bad)


def test_set_preset_writes_profile_resolved_and_agents(home, capsys):
    assert setup_cli.cmd_profile_set("economy", []) == 0
    assert profile.load() == profile.preset_profile("economy")
    resolved = json.loads((home / ".autopilot-kit" / "resolved.json").read_text(encoding="utf-8"))
    assert resolved["claude"]["reviewer-spec"] == {"model": "sonnet", "effort": "high"}
    agent = (home / ".claude" / "agents" / "autopilot-reviewer-spec.md").read_text(encoding="utf-8")
    assert "model: sonnet" in agent and "effort: high" in agent
    assert "economy" in capsys.readouterr().out


def test_set_role_override_keeps_current_profile(home):
    setup_cli.cmd_profile_set("economy", [])
    assert setup_cli.cmd_profile_set(None, ["executor=fast:low"]) == 0
    loaded = profile.load()
    assert loaded.roles["executor"] == ("fast", "low")
    assert loaded.roles["final-reviewer"] == ("strong", "high")  # из economy, не из quality
    agent = (home / ".claude" / "agents" / "autopilot-executor.md").read_text(encoding="utf-8")
    assert "model: haiku" in agent and "effort: low" in agent


def test_set_second_write_makes_backup(home):
    setup_cli.cmd_profile_set("economy", [])
    setup_cli.cmd_profile_set("quality", [])
    assert list((home / ".autopilot-kit").glob("profile.toml.bak-*"))
    assert list((home / ".claude" / "agents").glob("autopilot-reviewer-spec.md.bak-*"))


def test_dry_run_and_errors_write_nothing(home, capsys):
    assert setup_cli.cmd_profile_set("economy", [], dry_run=True) == 0
    assert not (home / ".autopilot-kit").exists()
    assert "dry-run" in capsys.readouterr().out
    assert setup_cli.cmd_profile_set(None, ["janitor=fast:low"]) == 2
    assert not (home / ".autopilot-kit").exists()


def test_cli_entry(home):
    assert cli.main(["profile", "set", "--preset", "quality", "--role", "executor=strong:high"]) == 0
    assert profile.load().roles["executor"] == ("strong", "high")
