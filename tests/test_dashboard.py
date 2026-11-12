import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kit import __main__ as cli
from kit import dashboard, program


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".autopilot-kit").mkdir(parents=True)
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(home))
    monkeypatch.setenv("AUTOPILOT_KIT_NO_SERVE", "1")
    return home


def stamp(minutes_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def make_program(root: Path, stages=None, **fields) -> Path:
    (root / ".autopilot").mkdir(parents=True)
    data = {"version": program.VERSION, "goal": "цель", "mode": "full", "questions": [], "updatedAt": stamp(),
            "stages": stages if stages is not None else [
                {"id": "A1", "title": "Первый", "status": "passed", "startedAt": stamp(200), "finishedAt": stamp(80)},
                {"id": "A2", "title": "Второй", "status": "running", "startedAt": stamp(70), "sessionId": "local_x"},
                {"id": "A3", "title": "Третий", "status": "pending"},
                {"id": "A0f", "title": "Долг", "status": "skipped"}],
            **fields}
    (root / ".autopilot" / "program.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


def register(home: Path, *roots: Path) -> None:
    programs = [{"root": str(r), "goal": "цель"} for r in roots]
    (home / ".autopilot-kit" / "programs.json").write_text(json.dumps({"programs": programs}), encoding="utf-8")


def state(extra=None, **slow):
    return dashboard.collect_state(slow, extra)


def texts(result: dict, level: int) -> list[str]:
    return [a["what"] for a in result["alerts"] if a["level"] == level]


def test_program_row_counts_stages_metrics_and_tasks(home, tmp_path):
    root = make_program(tmp_path / "proj", ownerTasks=[{"id": "T1", "text": "сделать", "stage": "A1", "done": None},
                                                        {"id": "T2", "text": "готово", "done": stamp()}])
    (root / ".autopilot-kit").mkdir()
    log = [{"at": stamp(5), "stage": "A2", "result": r} for r in ("pass", "block", "loop-release", "skip-program-chat")]
    (root / ".autopilot-kit" / "gate_log.jsonl").write_text("\n".join(map(json.dumps, log)) + "\n", encoding="utf-8")
    register(home, root)
    row = state()["programs"][0]
    assert (row["passed"], row["total"], row["current"]) == (1, 3, "A2")  # пропущенный этап не считается
    assert [t["id"] for t in row["tasks"]] == ["T1"]
    a1, a2 = row["stages"][0], row["stages"][1]
    assert a1["minutes"] == 120 and a1["elapsedText"] is None
    assert a2["minutes"] is None and a2["elapsedText"]
    assert (a2["gateRuns"], a2["blocks"], a2["releases"]) == (3, 1, 1)  # записи чатов оркестратора — не прогоны


def test_missing_folder_of_registered_program_is_critical(home, tmp_path):
    register(home, tmp_path / "gone")
    result = state()
    assert result["programs"][0]["error"] == "папка недоступна"
    assert "недоступна" in texts(result, dashboard.CRITICAL)[0]


def test_expired_pause_is_critical_and_active_pause_is_only_info(home, tmp_path):
    root = make_program(tmp_path / "proj", pause={"until": stamp(60), "window": "неделя"})
    register(home, root)
    assert any("Пауза кончилась" in t for t in texts(state(), dashboard.CRITICAL))

    other = make_program(tmp_path / "other", pause={"until": stamp(-60), "window": "неделя"}, updatedAt=stamp(600))
    register(home, other)
    result = state()
    assert texts(result, dashboard.CRITICAL) == []  # на паузе молчать — норма
    assert any("На паузе" in t for t in texts(result, dashboard.INFO))


def test_quiet_stage_is_critical_only_after_threshold(home, tmp_path):
    register(home, make_program(tmp_path / "fresh"))
    assert texts(state(), dashboard.CRITICAL) == []
    register(home, make_program(tmp_path / "quiet", updatedAt=stamp(program.WATCH_QUIET_MIN + 5)))
    assert any("молчит" in t for t in texts(state(), dashboard.CRITICAL))


def test_recent_run_counts_as_activity(home, tmp_path):
    root = make_program(tmp_path / "proj", updatedAt=stamp(600))
    (root / ".autopilot" / "state.js").write_text("window.STATE = " + json.dumps({"updatedAt": stamp(1)}) + ";\n", encoding="utf-8")
    register(home, root)
    assert texts(state(), dashboard.CRITICAL) == []


def test_waiting_question_and_failed_stage_are_critical(home, tmp_path):
    stages = [{"id": "A1", "title": "x", "status": "failed"}, {"id": "A2", "title": "y", "status": "waiting", "startedAt": stamp(5)}]
    register(home, make_program(tmp_path / "proj", stages=stages, questions=[{"id": "Q1", "question": "?", "answer": None}]))
    found = " ".join(texts(state(), dashboard.CRITICAL))
    assert "Q1" in found and "провален" in found and "ждёт вас" in found


def test_program_outside_registry_is_found_and_flagged_without_changing_registry(home, tmp_path):
    known = make_program(tmp_path / "known")
    make_program(tmp_path / "lost")
    make_program(tmp_path / "group" / "deep")
    make_program(tmp_path / "group" / "deep" / "too" / "far")
    register(home, known)
    before = (home / ".autopilot-kit" / "programs.json").read_text(encoding="utf-8")
    found = dashboard.discover([known])
    assert sorted(p.name for p in found) == ["deep", "lost"]
    result = state(found=[str(p) for p in found])
    assert sorted(p["registered"] for p in result["programs"]) == [False, False, True]
    assert sum("нет в реестре" in t.lower() for t in texts(result, dashboard.IMPORTANT)) == 2
    assert (home / ".autopilot-kit" / "programs.json").read_text(encoding="utf-8") == before


def test_collecting_state_does_not_touch_program_files(home, tmp_path):
    root = make_program(tmp_path / "proj")
    register(home, root)
    before = {p.name: p.read_bytes() for p in (root / ".autopilot").iterdir()}
    state()
    assert {p.name: p.read_bytes() for p in (root / ".autopilot").iterdir()} == before


def test_watch_run_is_recorded_and_late_watch_is_flagged(home, tmp_path):
    register(home, make_program(tmp_path / "proj"))
    assert any("ещё не записал" in t for t in texts(state(), dashboard.INFO))
    program.cmd_watch()
    assert not any("Сторож" in a["where"] for a in state()["alerts"])
    (home / ".autopilot-kit" / "watch_last").write_text(stamp(dashboard.WATCH_LATE_MIN + 5), encoding="utf-8")
    assert any("не запускался" in t for t in texts(state(), dashboard.IMPORTANT))


REPORT = """# Проверка версии Autopilot в dev

Прод: aaaaaaaaaaaa · кандидат: bbbbbbbbbbbb · dev: `x`

## Коммиты автора по skills/autopilot

bbbbbbb Версия 9.9.9: новое

## Изменённые файлы

- SKILL.md
- tools/ap.py

## Швы

```
OK    файлы ядра: на месте
OK    тексты-якоря: на месте
```

**Итог:** швы зелёные
"""


def test_trial_report_counts_seams_only_for_the_same_candidate(home):
    trial = home / ".autopilot-kit" / "trial"
    trial.mkdir()
    (trial / "report.md").write_text(REPORT, encoding="utf-8")
    info = dashboard._trial_report("bbbbbbbbbbbbcccc")
    assert (info["seamsOk"], info["seamsFail"]) == (2, 0)
    assert info["files"] == ["SKILL.md", "tools/ap.py"]
    assert "Версия 9.9.9" in info["log"]
    assert dashboard._trial_report("dddd")["seamsOk"] is None


def test_new_version_is_flagged_with_busy_stages(home, tmp_path):
    register(home, make_program(tmp_path / "proj"))
    core = {"available": True, "latest": "2.2.1", "installed": "2.2.0", "seamsOk": 7, "seamsFail": 0}
    found = " ".join(texts(state(upstream=core), dashboard.IMPORTANT))
    assert "2.2.1" in found and "швы зелёные" in found and "proj A2" in found


def test_doctor_failures_are_listed_except_missing_folder_already_shown(home, monkeypatch):
    monkeypatch.setattr(dashboard.doctor, "collect", lambda: [("git", dashboard.doctor.FAIL, "нет"), ("x", dashboard.doctor.WARN, "w")])
    monkeypatch.setattr(dashboard.projects, "collect_projects", lambda _extra: [("Gone: папка", dashboard.doctor.FAIL, "нет P:\\Gone")])
    health = dashboard.doctor_info([])
    assert health["warn"] == 1 and len(health["fail"]) == 2
    assert [a["what"] for a in state(doctor=health)["alerts"] if a["where"] == "kit doctor"] == ["git: нет"]


def test_upstream_info_without_network_is_not_an_error(home, monkeypatch):
    (home / ".autopilot-kit" / "upstream.lock.json").write_text(
        json.dumps({"commit": "a" * 40, "files": {}, "source": "x"}), encoding="utf-8")
    monkeypatch.setattr(dashboard.commands, "remote_head", lambda _url: None)
    info = dashboard.upstream_info()
    assert info["reachable"] is False and info["available"] is False


def test_slow_failure_does_not_hide_other_parts(home, monkeypatch):
    monkeypatch.setattr(dashboard, "upstream_info", lambda: 1 / 0)
    monkeypatch.setattr(dashboard, "doctor_info", lambda _extra: {"fail": [], "warn": 0})
    monkeypatch.setattr(dashboard, "git_info", lambda: {"unpushed": 2, "lastCommit": "—"})
    slow = dashboard.collect_slow([])
    assert slow["upstream"] is None and slow["git"]["unpushed"] == 2 and "upstream" in slow["errors"][0]


@pytest.fixture
def server(home, monkeypatch):
    monkeypatch.setattr(dashboard, "collect_slow", lambda _extra: {"checkedAt": program.now()})
    httpd = dashboard.make_server(0, [])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def fetch(port: int, path: str, host: str | None = None) -> bytes:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if host:
        request.add_header("Host", host)
    with urllib.request.urlopen(request, timeout=5) as reply:
        return reply.read()


def test_server_gives_page_state_and_ping(home, tmp_path, server):
    register(home, make_program(tmp_path / "proj"))
    assert dashboard.MARKER in fetch(server, "/").decode("utf-8")
    assert json.loads(fetch(server, "/api/state"))["programs"][0]["name"] == "proj"
    ping = json.loads(fetch(server, "/api/ping"))
    assert ping["marker"] == dashboard.MARKER and ping["code"] == dashboard.code_id([])
    assert dashboard._ping(server)["pid"] == ping["pid"]


def test_server_refuses_foreign_host_and_unknown_paths(server):
    for path, host in (("/api/state", "evil.example:8699"), ("/nope", None)):
        with pytest.raises(urllib.error.HTTPError):
            fetch(server, path, host)
    assert dashboard._ping(1) is None


def test_page_prints_values_only_as_text():
    page = dashboard.PAGE.read_text(encoding="utf-8")
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page


def test_cli_prints_address_without_starting_a_server(home, capsys):
    assert cli.main(["dashboard", "--no-open", "--port", "8123"]) == 0
    assert "http://localhost:8123/" in capsys.readouterr().out


def test_owner_pause_is_info_and_never_called_a_limit_pause(home, tmp_path):
    root = make_program(tmp_path / "proj", pause={"reason": "owner", "until": None, "text": "стоп до утра"}, updatedAt=stamp(600))
    register(home, root)
    result = state()
    assert texts(result, dashboard.CRITICAL) == []
    owner = [t for t in texts(result, dashboard.INFO) if "по слову владельца" in t]
    assert owner and "стоп до утра" in owner[0] and "лимит" not in owner[0]


def test_far_pause_date_in_alert_shows_the_year(home, tmp_path):
    far = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat(timespec="seconds")
    register(home, make_program(tmp_path / "proj", pause={"until": far, "window": "неделя"}))
    assert any(str(datetime.now().year + 2) in t or str(datetime.now().year + 1) in t for t in texts(state(), dashboard.INFO))


def test_stale_stage_wait_without_questions_points_to_why_paused(home, tmp_path):
    stages = [{"id": "A1", "title": "Первый", "status": "waiting", "startedAt": stamp(600), "sessionId": "local_x"}]
    register(home, make_program(tmp_path / "proj", stages=stages, updatedAt=stamp(600)))
    assert any("флаг мог устареть" in t for t in texts(state(), dashboard.CRITICAL))


def test_program_page_knows_pause_reasons_and_stale_wait_hint():
    page = program.page_template().read_text(encoding="utf-8")
    for needle in ("P.pause.reason", "стоп владельца", "Сама не продолжится", "why-paused", "getFullYear"):
        assert needle in page
