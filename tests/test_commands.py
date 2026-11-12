import builtins

import pytest

from kit import commands, upstream
from tests.conftest import commit_skill


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(path))
    return path


@pytest.fixture
def pin(tmp_path, remote):
    path = tmp_path / "upstream.pin"
    path.write_text(remote["first"] + "\n", encoding="utf-8")
    return path


@pytest.fixture
def green_seams(monkeypatch):
    """Поддельное ядро из conftest — не настоящий Autopilot: швы проверяются отдельно (test_seams.py)."""
    monkeypatch.setattr(commands.seams, "check", lambda _src: [{"seam": "шов", "ok": True, "detail": ""}])


def test_install_status_install_again(remote, home, pin, capsys):
    assert commands.cmd_install(remote["url"], pin) == 0
    targets = upstream.default_targets()
    assert all((t / "SKILL.md").read_text(encoding="utf-8") == "v1" for t in targets)
    assert upstream.read_lock()["commit"] == remote["first"]
    assert (home / ".claude" / "agents" / "autopilot-executor.md").exists()
    assert (home / ".autopilot-kit" / "resolved.json").exists()
    assert (home / ".autopilot-kit" / "models.json").exists()
    assert (home / ".autopilot-kit" / "bin" / "gate.py").exists()
    assert (home / ".autopilot-kit" / "bin" / "program.py").exists()
    assert (home / ".autopilot-kit" / "kit_path").read_text(encoding="utf-8").strip() == commands.KIT_ROOT.as_posix()
    assert (commands.KIT_ROOT / "skills" / "autopilot-init" / "SKILL.md").exists()

    capsys.readouterr()
    assert commands.cmd_status(remote["url"]) == 0
    out = capsys.readouterr().out
    assert out.count("OK:") == 2 and "есть обновление" in out

    assert commands.cmd_install(remote["url"], pin) == 0
    assert capsys.readouterr().out.count("без изменений") == 2


def test_install_refuses_local_changes(remote, home, pin, capsys):
    commands.cmd_install(remote["url"], pin)
    target = upstream.default_targets()[1]
    (target / "SKILL.md").write_text("mine", encoding="utf-8")
    pin.write_text(remote["second"] + "\n", encoding="utf-8")
    capsys.readouterr()
    assert commands.cmd_install(remote["url"], pin) == 1
    assert "LOCAL_CHANGES" in capsys.readouterr().out
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "mine"
    assert commands.cmd_status(remote["url"]) == 1


def test_update_shows_changes_and_confirms(remote, home, pin, monkeypatch, capsys, green_seams):
    commands.cmd_install(remote["url"], pin)
    capsys.readouterr()

    monkeypatch.setattr(builtins, "input", lambda _: "n")
    assert commands.cmd_update(remote["url"], pin) == 1
    out = capsys.readouterr().out
    assert "second" in out and "SKILL.md" in out and "Отменено" in out
    assert (upstream.default_targets()[0] / "SKILL.md").read_text(encoding="utf-8") == "v1"

    monkeypatch.setattr(builtins, "input", lambda _: "y")
    assert commands.cmd_update(remote["url"], pin) == 0
    assert all((t / "SKILL.md").read_text(encoding="utf-8") == "v2" for t in upstream.default_targets())
    assert upstream.read_lock()["commit"] == remote["second"]
    assert pin.read_text(encoding="utf-8").strip() == remote["second"]
    assert commands.cmd_update(remote["url"], pin, assume_yes=True) == 0
    assert "Уже актуально" in capsys.readouterr().out


def test_update_yes_flag_and_new_commit(remote, home, pin, green_seams):
    commands.cmd_install(remote["url"], pin)
    commit_skill(remote["work"], "v3", "third")
    import subprocess
    subprocess.run(["git", "push", "-q", str(remote["bare"]), "HEAD:main"], cwd=remote["work"], check=True)
    assert commands.cmd_update(remote["url"], pin, assume_yes=True) == 0
    assert (upstream.default_targets()[0] / "SKILL.md").read_text(encoding="utf-8") == "v3"


def test_rollback_by_pin_and_install(remote, home, pin, monkeypatch, green_seams):
    commands.cmd_install(remote["url"], pin)
    monkeypatch.setattr(builtins, "input", lambda _: "y")
    commands.cmd_update(remote["url"], pin)
    assert (upstream.default_targets()[0] / "SKILL.md").read_text(encoding="utf-8") == "v2"
    pin.write_text(remote["first"] + "\n", encoding="utf-8")
    assert commands.cmd_install(remote["url"], pin) == 0
    assert all((t / "SKILL.md").read_text(encoding="utf-8") == "v1" for t in upstream.default_targets())
    assert upstream.read_lock()["commit"] == remote["first"]


