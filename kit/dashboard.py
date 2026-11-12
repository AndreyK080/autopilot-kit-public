"""Пульт всех программ (D43): `python -m kit dashboard` — локальная страница только для чтения.

Дашборд прогона и дашборд программы показывают одно дело; пульт — всё сразу и то, что требует внимания владельца.
Из чатов этого не видно: этап не проснулся после паузы, папка программы пропала, программа выпала из реестра.
Правила внимания — обычный код, без модели. Файлы программ пульт не меняет.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kit import commands, doctor, program, projects, upstream

PORT = 8699  # сразу под диапазоном дашбордов программ (8700–8899)
MARKER = "autopilot-kit: пульт"
PAGE = Path(__file__).with_name("dashboard_page.html")
FAST_TTL = 5        # секунд: состояние программ читается с сетевого диска, страница опрашивает его каждые 15 с
SLOW_TTL = 1800     # секунд: GitHub, doctor и поиск программ на диске
WATCH_LATE_MIN = 45  # сторож ходит каждые 15 минут; три пропуска подряд — приложение или компьютер выключены
TASKS = {"autopilot-program-watchdog": "Сторож программ", "autopilot-weekly-update-check": "Автообновление Autopilot"}
CRITICAL, IMPORTANT, INFO = 0, 1, 2
GATE_RESULTS = ("pass", "block", "loop-release")  # остальные записи журнала — чаты оркестратора и сторожа, не работа этапа


def _ago(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 48 * 60:
        return f"{minutes // 60} ч {minutes % 60:02d} мин"
    return f"{minutes // 1440} дн {minutes % 1440 // 60} ч"


def _moment(stamp: str | None) -> datetime | None:
    moment = program._instant(stamp or "")
    return None if moment.year == 1 else moment.astimezone()


def _since(moment: datetime | None) -> float | None:
    return None if moment is None else (datetime.now(timezone.utc) - moment).total_seconds() / 60


def _clock(moment: datetime | None) -> str:
    if not moment:
        return "—"
    return moment.strftime("%d.%m, %H:%M" if moment.year == datetime.now().year else "%d.%m.%Y, %H:%M")


def _item(level: int, where: str, what: str, action: str) -> dict:
    return {"level": level, "where": where, "what": what, "action": action}


def _stage_row(data: dict, stage: dict, log: list[dict]) -> dict:
    metrics = program.stage_metrics(data, stage, log)
    started, finished = _moment(stage.get("startedAt")), _moment(stage.get("finishedAt"))
    return {"id": stage["id"], "title": stage.get("title") or "", "status": stage["status"],
            "statusText": program.STATUS_RU.get(stage["status"], stage["status"]),
            "minutes": int((finished - started).total_seconds() // 60) if started and finished else None,
            "elapsedText": _ago(_since(started)) if started and not finished else None,
            "gateRuns": metrics["runs"], "blocks": metrics["blocks"], "releases": metrics["releases"],
            "flaky": metrics["flaky"], "repairs": metrics["repairs"]}


def _program_alerts(row: dict, data: dict, stage: dict | None, quiet: float | None) -> list[dict]:
    """Что требует внимания в одной программе; пороги те же, что у сторожа."""
    name = row["name"]
    where = f"{name} · {stage['id']}" if stage else name
    alerts = []
    questions = program.open_questions(data)
    if questions:
        alerts.append(_item(CRITICAL, name, "Ждёт вашего ответа: " + ", ".join(q["id"] for q in questions) + ".",
                            "Ответить в чате оркестратора"))
    for failed in (s for s in data["stages"] if s["status"] == "failed"):
        alerts.append(_item(CRITICAL, f"{name} · {failed['id']}", "Этап провален.", "Разобрать в чате оркестратора"))
    if stage and stage["status"] == "waiting":
        alone = (not questions and not [t for t in data.get("ownerTasks") or [] if not t.get("done")]
                 and quiet is not None and quiet >= program.WATCH_REMIND_MIN)
        alerts.append(_item(CRITICAL, where, f"Этап ждёт вас уже {_ago(quiet)}."
                            + (" Открытых вопросов и задач в программе нет — флаг мог устареть." if alone else ""),
                            "Оркестратору: `program.py why-paused`" if alone else "Ответить в чате оркестратора"))
    pause = data.get("pause") or {}
    until = _moment(pause.get("until"))
    paused = bool(pause) and until is not None and until > datetime.now(timezone.utc).astimezone()
    if pause and not program.auto_resumes(pause):  # D46: остановка владельцем — сама не кончится
        alerts.append(_item(INFO, where, "Пауза по слову владельца" + (f": {pause['text']}" if pause.get("text") else "")
                            + ". Сама не кончится.", "Сказать оркестратору «продолжай» — он выполнит resume"))
    elif paused:
        alerts.append(_item(INFO, where, f"На паузе до {_clock(until)}; продолжит задача сброса лимита.", "Ничего не нужно"))
    elif pause:
        alerts.append(_item(CRITICAL, where, f"Пауза кончилась {_clock(until)}, но программа всё ещё на паузе: "
                            f"последняя активность {_ago(quiet)} назад.", "Написать /autopilot-program в оркестраторе"))
    if not row["registered"]:
        if stage:
            alerts.append(_item(IMPORTANT, where, f"Этап числится идущим, активности нет {_ago(quiet)}. Программы нет в реестре: "
                                "сторож и проверка занятости перед обновлением её не видят.",
                                "Вернуть в реестр и перезапустить оркестратор или закрыть"))
    elif stage and stage["status"] == "running" and not pause and quiet is not None and quiet >= program.WATCH_QUIET_MIN:
        alerts.append(_item(CRITICAL, where, f"Этап молчит {_ago(quiet)}: сторож должен был его разбудить.",
                            "Написать «продолжай» оркестратору"))
    elif (not stage and not pause and program.next_pending(data) is not None
          and quiet is not None and quiet >= program.WATCH_QUIET_MIN):
        alerts.append(_item(IMPORTANT, name, f"Следующий этап не начат уже {_ago(quiet)}.", "Написать «продолжай» оркестратору"))
    if stage and stage["status"] == "running" and not pause and program.reserve_empty(data):
        # T21.5: резерв пополняется только в ходе владельца — предупредить заранее, пока этап ещё идёт
        alerts.append(_item(IMPORTANT, where, "Резерв чатов пуст: когда этап сдастся, следующий не запустится без владельца.",
                            "Написать оркестратору что-нибудь — в его ходе резерв пополнится"))
    return alerts


def program_row(root: Path, registered: bool) -> tuple[dict, list[dict]]:
    """Строка программы для страницы и её пункты внимания. Недоступная программа — тоже строка, а не исключение."""
    row = {"name": root.name, "root": str(root), "registered": registered, "error": None, "stages": [], "passed": 0,
           "total": 0, "current": None, "currentTitle": None, "lastActivity": "—", "quietText": "—", "tasks": [], "url": None}
    if not root.is_dir():
        row["error"] = "папка недоступна"
        return row, [_item(CRITICAL if registered else IMPORTANT, root.name, f"Папка {root} недоступна, а программа числится в реестре.",
                           "Вернуть доступ к папке или убрать программу из реестра")]
    try:
        data = program.load(root)
    except (OSError, ValueError, program.ProgramError) as error:
        row["error"] = str(error)
        return row, [_item(CRITICAL if registered else IMPORTANT, root.name, f"Состояние программы не прочитать: {error}.",
                           "Открыть чат оркестратора программы")]
    log = program.read_gate_log(root)
    try:
        run = program.read_run(root)
    except (OSError, ValueError, program.ProgramError):
        run = None
    marks = [_moment(data.get("updatedAt")), _moment((run or {}).get("updatedAt"))]
    marks += [_moment(e.get("at")) for e in log[-200:] if e.get("result") in GATE_RESULTS]
    last = max((m for m in marks if m), default=None)
    quiet = _since(last)
    stage = program.active_stage(data)
    live = [s for s in data["stages"] if s["status"] != "skipped"]
    row.update(stages=[_stage_row(data, s, log) for s in data["stages"]],
               passed=sum(s["status"] == "passed" for s in live), total=len(live),
               current=stage["id"] if stage else None, currentTitle=stage.get("title") if stage else None,
               lastActivity=_clock(last), quietText=_ago(quiet), goal=data.get("goal") or "",
               tasks=[{"id": t.get("id"), "stage": t.get("stage"), "text": t.get("text")}
                      for t in data.get("ownerTasks") or [] if not t.get("done")],
               url=program.page_url(root) if registered else None)
    return row, _program_alerts(row, data, stage, quiet)


def discover(known: list[Path]) -> list[Path]:
    """Программы рядом с известными (папка и подпапка), которых нет в реестре: проект R и проект K выпали из него незаметно."""
    found: list[Path] = []
    bases = {os.path.normcase(str(root.parent)): root.parent for root in known}
    for base in bases.values():
        for child in _subdirs(base):
            for candidate in (child, *_subdirs(child)):
                if program.program_path(candidate).is_file() and not any(projects._same(candidate, k) for k in [*known, *found]):
                    found.append(candidate)
    return found


def _subdirs(path: Path) -> list[Path]:
    try:
        with os.scandir(path) as entries:
            return [Path(e.path) for e in entries if not e.name.startswith((".", "_")) and e.is_dir()]
    except OSError:  # чужая или недоступная папка на сетевом диске — просто не ищем в ней
        return []


def _installed_version() -> str | None:
    try:
        text = (upstream.default_targets()[0] / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^\s*version:\s*"?([^"\s]+)', text, re.M)
    return match.group(1) if match else None


def _remote_version(url: str, head: str) -> str | None:
    match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?", url)
    if not match:
        return None
    raw = f"https://raw.githubusercontent.com/{match.group(1)}/{head}/{upstream.SKILL_SUBPATH.as_posix()}/SKILL.md"
    try:
        with urllib.request.urlopen(raw, timeout=10) as reply:
            text = reply.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    found = re.search(r'^\s*version:\s*"?([^"\s]+)', text, re.M)
    return found.group(1) if found else None


def _trial_report(head: str | None) -> dict:
    """Итог `kit trial` для этого коммита: швы, коммиты автора и изменённые файлы. Другой кандидат — швы не проверялись."""
    empty = {"seamsOk": None, "seamsFail": None, "log": "", "files": []}
    try:
        text = (commands.trial_root() / "report.md").read_text(encoding="utf-8")
    except OSError:
        return empty
    candidate = re.search(r"кандидат: (\w+)", text)
    if not head or not candidate or not head.startswith(candidate.group(1)):
        return empty
    sections = dict(re.findall(r"^## (.+?)\n\n(.*?)(?=^## |\Z)", text, re.M | re.S))
    seams = sections.get("Швы", "")
    return {"seamsOk": len(re.findall(r"^OK\s", seams, re.M)), "seamsFail": len(re.findall(r"^FAIL\s", seams, re.M)),
            "log": sections.get("Коммиты автора по skills/autopilot", "").strip(),
            "files": re.findall(r"^- (.+)$", sections.get("Изменённые файлы", ""), re.M)}


def upstream_info() -> dict:
    lock = upstream.read_lock()
    info = {"installed": _installed_version(), "installedCommit": (lock or {}).get("commit", "")[:7], "latest": None,
            "latestCommit": None, "available": False, "reachable": False, "seamsOk": None, "seamsFail": None, "log": "", "files": []}
    if not lock:
        return info
    url = lock.get("source") or upstream.REPO_URL
    head = commands.remote_head(url)
    if not head:
        return info
    latest = _remote_version(url, head)
    info.update(reachable=True, latestCommit=head[:7], latest=latest or info["installed"],
                # HEAD сдвинулся, а версия навыка та же — в репозитории автора менялось не ядро
                available=head != lock["commit"] and (latest is None or latest != info["installed"]))
    info.update(_trial_report(head))
    return info


def doctor_info(extra: list[Path]) -> dict:
    rows = doctor.collect() + projects.collect_projects(extra)
    return {"fail": [f"{name}: {message}" for name, status, message in rows if status == doctor.FAIL],
            "warn": sum(status == doctor.WARN for _, status, _ in rows)}


def git_info() -> dict:
    def ask(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(commands.KIT_ROOT), *args], capture_output=True, text=True, encoding="utf-8")
        return done.stdout.strip() if done.returncode == 0 else ""
    unpushed = ask("rev-list", "--count", "@{u}..HEAD")
    return {"unpushed": int(unpushed) if unpushed.isdigit() else None, "lastCommit": _clock(_moment(ask("log", "-1", "--format=%cI")))}


def collect_slow(extra: list[Path]) -> dict:
    """То, что медленно или ходит в сеть: обновляется редко и в фоне, страница не ждёт."""
    slow: dict = {"checkedAt": program.now(), "upstream": None, "doctor": None, "git": None, "found": []}
    jobs = {"upstream": upstream_info, "doctor": lambda: doctor_info(extra), "git": git_info,
            "found": lambda: [str(p) for p in discover(projects.project_list(extra))]}
    for key, job in jobs.items():
        try:
            slow[key] = job()
        except Exception as error:  # один сбой (нет сети, нет codex) не должен гасить остальной пульт
            slow.setdefault("errors", []).append(f"{key}: {error}")
    return slow


def _registered() -> list[Path]:
    return [Path(os.path.abspath(p["root"])) for p in projects._registry().get("programs") or []
            if isinstance(p, dict) and p.get("root")]


def _automation() -> tuple[list[dict], list[dict]]:
    home = upstream.kit_home()
    last = None
    try:
        last = _moment((home / ".autopilot-kit" / "watch_last").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    quiet = _since(last)
    rows = [{"name": name, "present": (home / ".claude" / "scheduled-tasks" / task).is_dir()} for task, name in TASKS.items()]
    rows[0].update(last=_clock(last), ago=_ago(quiet))
    trial = commands.trial_root() / "report.md"
    if trial.is_file():
        checked = datetime.fromtimestamp(trial.stat().st_mtime, timezone.utc)
        rows[1].update(last=_clock(checked.astimezone()), ago=_ago(_since(checked)), note="последняя проверка новой версии")
    alerts = []
    if quiet is None:
        alerts.append(_item(INFO, "Сторож", "Сторож ещё не записал ни одного запуска: запись появляется после первого обхода.", "Ничего не нужно"))
    elif quiet >= WATCH_LATE_MIN:
        alerts.append(_item(IMPORTANT, "Сторож", f"Сторож не запускался {_ago(quiet)}: скорее всего, приложение или компьютер были выключены, "
                            "и программы шли без присмотра.", "Держать приложение и компьютер включёнными на время программ"))
    return rows, alerts


def collect_state(slow: dict, extra: list[Path] | None = None) -> dict:
    """Всё состояние для страницы. Только чтение."""
    registered = _registered()
    extra_roots = [r for r in projects.project_list(extra) if not any(projects._same(r, k) for k in registered)]
    found = [Path(p) for p in slow.get("found") or []
             if not any(projects._same(Path(p), k) for k in [*registered, *extra_roots])]
    programs, alerts = [], []
    for root, is_registered in [*((r, True) for r in registered), *((r, False) for r in [*extra_roots, *found])]:
        row, items = program_row(root, is_registered)
        programs.append(row)
        alerts += items
    automation, watch_alerts = _automation()
    alerts += watch_alerts
    core = slow.get("upstream")
    if core and core.get("available"):
        busy = [f"{p['name']} {p['current']}" for p in programs if p["current"] and p["registered"]]
        seams = ("швы зелёные" if core["seamsOk"] and not core["seamsFail"] else
                 "есть красные швы" if core["seamsFail"] else "швы ещё не проверялись")
        reason = f"идут {', '.join(busy)}" if busy else "ждёт проверки в понедельник"
        alerts.append(_item(IMPORTANT, "Ядро", f"Вышла версия {core['latest']} (установлена {core['installed']}), {seams}; не установлена: {reason}.",
                            "Поставится сама, когда этапы закончатся; раньше — python -m kit update в момент простоя"))
    health = slow.get("doctor")
    if health:
        for line in health["fail"]:
            if ": папка:" not in line:  # пропавшая папка уже в списке выше, отдельной строкой программы
                alerts.append(_item(IMPORTANT, "kit doctor", line, "Запустить python -m kit doctor --projects"))
    git = slow.get("git") or {}
    if git.get("unpushed"):
        alerts.append(_item(INFO, "autopilot-kit", f"Не отправлено на GitHub коммитов: {git['unpushed']}.", "Сказать, когда отправить"))
    alerts.sort(key=lambda a: a["level"])
    return {"generatedAt": program.now(), "programs": programs, "alerts": alerts, "automation": automation,
            "core": core, "doctor": health, "git": git, "slowCheckedAt": _clock(_moment(slow.get("checkedAt")))}


class Pulse:
    """Кэш состояния для сервера: быстрая часть по запросу, медленная — фоновым потоком."""

    def __init__(self, extra: list[Path]):
        self.extra = extra
        self.lock = threading.Lock()
        self.slow: dict = {}
        self.slow_at = 0.0
        self.slow_running = False
        self.state: dict | None = None
        self.state_at = 0.0

    def _refresh_slow(self) -> None:
        try:
            slow = collect_slow(self.extra)
            with self.lock:
                self.slow, self.slow_at, self.state_at = slow, time.monotonic(), 0.0
        finally:
            self.slow_running = False

    def current(self) -> dict:
        with self.lock:
            if not self.slow_running and (not self.slow_at or time.monotonic() - self.slow_at >= SLOW_TTL):
                self.slow_running = True
                threading.Thread(target=self._refresh_slow, daemon=True).start()
            if self.state is None or time.monotonic() - self.state_at >= FAST_TTL:
                self.state = collect_state(self.slow, self.extra)
                self.state["slowPending"] = not self.slow_at
                self.state_at = time.monotonic()
            return self.state


def code_id(extra: list[Path]) -> str:
    """Меняется с кодом пульта и списком папок: так обычный запуск заменяет фоновый сервер прошлой версии."""
    raw = Path(__file__).read_bytes() + PAGE.read_bytes() + repr(sorted(str(p) for p in extra)).encode("utf-8")
    return format(zlib.crc32(raw), "08x")


def make_server(port: int, extra: list[Path]) -> ThreadingHTTPServer:
    pulse = Pulse(extra)
    ping = json.dumps({"marker": MARKER, "pid": os.getpid(), "code": code_id(extra)}).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, kind: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            # чужой сайт в браузере не должен читать состояние проектов через подмену DNS
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):
                self._send(403, "text/plain; charset=utf-8", "Только с этого компьютера".encode("utf-8"))
            elif self.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            elif self.path == "/api/state":
                self._send(200, "application/json; charset=utf-8", json.dumps(pulse.current(), ensure_ascii=False).encode("utf-8"))
            elif self.path == "/api/ping":
                self._send(200, "application/json; charset=utf-8", ping)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

        def log_message(self, *_args) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def _ping(port: int) -> dict | None:
    """Ответ нашего сервера; {} — порт занят другим; None — никого."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as reply:
            answer = json.loads(reply.read())
        return answer if answer.get("marker") == MARKER else {}
    except urllib.error.HTTPError:
        return {}
    except ValueError:
        return {}
    except OSError:
        return None


