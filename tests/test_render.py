import json
import warnings
from pathlib import Path

import pytest

from kit import profile, render

GOLDEN = Path(__file__).parent / "golden"


def golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def resolved(vendor: str, preset: str = "quality"):
    return profile.resolve(profile.preset_profile(preset), vendor, profile.load_models())


@pytest.mark.parametrize("preset", ["quality", "economy"])
def test_claude_agents_match_golden(preset):
    files = render.render_claude_agents(resolved("claude", preset))
    assert sorted(files) == [
        "autopilot-executor.md",
        "autopilot-final-reviewer.md",
        "autopilot-reviewer-craft.md",
        "autopilot-reviewer-spec.md",
    ]
    for name, text in files.items():
        assert text == golden(f"claude-{preset}/{name}")


def test_reviewers_are_read_only_executor_is_not():
    files = render.render_claude_agents(resolved("claude"))
    assert "tools: Read, Grep, Glob, Bash" in files["autopilot-reviewer-spec.md"]
    assert "tools:" not in files["autopilot-executor.md"]
    assert "Edit" not in files["autopilot-final-reviewer.md"]


def test_codex_agents_match_golden():
    files = render.render_codex(resolved("codex"))
    assert sorted(files) == [
        "autopilot_executor.toml",
        "autopilot_final_reviewer.toml",
        "autopilot_reviewer_craft.toml",
        "autopilot_reviewer_spec.toml",
    ]
    for name, text in files.items():
        assert text == golden(f"codex-quality/{name}")


def test_codex_empty_when_unverified():
    with pytest.warns(UserWarning):
        assert render.render_codex({}) == {}


def test_resolved_json_and_models_copy(tmp_path):
    models = profile.load_models()
    path = tmp_path / "resolved.json"
    assert render.write_resolved(profile.preset_profile("quality"), models, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["claude"]["final-reviewer"] == {"model": "opus", "effort": "max"}
    assert data["codex"]["executor"]["model"] == models["codex"]["tiers"]["balanced"]
    assert not render.write_resolved(profile.preset_profile("quality"), models, path)

    skipped = {"claude": models["claude"], "codex": {"tiers": {}, "efforts": [], "unverified": True}}
    render.write_resolved(profile.preset_profile("quality"), skipped, path)
    assert list(json.loads(path.read_text(encoding="utf-8"))) == ["claude"]

    copy = tmp_path / "models.json"
    assert render.write_models_copy(path=copy)
    assert json.loads(copy.read_text(encoding="utf-8")) == models


def test_write_claude_agents_idempotent_with_backup_and_scope(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "mine.md").write_text("не трогать", encoding="utf-8")
    (agents / "autopilot-executor.md").write_text("старое", encoding="utf-8")

    changed = render.write_claude_agents(resolved("claude"), agents)
    assert len(changed) == 4
    assert (agents / "mine.md").read_text(encoding="utf-8") == "не трогать"
    assert len(list(agents.glob("autopilot-executor.md.bak-*"))) == 1

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert render.write_claude_agents(resolved("claude"), agents) == []
    assert len(list(agents.glob("*.bak-*"))) == 1
