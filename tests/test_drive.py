"""Привод «Claude Desktop Gate» (D48, D49): host-маркер, идентичность оркестратора, сторож, модели, лимиты."""
import io
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from kit import gate, program
from tests.conftest import git


GATE_ENV = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop-3p"}
PROXY_ENV = {"CLAUDECODE": "1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:8045"}  # подписка со своим прокси — НЕ гейтвей
CLAUDE_ENV = {"CLAUDECODE": "1"}
CODEX_ENV = {"CODEX_THREAD_ID": "thread-1"}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Ни настоящего домашнего каталога, ни окружения приложения: detection-тесты детерминированы."""
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "kit-home"))
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


# ── T19.2/T19.8: определение привода и host-маркер ──────────────────────────

@pytest.mark.parametrize("env, drive", [
    ({}, "unknown"),
    (CLAUDE_ENV, "claude"),
    (PROXY_ENV, "claude"),                                   # T19.8: BASE_URL — не признак (локальный прокси подписки)
    (GATE_ENV, "claude-gate"),
    ({**GATE_ENV, "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721/claude-desktop"}, "claude-gate"),
    ({"CLAUDE_CODE_ENTRYPOINT": "claude-desktop-3p"}, "claude-gate"),
    (CODEX_ENV, "codex"),
    ({**CODEX_ENV, "ANTHROPIC_BASE_URL": "https://gw.example"}, "codex"),
])
def test_drive_detection(env, drive):
    assert gate.drive_of(env) == drive
    assert program.drive_id(env) == drive


def test_gate_log_host_is_claude_gate(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".autopilot-kit").mkdir(parents=True)
    (project / ".autopilot-kit" / "project.toml").write_text("[gate]\ncommands = []\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop-3p")
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert gate.main(["--hook", "claude-stop", "--project", str(project)]) == 0
    entry = json.loads((project / ".autopilot-kit" / "gate_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["host"] == "claude-gate" and entry["mode"] == "hook" and entry["result"] == "pass"


def test_gate_log_host_stays_claude_without_marker(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".autopilot-kit").mkdir(parents=True)
    (project / ".autopilot-kit" / "project.toml").write_text("[gate]\ncommands = []\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    for name in ("CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert gate.main(["--hook", "claude-stop", "--project", str(project)]) == 0
    entry = json.loads((project / ".autopilot-kit" / "gate_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["host"] == "claude"


def test_machine_id_carries_drive(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop-3p")
    parts = program.machine_id().split("|")
    assert parts[0] == platform.node() and parts[2] == "claude-gate"


def test_machines_compatible_legacy_and_drives():
    current = f"{platform.node()}|C:\\Users\\A|claude-gate"
    assert program.machines_compatible(None, current)                      # оркестратор не регистрировался
    assert program.machines_compatible(current, current)
    assert program.machines_compatible(f"{platform.node()}|C:\\Users\\A", current)  # запись до D48 — без привода
    assert program.machines_compatible(f"{platform.node()}|C:\\Users\\A|unknown", current)
    assert not program.machines_compatible(f"{platform.node()}|C:\\Users\\A|claude", current)  # другой профиль
    assert not program.machines_compatible(f"other-pc|C:\\Users\\A|claude-gate", current)      # другая машина
    assert not program.machines_compatible(f"{platform.node()}|C:\\Users\\B", current)         # другой дом


@pytest.fixture
def gate_env(monkeypatch, tmp_path):
    """Окружение привода claude-gate и домашний каталог kit в tmp_path."""
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop-3p")
    for name in ("CODEX_THREAD_ID",):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def proj(tmp_path, gate_env):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "f.txt").write_text("x", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    (root / ".autopilot-kit").mkdir()
    (root / ".autopilot-kit" / "project.toml").write_text('[gate]\ncommands = []\n', encoding="utf-8")
    program.cmd_init(root, "демо", None, "full")
    program.cmd_stage_add(root, "M1", "Ядро", "M1: работа", "M1", [])
    return root


def _machine_prefix() -> str:
    return "|".join(program.machine_id().split("|")[:2])


def _set_machine(root, drive: str) -> None:
    path = root / ".autopilot" / "program.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["orchestratorMachine"] = f"{_machine_prefix()}|{drive}" if drive else _machine_prefix()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_orchestrator_records_drive(proj):
    program.cmd_orchestrator(proj, "local_orch")
    data = program.load(proj)
    assert data["orchestratorMachine"].split("|")[2] == "claude-gate"


def test_watch_skips_program_of_another_profile(proj):
    program.cmd_orchestrator(proj, "local_orch")
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    _set_machine(proj, "claude")  # оркестратор записан подписочным профилем той же машины
    result = program.watch_program(proj, {})
    assert result["foreign"] is True and result["action"] == "none"
    assert "другого профиля" in result["note"]


def test_watch_serves_program_of_own_profile_and_legacy_records(proj):
    program.cmd_orchestrator(proj, "local_orch")
    result = program.watch_program(proj, {})
    assert not result.get("foreign")
    _set_machine(proj, "unknown")  # привод не определён — не повод считать программу чужой
    assert not program.watch_program(proj, {}).get("foreign")
    _set_machine(proj, "")  # запись до D48 — без привода
    assert not program.watch_program(proj, {}).get("foreign")


def test_watch_prompt_tells_to_skip_foreign_records():
    text = program.watch_prompt()
    assert "foreign: true" in text and "другого профиля приложения" in text


def test_roles_skill_detects_the_gate_drive():
    from kit import commands
    text = (commands.KIT_ROOT / "skills" / "autopilot-roles" / "SKILL.md").read_text(encoding="utf-8")
    assert "claude-desktop-3p" in text and "'claude-gate'" in text
    assert "Claude Desktop Gate" in text


# ── T19.3: вендор claude-gate и пресет desktop-gate ─────────────────────────

def test_models_table_has_gate_vendor():
    from kit import profile
    block = profile.load_models()["claude-gate"]
    assert block["tiers"] == {"strong": "opus", "balanced": "sonnet", "fast": "haiku"}
    assert block["gateway"] == {"opus": "qwen3.8-max", "sonnet": "qwen3.8-flash", "haiku": "qwen3.6-flash"}


def test_desktop_gate_puts_executor_on_strong_model():
    from kit import profile
    preset = profile.preset_profile("desktop-gate")
    assert preset.roles["executor"] == ("strong", "medium")
    resolved = profile.resolve(preset, "claude-gate", profile.load_models())
    assert resolved["executor"] == ("opus", "medium")          # гейтвей отображает opus в qwen3.8-max
    assert resolved["final-reviewer"] == ("opus", "max")
    quality = profile.resolve(profile.preset_profile("quality"), "claude-gate", profile.load_models())
    assert quality["executor"] == ("sonnet", "medium")          # пресет quality дал бы flash-модель


def test_resolved_json_includes_gate_vendor(tmp_path, monkeypatch):
    from kit import profile, render
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "home"))
    render.write_resolved(profile.preset_profile("desktop-gate"), profile.load_models())
    data = json.loads(render.resolved_json_path().read_text(encoding="utf-8"))
    assert data["claude-gate"]["executor"] == {"model": "opus", "effort": "medium"}


def test_setup_table_shows_gate_vendor():
    from kit import profile, setup_cli
    table = setup_cli.render_table(profile.preset_profile("desktop-gate"), profile.load_models())
    assert "claude-gate: opus / medium" in table


def test_setup_skill_offers_desktop_gate_preset():
    from kit import commands
    text = (commands.KIT_ROOT / "skills" / "autopilot-setup" / "SKILL.md").read_text(encoding="utf-8")
    assert "Claude Desktop Gate" in text and "`desktop-gate`" in text


# ── T19.4: §5a при plan.status != ok — явно ─────────────────────────────────

def test_limits_not_applicable_is_explicit():
    result = program.cmd_limits({"plan": {"status": "not_applicable"}}, "start")
    assert result["decision"] == "go" and result["limits"] == "not_applicable"
    assert "гейтвей" in result["note"]
    broken = program.cmd_limits({"plan": {"status": "unavailable"}}, "start")
    assert broken["decision"] == "go" and "limits" not in broken  # «не прочитаны» — не то же, что «не применяются»


def test_program_skill_skips_limits_section_on_the_gate_drive():
    from kit import commands
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Limits that do not apply (D48).**", 'answers `plan.status: "not_applicable"`',
                   "**skip this section entirely**", "Лимиты подписки не измеряются (трафик через гейтвей",
                   "not as a limit pause"):
        assert phrase in text, phrase


def test_program_skill_registers_watchdog_per_profile():
    from kit import commands
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    assert "per app profile" in text and "foreign: true" in text


# ── T19.5: дрейф инструментов (PushNotification, ToolSearch, tabs) ──────────

def test_program_texts_offer_tool_fallbacks():
    rules = program.STAGE_RULES
    assert "preview_list" in rules and "нет такого инструмента в этом билде" in rules  # tabs_context/tabs_select
    assert "mcp__ccd_turn__wrap_up" in rules and "PushNotification" in rules            # уведомление
    assert "нет ToolSearch" in rules or "нет `ToolSearch`" in rules
    for text in (program.watch_prompt(),):
        assert "PushNotification" in text and "mcp__ccd_turn__wrap_up" in text
        assert "нет ToolSearch в этом билде" in text
    assert "D48" in gate.PANE_REMINDER and "ToolSearch" in gate.PANE_REMINDER


def test_wake_and_pool_prompts_offer_tool_fallbacks(tmp_path, monkeypatch, proj):
    program.cmd_start(proj, "M1", adopt=False)
    program.cmd_bind(proj, "M1", "local_stage")
    wake = program.cmd_wake_prompt(proj)
    assert "PushNotification" in wake and "mcp__ccd_turn__wrap_up" in wake
    assert "нет ToolSearch в этом билде" in wake
    pool = program.pool_prompt(program.load(proj))
    assert "нет его в билде — уже загружен" in pool


def test_program_skill_defines_the_tool_drift_rule():
    from kit import commands
    text = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("**Tool drift (D48).**", "has no `PushNotification`, no `tabs_context`/`tabs_select` and no `ToolSearch`",
                   "`mcp__ccd_turn__wrap_up`", "`mcp__Claude_Browser__preview_list`",
                   "Try the named tool first; substitute only after the build refused it."):
        assert phrase in text, phrase


# ── T19.6: машинно-независимый путь хука Stop ───────────────────────────────

PORTABLE_HOOK = 'python "$HOME/.autopilot-kit/bin/gate.py" --hook claude-stop'


@pytest.fixture
def kit_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".autopilot-kit" / "bin").mkdir(parents=True)
    (home / ".autopilot-kit" / "bin" / "gate.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    return home


def _project_with_hook(tmp_path, hook: str):
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": hook, "timeout": 1200}]}]}}
    (root / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return root


def _hook_row(root):
    import subprocess
    from kit import projects
    which = lambda _name: "C:/Python312/python.exe"
    run = lambda args: subprocess.CompletedProcess(args, 0, stdout="kit-ok\n", stderr="")
    return next(r for r in projects.check_project(root, which, run) if r[0].endswith("хук гейта"))


def test_templates_write_machine_independent_hook(kit_home, tmp_path):
    from kit import project
    target = tmp_path / "proj"
    project.init_project("python-cli", target)
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert command == PORTABLE_HOOK and "<~>" not in command
    # Codex и Antigravity остаются на абсолютном пути: оболочка их хуков не известна
    codex = json.loads((target / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert kit_home.as_posix() in codex["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_doctor_accepts_portable_hook_and_relocate_keeps_it(kit_home, tmp_path):
    from kit import projects
    root = _project_with_hook(tmp_path, PORTABLE_HOOK)
    name, status, message = _hook_row(root)
    assert status == projects.OK and "$HOME" in message and "машинно-независимый" in message
    before = (root / ".claude" / "settings.json").read_bytes()
    projects.relocate([root])
    assert (root / ".claude" / "settings.json").read_bytes() == before  # $HOME-форма не переписывается


def test_doctor_flags_foreign_absolute_hook_with_home_hint(kit_home, tmp_path):
    from kit import projects
    root = _project_with_hook(tmp_path, 'python "C:/Users/olduser/.autopilot-kit/bin/gate.py" --hook claude-stop')
    _name, status, message = _hook_row(root)
    assert status == projects.FAIL
    assert "$HOME/.autopilot-kit/bin/gate.py" in message and "D48" in message  # общий проект: не relocate, а $HOME-форма


# ── T19.7: doctor видит провайдер окружения ─────────────────────────────────

def _providers(rows):
    return {name: (status, message) for name, status, message in rows}


def test_doctor_sees_the_gateway_drive():
    from kit import doctor
    rows = _providers(doctor.check_api_keys({
        "ANTHROPIC_AUTH_TOKEN": "secret-token",
        "ANTHROPIC_BASE_URL": "https://gw.example.test/compatible/v1",
        "CLAUDE_CODE_ENTRYPOINT": "claude-desktop-3p",
    }))
    status, message = rows["Провайдер Anthropic"]
    assert status == doctor.OK and "Claude Desktop Gate" in message and "gw.example.test" in message
    assert "secret-token" not in message  # значение токена в отчёт не попадает


def test_doctor_provider_combinations():
    from kit import doctor
    assert _providers(doctor.check_api_keys({"ANTHROPIC_AUTH_TOKEN": "t"}))["Провайдер Anthropic"][0] == doctor.FAIL
    anthropic = {"ANTHROPIC_AUTH_TOKEN": "t", "ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
    assert _providers(doctor.check_api_keys(anthropic))["Провайдер Anthropic"][0] == doctor.FAIL
    assert _providers(doctor.check_api_keys({"ANTHROPIC_BASE_URL": "https://gw.example"}))["Провайдер Anthropic"][0] == doctor.WARN
    assert _providers(doctor.check_api_keys({}))["Провайдер Anthropic"][0] == doctor.OK
    rows = doctor.check_api_keys({"ANTHROPIC_API_KEY": "sk-x", "ANTHROPIC_AUTH_TOKEN": "t",
                                  "ANTHROPIC_BASE_URL": "https://gw.example"})
    assert _providers(rows)["ANTHROPIC_API_KEY не задан"][0] == doctor.FAIL  # API-ключ запрещён и при гейтвее (D3)


def test_doctor_reads_provider_from_claude_settings(tmp_path, monkeypatch):
    from kit import doctor
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"env": {"ANTHROPIC_BASE_URL": "https://gw.example/v1", "ANTHROPIC_AUTH_TOKEN": "tok"}}), encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    env = doctor.claude_settings_env()
    assert env["ANTHROPIC_AUTH_TOKEN"] == "tok"
    status, message = _providers(doctor.check_api_keys(env))["Провайдер Anthropic"]
    assert status == doctor.OK and "gw.example" in message
    (home / ".claude" / "settings.json").write_text("{oops", encoding="utf-8")
    assert doctor.claude_settings_env() == {}  # битые настройки — не ошибка doctor


def test_doctor_shows_gateway_from_settings_not_local_proxy(tmp_path, monkeypatch):
    # T19.8: в окружении сессии — локальный прокси приложения, настоящий адрес гейтвея — в settings.json
    from kit import doctor
    home = tmp_path / "home2"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"env": {"ANTHROPIC_BASE_URL": "https://real-gw.example/v1", "ANTHROPIC_AUTH_TOKEN": "tok"}}), encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:15721/claude-desktop")
    merged = {**os.environ, **doctor.claude_settings_env()}
    _status, message = _providers(doctor.check_api_keys(merged))["Провайдер Anthropic"]
    assert "real-gw.example" in message and "127.0.0.1" not in message


# ── T19.8 (D49): фиксация привода и авторитетное подтверждение ──────────────

def _write_profile(home, drive: str):
    (home / ".autopilot-kit").mkdir(parents=True, exist_ok=True)
    (home / ".autopilot-kit" / "profile.toml").write_text(f'preset = "quality"\ndrive = "{drive}"\n', encoding="utf-8")


def test_profile_pin_overrides_environment(tmp_path, monkeypatch):
    from kit import profile
    home = tmp_path / "pin-home"
    _write_profile(home, "claude-gate")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    assert profile.load().drive == "claude-gate"
    assert program.drive_id(CLAUDE_ENV) == "claude-gate"   # подписочное окружение, но фиксация сильнее
    assert gate.pinned_drive(None) == "claude-gate"
    _write_profile(home, "claude")
    assert program.drive_id(GATE_ENV) == "claude"          # фиксация сильнее и признака 3p
    assert profile.load().drive == "claude"


def test_project_pin_beats_profile_pin(tmp_path, monkeypatch):
    home = tmp_path / "pin-home2"
    _write_profile(home, "claude")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    root = tmp_path / "pinned-proj"
    (root / ".autopilot-kit").mkdir(parents=True)
    # drive — ключ верхнего уровня, до табличных секций (TOML)
    (root / ".autopilot-kit" / "project.toml").write_text('drive = "claude-gate"\n[gate]\ncommands = []\n', encoding="utf-8")
    assert program.drive_id(CLAUDE_ENV, root) == "claude-gate"
    assert gate.pinned_drive(root) == "claude-gate"
    assert program.drive_id(CLAUDE_ENV) == "claude"        # без проекта — профильная фиксация


def test_bad_drive_pin_is_ignored(tmp_path, monkeypatch):
    from kit import profile
    home = tmp_path / "pin-home3"
    (home / ".autopilot-kit").mkdir(parents=True)
    (home / ".autopilot-kit" / "profile.toml").write_text('preset = "quality"\ndrive = "gemini"\n', encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    with pytest.raises(ValueError):
        profile.load()
    assert program.drive_id(CLAUDE_ENV) == "claude"        # program.py не падает на чужом значении
    assert gate.pinned_drive(None) is None


def test_gate_log_host_follows_project_pin(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".autopilot-kit").mkdir(parents=True)
    (project / ".autopilot-kit" / "project.toml").write_text(
        'drive = "claude-gate"\n[gate]\ncommands = []\n', encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")                  # окружение подписки, фиксация проекта сильнее
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert gate.main(["--hook", "claude-stop", "--project", str(project)]) == 0
    entry = json.loads((project / ".autopilot-kit" / "gate_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["host"] == "claude-gate"


def test_proxy_in_base_url_does_not_flip_subscription_to_gate(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".autopilot-kit").mkdir(parents=True)
    (project / ".autopilot-kit" / "project.toml").write_text("[gate]\ncommands = []\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8045")  # свой прокси подписки (кейс 06.11)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert gate.main(["--hook", "claude-stop", "--project", str(project)]) == 0
    entry = json.loads((project / ".autopilot-kit" / "gate_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["host"] == "claude"


def test_limits_plan_ok_confirms_subscription_and_heals_identity(proj, monkeypatch):
    # окружение gate (fixture gate_env), оркестратор записан с приводом claude-gate — но plan.status ok авторитетен
    program.cmd_orchestrator(proj, "local_orch")
    assert program.load(proj)["orchestratorMachine"].endswith("|claude-gate")
    usage = {"plan": {"status": "ok", "plan": "pro", "windows": [
        {"label": "5-hour limit", "percentUsed": 10, "resetsAt": None}]}}
    result = program.cmd_limits(usage, "start", proj)
    assert result["decision"] == "go" and result["drive"] == "claude"
    data = program.load(proj)
    assert data["drive"] == "claude" and data["orchestratorMachine"].endswith("|claude")
    # сторож подписочного профиля больше не считает оркестратора чужим
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    assert not program.watch_program(proj, {}).get("foreign")


def test_limits_not_applicable_confirms_gate_drive(proj):
    program.cmd_orchestrator(proj, "local_orch")
    result = program.cmd_limits({"plan": {"status": "not_applicable"}}, "start", proj)
    assert result["limits"] == "not_applicable" and result["drive"] == "claude-gate"
    assert program.load(proj)["drive"] == "claude-gate"


def test_limits_unavailable_confirms_nothing(proj):
    program.cmd_orchestrator(proj, "local_orch")
    result = program.cmd_limits({"plan": {"status": "unavailable"}}, "start", proj)
    assert result["decision"] == "go" and "drive" not in result
    assert program.load(proj)["drive"] == "claude-gate"  # статус unavailable ничего не подтверждает — запись не тронута


def test_codex_synthetic_limits_confirm_nothing(proj):
    # `limits --codex` synthesizes plan со status ok и полем source — это не ответ get_usage, привод не подтверждает
    program.cmd_orchestrator(proj, "local_orch")
    usage = {"plan": {"status": "ok", "windows": [], "source": "rollout-2026-11-07.jsonl"}}
    result = program.cmd_limits(usage, "start", proj)
    assert result["decision"] == "go" and "drive" not in result
    assert program.load(proj)["drive"] == "claude-gate"  # запись оркестратора не испорчена


def test_heal_does_not_touch_another_machines_identity(proj):
    program.cmd_orchestrator(proj, "local_orch")
    path = proj / ".autopilot" / "program.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["orchestratorMachine"] = "other-pc|C:\\Other|claude-gate"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    program.cmd_limits({"plan": {"status": "ok", "windows": []}}, "start", proj)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["orchestratorMachine"] == "other-pc|C:\\Other|claude-gate"  # чужая идентичность не правится
    assert data["drive"] == "claude"


def test_orchestrator_usage_pins_confirmed_drive(proj):
    out = program.cmd_orchestrator(proj, "local_orch", {"plan": {"status": "ok"}})
    data = program.load(proj)
    assert data["drive"] == "claude" and data["orchestratorMachine"].endswith("|claude")
    assert "привод claude" in out
    program.cmd_orchestrator(proj, "local_orch", {"plan": {"status": "not_applicable"}})
    assert program.load(proj)["orchestratorMachine"].endswith("|claude-gate")


def test_orchestrator_reuses_confirmed_drive_without_usage(proj, monkeypatch):
    program.cmd_orchestrator(proj, "local_orch", {"plan": {"status": "ok"}})
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop-3p")  # окружение «спорит» с подтверждением
    program.cmd_orchestrator(proj, "local_orch2")
    assert program.load(proj)["orchestratorMachine"].endswith("|claude")  # ранее подтверждённый сильнее окружения


def test_profile_set_drive_flag(tmp_path):
    from kit import __main__ as cli, profile
    assert cli.main(["profile", "set", "--preset", "desktop-gate", "--drive", "claude-gate"]) == 0
    loaded = profile.load()
    assert loaded.drive == "claude-gate" and loaded.preset == "desktop-gate"
    assert 'drive = "claude-gate"' in profile.global_profile_path().read_text(encoding="utf-8")
    with pytest.raises(SystemExit):  # argparse: неизвестный привод не проходит choices
        cli.main(["profile", "set", "--drive", "gemini"])


def test_skills_teach_the_narrowed_detection():
    from kit import commands
    roles = (commands.KIT_ROOT / "skills" / "autopilot-roles" / "SKILL.md").read_text(encoding="utf-8")
    assert "ANTHROPIC_BASE_URL` is **not** a drive marker" in roles
    assert 'drive = "claude" | "claude-gate" | "codex"' in roles
    assert "CLAUDECODE -and $env:ANTHROPIC_BASE_URL" not in roles  # старый широкий признак убран
    prog = " ".join((commands.KIT_ROOT / "skills" / "autopilot-program" / "SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ("The environment can lie in both directions", "**The limits answer is authoritative (T19.8).**",
                   "`plan.status: \"ok\"` → drive `claude`", "--usage '<the get_usage json>'",
                   "Never skip this section on env markers alone."):
        assert phrase in prog, phrase


# ── T19.9: сторож не трогает чужое и неподтверждённое ───────────────────────

def _drop_machine(root):
    """Запись до D48: оркестратор есть, orchestratorMachine нет."""
    path = root / ".autopilot" / "program.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["orchestratorMachine"] = None
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _start_unbound(root, minutes_ago=20):
    """Этап начат (`start`), сессия не привязана — сценарий D35: сторож хочет будить оркестратора."""
    program.cmd_start(root, "M1", adopt=False)
    path = root / ".autopilot" / "program.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["stages"][0]["startedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).astimezone().isoformat(timespec="seconds")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_watch_skips_dashboard_server_for_foreign_programs(proj, monkeypatch):
    program.cmd_orchestrator(proj, "local_orch")
    _set_machine(proj, "claude")  # другой привод той же машины
    program.register_program(proj, "демо")
    served = []
    monkeypatch.setattr(program, "ensure_server", lambda root: served.append(str(root)))
    monkeypatch.delenv("AUTOPILOT_KIT_NO_SERVE", raising=False)
    results = program.cmd_watch()
    assert served == []  # T19.9: сервер чужой программы не поднимается и не заменяется
    assert any(r.get("foreign") for r in results)


def test_unknown_owner_flagged_and_action_kept_on_first_pass(proj):
    program.cmd_orchestrator(proj, "local_orch")
    _drop_machine(proj)
    _start_unbound(proj)
    result = program.watch_program(proj, {})
    assert result["unknownOwner"] is True and result["action"] == "wake_orchestrator"
    assert result["orchestrator"] == "local_orch"
    assert "confirm-owner" in result["ownerMessage"] and "local_orch" in result["ownerMessage"]


def test_unknown_owner_confirm_and_absent_lifecycle(proj):
    program.cmd_orchestrator(proj, "local_orch")
    _drop_machine(proj)
    _start_unbound(proj)
    # сессия оркестратора в этом профиле не найдена → задача сторожа глушит запись
    program.cmd_confirm_owner(proj, absent=True)
    silenced = program.watch_program(proj, program.load_watch_memory())
    assert silenced["action"] == "none" and silenced.get("unknownOwner")
    assert "ownerMessage" not in silenced and "не подтверждён" in silenced["note"]
    # владелец (или задача, нашедшая сессию) подтверждает → запись становится своей и снова обслуживается
    out = program.cmd_confirm_owner(proj, absent=False)
    data = program.load(proj)
    assert data["orchestratorMachine"].split("|")[2] == "claude-gate"  # ранее подтверждённый привод сохранён
    assert "владение подтверждено" in out
    assert not program.load_watch_memory().get(program.unknown_owner_key(proj))
    again = program.watch_program(proj, program.load_watch_memory())
    assert not again.get("unknownOwner") and again["action"] == "wake_orchestrator"


def test_watch_skips_dashboard_server_for_silenced_unknown_owner(proj, monkeypatch):
    program.cmd_orchestrator(proj, "local_orch")
    _drop_machine(proj)
    program.register_program(proj, "демо")
    program.cmd_confirm_owner(proj, absent=True)
    served = []
    monkeypatch.setattr(program, "ensure_server", lambda root: served.append(str(root)))
    monkeypatch.delenv("AUTOPILOT_KIT_NO_SERVE", raising=False)
    results = program.cmd_watch()
    assert served == []
    item = [r for r in results if r["root"].endswith("proj")][0]
    assert item.get("unknownOwner") and item["action"] == "none"


def test_watch_prompt_teaches_the_unknown_owner_rule():
    text = program.watch_prompt()
    assert "unknownOwner: true" in text and "confirm-owner" in text and "confirm-owner --absent" in text
    assert "ownerMessage" in text and "не делай" in text
    assert "6. Ответь одной строкой" in text and "7. Затем убери этот чат" in text


def test_doctor_warns_about_misplaced_drive_pin(tmp_path, monkeypatch):
    from kit import doctor
    home = tmp_path / "warn-home"
    (home / ".autopilot-kit").mkdir(parents=True)
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    (home / ".autopilot-kit" / "profile.toml").write_text(
        'preset = "quality"\n\n[roles.executor]\ntier = "strong"\neffort = "medium"\ndrive = "claude-gate"\n', encoding="utf-8")
    status, message = doctor.check_drive_pin()
    assert status == doctor.WARN and "roles.executor.drive" in message
    assert program.pinned_drive() is None  # вложенный ключ молча не работает — поэтому WARN
    (home / ".autopilot-kit" / "profile.toml").write_text('preset = "quality"\ndrive = "claude-gate"\n', encoding="utf-8")
    status, message = doctor.check_drive_pin()
    assert status == doctor.OK and "drive = claude-gate" in message
    (home / ".autopilot-kit" / "profile.toml").write_text('preset = "quality"\n', encoding="utf-8")
    assert doctor.check_drive_pin()[0] == doctor.OK


def test_doctor_projects_warn_about_drive_inside_gate(tmp_path, monkeypatch):
    from kit import projects
    home = tmp_path / "warn-home2"
    (home / ".autopilot-kit" / "bin").mkdir(parents=True)
    (home / ".autopilot-kit" / "bin" / "gate.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    root = tmp_path / "proj"
    (root / ".autopilot-kit").mkdir(parents=True)
    (root / ".autopilot-kit" / "project.toml").write_text('[gate]\ncommands = []\ndrive = "claude-gate"\n', encoding="utf-8")
    assert program.pinned_drive(root) is None and gate.pinned_drive(root) is None  # внутри [gate] не работает
    which = lambda _name: "C:/Python312/python.exe"
    run = lambda args: subprocess.CompletedProcess(args, 0, stdout="kit-ok\n", stderr="")
    rows = [r for r in projects.check_project(root, which, run) if "фиксация привода" in r[0]]
    assert rows and rows[0][1] == projects.WARN and "gate.drive" in rows[0][2]