def _stop_old(pid: int, port: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        if _ping(port) is None:
            return
        time.sleep(0.25)


def _spawn(port: int, extra: list[Path]) -> None:
    log_path = upstream.kit_home() / ".autopilot-kit" / "dashboard.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-m", "kit", "dashboard", "--foreground", "--no-open", "--port", str(port)]
    for path in extra:
        args += ["--project", str(path)]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with open(log_path, "ab") as log:
        subprocess.Popen(args, cwd=commands.KIT_ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)


def cmd_dashboard(extra: list[Path] | None = None, port: int = PORT, foreground: bool = False, open_browser: bool = True) -> int:
    extra = [Path(os.path.abspath(p)) for p in extra or []]
    url = f"http://localhost:{port}/"
    if os.environ.get("AUTOPILOT_KIT_NO_SERVE"):  # тесты не поднимают серверы
        print(f"Пульт: {url}")
        return 0
    answer = _ping(port)
    if answer == {}:
        print(f"Порт {port} занят другим процессом. Укажите другой: python -m kit dashboard --port <номер>")
        return 1
    if answer and answer.get("code") != code_id(extra):
        _stop_old(answer["pid"], port)
        answer = None
    if foreground:
        while answer:  # сервер этой версии уже работает — окну достаточно ждать, пока он жив
            time.sleep(30)
            answer = _ping(port)
        print(f"Пульт: {url}", flush=True)
        make_server(port, extra).serve_forever()
        return 0
    if not answer:
        _spawn(port, extra)
        for _ in range(40):
            if _ping(port):
                break
            time.sleep(0.25)
        else:
            print(f"Сервер пульта не ответил — см. {upstream.kit_home() / '.autopilot-kit' / 'dashboard.log'}")
            return 1
    print(f"Пульт: {url}")
    if open_browser:
        webbrowser.open(url)
    return 0
