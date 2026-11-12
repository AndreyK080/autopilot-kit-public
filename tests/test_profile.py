import pytest

from kit import profile


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(path))
    return path


def write_toml(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_defaults_to_quality(home):
    loaded = profile.load()
    assert loaded.preset == "quality"
    assert loaded.roles["executor"] == ("balanced", "medium")
    assert loaded.roles["final-reviewer"] == ("strong", "max")


def test_global_and_project_merge_by_role(home, tmp_path):
    write_toml(profile.global_profile_path(), 'preset = "economy"\n[roles.executor]\ntier = "fast"\neffort = "low"\n')
    project = tmp_path / "proj"
    write_toml(
        profile.project_profile_path(project),
        '[roles.reviewer-craft]\ntier = "strong"\neffort = "xhigh"\n',
    )
    loaded = profile.load(project)
    assert loaded.preset == "economy"
    assert loaded.roles["executor"] == ("fast", "low")  # из глобального
    assert loaded.roles["reviewer-spec"] == ("balanced", "high")  # из пресета economy
    assert loaded.roles["reviewer-craft"] == ("strong", "xhigh")  # из проектного


def test_resolve_both_vendors():
    models = profile.load_models()
    p = profile.preset_profile("quality")
    claude = profile.resolve(p, "claude", models)
    assert claude["executor"] == ("sonnet", "medium")
    assert claude["final-reviewer"] == ("opus", "max")
    codex = profile.resolve(p, "codex", models)
    assert codex["executor"] == (models["codex"]["tiers"]["balanced"], "medium")


def test_effort_downgraded_with_warning():
    models = {"codex": {"tiers": {"strong": "s", "balanced": "b", "fast": "f"}, "efforts": ["low", "medium", "high", "xhigh"]}}
    p = profile.preset_profile("quality")
    with pytest.warns(UserWarning, match="max"):
        resolved = profile.resolve(p, "codex", models)
    assert resolved["final-reviewer"] == ("s", "xhigh")
    assert resolved["executor"] == ("b", "medium")


def test_unknown_role_tier_effort_vendor(home):
    with pytest.raises(ValueError, match="роль"):
        write_toml(profile.global_profile_path(), '[roles.janitor]\ntier = "fast"\neffort = "low"\n')
        profile.load()
    write_toml(profile.global_profile_path(), '[roles.executor]\ntier = "huge"\neffort = "low"\n')
    with pytest.raises(ValueError, match="уровень"):
        profile.load()
    write_toml(profile.global_profile_path(), '[roles.executor]\ntier = "fast"\neffort = "turbo"\n')
    with pytest.raises(ValueError, match="усилие"):
        profile.load()
    with pytest.raises(ValueError, match="вендор"):
        profile.resolve(profile.preset_profile("quality"), "gemini", profile.load_models())
    with pytest.raises(ValueError, match="пресет"):
        profile.preset_profile("turbo")


def test_resolve_rejects_unverified_vendor():
    models = {"codex": {"tiers": {}, "efforts": [], "unverified": True}}
    with pytest.raises(ValueError, match="unverified"):
        profile.resolve(profile.preset_profile("quality"), "codex", models)


def test_write_roundtrip_and_backup(home, tmp_path):
    path = tmp_path / "p" / "profile.toml"
    original = profile.preset_profile("economy")
    profile.write(original, path)
    write_toml(profile.global_profile_path(), path.read_text(encoding="utf-8"))
    assert profile.load() == original
    profile.write(original, path)  # то же содержимое — без .bak
    assert not list(path.parent.glob("*.bak-*"))
    profile.write(profile.preset_profile("quality"), path)
    assert len(list(path.parent.glob("profile.toml.bak-*"))) == 1
