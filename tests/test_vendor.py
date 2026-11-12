"""Копия оригинального Autopilot внутри репозитория kit (D56): целостность, запись, установка без сети."""
import json
import subprocess
from pathlib import Path

import pytest

from kit import commands, upstream

KIT_ROOT = Path(__file__).resolve().parent.parent


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def fake_clone(tmp_path):
    """Клон «оригинала»: skills/autopilot + LICENSE, один коммит. Возвращает (корень, полный хеш)."""
    root = tmp_path / "clone"
    skill = root / "skills" / "autopilot"
    (skill / "phases").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: autopilot\n---\nтекст\n", encoding="utf-8")
    (skill / "phases" / "a.md").write_text("фаза\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026 Автор\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "-m", "v")
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return root, sha


def test_vendor_write_and_read_back(tmp_path):
    clone, sha = fake_clone(tmp_path)
    vendor = tmp_path / "vendor"
    upstream.vendor_write(clone / "skills" / "autopilot", sha, "https://example.test/x.git", root=vendor)
    assert (vendor / "autopilot" / "SKILL.md").is_file() and "Автор" in (vendor / "LICENSE").read_text(encoding="utf-8")
    manifest = json.loads((vendor / "UPSTREAM.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == sha and set(manifest["files"]) == {"SKILL.md", "phases/a.md"}
    src, commit = upstream.vendored(sha[:12], root=vendor)
    assert commit == sha and src == vendor / "autopilot"


def test_vendored_is_none_without_copy_or_for_other_commit(tmp_path):
    assert upstream.vendored("abc123", root=tmp_path / "нет") is None
    clone, sha = fake_clone(tmp_path)
    vendor = tmp_path / "vendor"
    upstream.vendor_write(clone / "skills" / "autopilot", sha, root=vendor)
    assert upstream.vendored("0000000", root=vendor) is None


def test_tampered_copy_is_refused(tmp_path):
    clone, sha = fake_clone(tmp_path)
    vendor = tmp_path / "vendor"
    upstream.vendor_write(clone / "skills" / "autopilot", sha, root=vendor)
    (vendor / "autopilot" / "SKILL.md").write_text("правка руками\n", encoding="utf-8")
    with pytest.raises(upstream.VendorError):
        upstream.vendored(sha, root=vendor)


def test_shipped_vendor_copy_matches_pin_and_manifest():
    """Репозиторий всегда несёт ровно ту версию оригинала, что закреплена в upstream.pin, и без изменений."""
    pin = commands.read_pin()
    found = upstream.vendored(pin)
    assert found is not None, "vendor/ не содержит закреплённый коммит: python -m kit vendor"
    assert (found[0] / "SKILL.md").is_file() and (KIT_ROOT / "vendor" / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_install_uses_vendor_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "home"))

    def no_network(*args, **kwargs):
        raise AssertionError("установка из vendor не должна ходить в сеть")

    monkeypatch.setattr(upstream, "fetch", no_network)
    assert commands.cmd_install() == 0
    installed = tmp_path / "home" / ".claude" / "skills" / "autopilot" / "SKILL.md"
    assert installed.read_bytes() == (KIT_ROOT / "vendor" / "autopilot" / "SKILL.md").read_bytes()
    assert (KIT_ROOT / "vendor" / "autopilot" / "SKILL.md").is_file()  # установка не удалила копию
