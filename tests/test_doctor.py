import json

import pytest

from kit import commands, doctor, upstream


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(path))
    for name in doctor.API_KEYS:
        monkeypatch.delenv(name, raising=False)
    return path


def statuses(rows):
    return {name: status for name, status, _ in rows}


def test_empty_home_fails_install_checks(home, capsys):
    rows = statuses(doctor.collect())
    assert rows["Autopilot установлен, хеши"] == doctor.FAIL
    assert rows["Навыки kit установлены"] == doctor.FAIL
    assert rows["resolved.json"] == doctor.FAIL
    assert rows["Агенты autopilot-*"] == doctor.FAIL
    assert doctor.cmd_doctor() == 1
    assert "FAIL" in capsys.readouterr().out


def test_all_ok_after_install(home, remote, tmp_path):
    pin = tmp_path / "upstream.pin"
    pin.write_text(remote["first"] + "\n", encoding="utf-8")
    assert commands.cmd_install(remote["url"], pin) == 0
    # свои навыки в репозитории kit настоящие: install копирует skills/ из репозитория
    rows = statuses(doctor.collect())
    for key in ("Python ≥ 3.11", "git", "Autopilot установлен, хеши", "Навыки kit установлены", "resolved.json", "Агенты autopilot-*"):
        assert rows[key] == doctor.OK, key
    (upstream.default_targets()[0] / "SKILL.md").write_text("edit", encoding="utf-8")
    assert doctor.check_autopilot()[0] == doctor.FAIL


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
def test_api_key_in_environment_fails(name):
    rows = doctor.check_api_keys({name: "sk-x"})
    assert [s for _, s, _ in rows].count(doctor.FAIL) == 1
    assert any("риск оплаты" in m for _, s, m in rows if s == doctor.FAIL)
    assert all(s == doctor.OK for _, s, _ in doctor.check_api_keys({}))


def test_codex_login_variants():
    which = lambda _name: "codex"
    assert doctor.check_codex_login(lambda a: (0, "Logged in using ChatGPT"), which)[0] == doctor.OK
    assert doctor.check_codex_login(lambda a: (0, "Logged in using an API key"), which)[0] == doctor.FAIL
    assert doctor.check_codex_login(lambda a: (-1, ""), which)[0] == doctor.WARN
    assert doctor.check_codex_login(lambda a: (0, ""), lambda _n: None) is None


def test_claude_login_is_only_a_warning():
    which = lambda _name: "claude"
    assert doctor.check_claude_login(lambda a: (0, json.dumps({"loggedIn": True})), which)[0] == doctor.OK
    assert doctor.check_claude_login(lambda a: (1, json.dumps({"loggedIn": False})), which)[0] == doctor.WARN
    assert doctor.check_claude_login(lambda a: (1, "boom"), which)[0] == doctor.WARN
    assert doctor.check_claude_login(lambda a: (0, ""), lambda _n: None)[0] == doctor.WARN