def test_update_without_install(remote, home, pin):
    assert commands.cmd_update(remote["url"], pin, assume_yes=True) == 1


def test_update_refuses_red_seams(remote, home, pin, capsys):
    # D20: поддельное ядро без файлов Autopilot — швы красные, прод не меняется даже с --yes
    commands.cmd_install(remote["url"], pin)
    capsys.readouterr()
    assert commands.cmd_update(remote["url"], pin, assume_yes=True) == 1
    out = capsys.readouterr().out
    assert "Швы не пройдены" in out and "FAIL" in out
    assert (upstream.default_targets()[0] / "SKILL.md").read_text(encoding="utf-8") == "v1"
    assert upstream.read_lock()["commit"] == remote["first"]
    assert pin.read_text(encoding="utf-8").strip() == remote["first"]


def push_commit(remote, path, text, message):
    import subprocess
    from tests.conftest import git
    (remote["work"] / path).parent.mkdir(parents=True, exist_ok=True)
    (remote["work"] / path).write_text(text, encoding="utf-8")
    git(remote["work"], "add", "-A")
    git(remote["work"], "commit", "-m", message)
    subprocess.run(["git", "push", "-q", str(remote["bare"]), "HEAD:main"], cwd=remote["work"], check=True)


def test_check_update_three_cases(remote, home, pin, capsys):
    assert commands.cmd_check_update(remote["url"]) == 1  # нет lock
    commands.cmd_install(remote["url"], pin)  # прод на first, HEAD — second
    capsys.readouterr()
    assert commands.cmd_check_update(remote["url"]) == 10
    out = capsys.readouterr().out
    assert "Есть новая версия" in out and "second" in out and "SKILL.md" in out and "kit trial" in out
    pin.write_text(remote["second"] + "\n", encoding="utf-8")
    commands.cmd_install(remote["url"], pin)
    capsys.readouterr()
    assert commands.cmd_check_update(remote["url"]) == 0
    push_commit(remote, "skills/other/SKILL.md", "чужой навык", "other skill")  # HEAD сдвинулся не из-за Autopilot
    assert commands.cmd_check_update(remote["url"]) == 0
    assert "skills/autopilot не изменился" in capsys.readouterr().out


def test_trial_installs_candidate_in_dev_and_leaves_prod(remote, home, pin, capsys, green_seams):
    commands.cmd_install(remote["url"], pin)
    (home / ".autopilot-kit" / "profile.toml").write_text('[roles.executor]\ntier = "fast"\neffort = "low"\n',
                                                         encoding="utf-8")
    prod_lock = upstream.read_lock()
    capsys.readouterr()
    assert commands.cmd_trial(remote["url"]) == 0
    dev = home / ".autopilot-kit" / "trial" / "home"
    assert (dev / ".claude" / "skills" / "autopilot" / "SKILL.md").read_text(encoding="utf-8") == "v2"
    assert (dev / ".autopilot-kit" / "profile.toml").read_text(encoding="utf-8").startswith("[roles.executor]")
    assert (dev / ".claude" / "agents" / "autopilot-executor.md").exists()
    assert upstream.read_lock() == prod_lock  # прод не тронут
    assert (upstream.default_targets()[0] / "SKILL.md").read_text(encoding="utf-8") == "v1"
    report = (home / ".autopilot-kit" / "trial" / "report.md").read_text(encoding="utf-8")
    assert "кандидат: " + remote["second"][:12] in report and "- SKILL.md" in report and "швы зелёные" in report


def test_trial_red_seams_exit_1(remote, home, pin):
    commands.cmd_install(remote["url"], pin)
    assert commands.cmd_trial(remote["url"]) == 1
    assert "в прод не ставить" in (home / ".autopilot-kit" / "trial" / "report.md").read_text(encoding="utf-8")


def test_own_skills_installed_with_backup(home, tmp_path):
    skills = tmp_path / "skills"
    (skills / "autopilot-roles").mkdir(parents=True)
    (skills / "autopilot-roles" / "SKILL.md").write_text("ours", encoding="utf-8")
    assert len(commands.install_own_skills(skills)) == 2
    assert commands.install_own_skills(skills) == []
    target = upstream.default_targets()[0].parent / "autopilot-roles"
    (target / "SKILL.md").write_text("edited", encoding="utf-8")
    commands.install_own_skills(skills)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "ours"
    assert not list(target.parent.glob("*.bak-*"))
    assert list((home / ".autopilot-kit" / "backups").glob("claude-autopilot-roles.bak-*"))
    assert commands.install_own_skills(tmp_path / "missing") == []
