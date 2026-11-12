import subprocess
from pathlib import Path

import pytest


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def commit_skill(work: Path, text: str, message: str) -> str:
    skill = work / "skills" / "autopilot"
    (skill / "phases").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(text, encoding="utf-8")
    (skill / "phases" / "one.md").write_text("phase " + text, encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-m", message)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """Локальный bare-репозиторий с двумя коммитами вместо GitHub."""
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    first = commit_skill(work, "v1", "first")
    second = commit_skill(work, "v2", "second")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return {"url": str(bare), "first": first, "second": second, "work": work, "bare": bare}


@pytest.fixture(autouse=True)
def no_dashboard_server(monkeypatch):
    """program.py в тестах не поднимает фоновый сервер дашборда (D25)."""
    monkeypatch.setenv("AUTOPILOT_KIT_NO_SERVE", "1")
