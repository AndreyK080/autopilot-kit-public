"""Программа из нескольких прогонов Autopilot: состояние и проверка сдачи этапа (D18).

Файл самодостаточен (только стандартная библиотека): install копирует его в ~/.autopilot-kit/bin/program.py.
Навык /autopilot-program вызывает его из папки проекта; сам код проекта он не трогает.

Файлы проекта:
  .autopilot/program.json — источник истины (этапы, вопросы и ответы владельца);
  .autopilot/PROGRAM.md   — вид для человека, перерисовывается после каждой команды.

Команды (вывод — текст; check и next --json — JSON):
  init --goal G [--plan P] [--mode semi]
  stage add ID --title T --task TEXT [--plan-ref R] [--criterion C]...
  stage set ID --status pending|skipped|passed [--note N]   # решение владельца после провала
  ask QID --question Q --recommended R [--stage ID]          # вопрос владельцу (без --stage — для всей программы)
  answer QID [--answer A] [--assumption]                     # без --answer берётся рекомендуемый ответ
  start ID [--adopt]                                         # занять папку под этап; --adopt — подхватить начатый прогон
  bind ID --session SID                                      # сессия, в которой идёт этап
  check [ID] [--record] [--no-gate]                          # вердикт этапа JSON
  next [--json]                                              # готов ли следующий этап; аргументы Autopilot для него
  prompt ID [--manual]                                       # задание сессии этапа (после start); --manual — для Codex
  status | report [--metrics]                               # --metrics: польза по этапам из журнала гейта (D41)
  track                                                      # одна строка хода программы для чата
  limits --phase start|running --usage <JSON get_usage> | --codex   # решение по лимитам: go / pause / insure (D22, D24)
  pause --until <ISO> [--window W] [--orchestrator SID] [--reason limit|owner|other] [--text T] | resume [--keep-wait]
                                                             # пауза: limit — до сброса лимита, продолжу сам; owner/other — снимает только resume (D46)
  quota-pause --text '<отказ 429 дословно>' [--orchestrator SID]  # квота гейтвея исчерпана: пауза до сброса из текста отказа (T21.9)
  why-paused                                                 # все причины «оранжевого» дашборда и чем снять каждую (D46)
  stage unwait ID [--force]                                  # снять ожидание владельца в state.js этапа (ap.py answered), если ничто не держит (D46)
  wake-prompt                                                # текст разовой задачи «продолжить после сброса лимита»
  plan-template | plan-check FILE | plan-load FILE           # план программы по шаблону (D23)
  mode full|semi|interview|manual                            # режим прогонов следующих этапов (D29: full)
  autonomy full|ask                                          # D30: full — оркестратор не ждёт владельца
  stage repair ID | stage accept ID [--note N]               # провал: один ремонт, затем принять и этап долга (D30)
  stage prev-done ID [--session S]                           # прежние сессии этапа погашены (T21.3)
  job set --label L --probe CMD --until ISO | job clear --label L | job list   # долгая работа вне чата под наблюдением сторожа (D47)
  owner-task add TEXT [--stage S] [--kind pause] | owner-task done T1 [--unwait] [--note N]   # задачи владельца, программу не держат (D30);
                                                             # kind pause — «ожидание паузы», её закрывает resume (D46)
  ask ID … --approval | approve add TEXT [--env E]… [--stage S] [--permission mcp__…] | approve list   # разрешения для проверки режима auto (D41, T21.4б)
  stage continue ID                                          # этап сдан частично: следующая часть доделывает отложенное
  leftovers ID [--done --note N]                             # остаток сданного этапа и отметка, что он разобран (D26)
  codex-run ID [--exec-arg A]… | codex-status [ID] | codex-answer ID TEXT | codex-prompt ID   # привод Codex (D24)
  watch [--json] | watch-prompt                              # сторож программ машины и текст его задачи (D28)
  confirm-owner [--absent]                                   # подтверждение владения записью до D48: --absent — глушить (T19.9)
  orchestrator --session SID [--usage <JSON get_usage>]         # id чата оркестратора — его будит сторож (D31);
                                                             # --usage авторитетно подтверждает привод (T19.8)
  setup-check                                                # настроена ли папка проекта для kit: гейт, хуки, правила, git (D39)
  pool add SID | pool drop SID | pool release SID | pool take [--json] | pool need | pool list | pool-prompt   # резерв сессий этапов (D31); drop — убрать мёртвую
                                                             # take --json: сначала сессия сданного этапа для очистки (D40), затем резерв
  signal ID                                                  # сообщение резервной сессии: задание этапа (D31)
  prompt ID --after-signal                                   # этап, созданный на паузе: начнёт по сигналу
  page [--launch] | serve                                    # дашборд .autopilot/program.html и его постоянный сервер (D25);
                                                             # --launch — ещё конфигурация панели и освобождение порта под неё (T21.15)

Вердикты check: not_started (прогон этапа ещё не начат), waiting (Autopilot ждёт владельца), unfinished
(прогон не закончен и не ждёт), passed, failed (с причинами). Сдача: прогон закончен, нет упавших этапов
Autopilot и незакрытых тасков, гейты G2–G4 не провалены и слепая приёмка (G4) была, гейт проекта — код 0,
после старта этапа есть коммит «Autopilot: сборка сдана», в PROGRESS.md есть «## Следующий шаг» (кроме
последнего этапа). G1 не проверяется: он фиксирует открытые требования в момент начала спецификации.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = 1
MODES = ("full", "semi", "interview", "manual")
STAGE_STATUSES = ("pending", "running", "waiting", "passed", "failed", "skipped")
ACTIVE = ("running", "waiting")
LANDING_SUBJECT = "Autopilot: сборка сдана"
NEXT_STEP_HEADING = "## Следующий шаг"
GATE_TAIL = 2000
MARKER = "<!-- autopilot-kit:program — вид program.json; правится только командами program.py -->"
# фазы прогона Autopilot (ид в state.js, имя как на его дашборде) и их вес в проценте этапа; страница берёт их из program.js
PHASES = (("preflight", "Подготовка", 3), ("manifest", "Требования", 7), ("briefing", "Брифинг", 5),
          ("spec", "Спецификация", 12), ("plan", "План", 8), ("build", "Разработка", 45),
          ("review", "Код-ревью", 12), ("final", "Приёмка", 8))
PAGE_NAME = "program.html"
PAGE_TEMPLATE = "program_page.html"  # лежит рядом с этим файлом (kit/ или ~/.autopilot-kit/bin/)
LAUNCH_NAME = "autopilot-program"


class ProgramError(Exception):
    pass


# ── пути и время ────────────────────────────────────────────────────────────

def kit_home() -> Path:
    override = os.environ.get("AUTOPILOT_KIT_HOME")
    return Path(override) if override else Path.home()


def gate_script() -> Path:
    return kit_home() / ".autopilot-kit" / "bin" / "gate.py"


def find_project_root(start: Path) -> Path:
    """Ближайшая вверх папка с .autopilot, .autopilot-kit или .git; иначе start."""
    start = Path(os.path.abspath(start))  # не resolve: на сетевом диске P: он даёт UNC-путь, с которым cmd.exe не работает
    for folder in (start, *start.parents):
        if any((folder / name).exists() for name in (".autopilot", ".autopilot-kit", ".git")):
            return folder
    return start


def program_path(root: Path) -> Path:
    return root / ".autopilot" / "program.json"


def view_path(root: Path) -> Path:
    return root / ".autopilot" / "PROGRAM.md"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ── состояние программы ─────────────────────────────────────────────────────

def load(root: Path) -> dict:
    path = program_path(root)
    if not path.exists():
        raise ProgramError("программы нет — начните с `program.py init`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ProgramError(f"program.json не разбирается: {error}") from error
    if data.get("version") != VERSION:
        raise ProgramError(f"program.json версии {data.get('version')}, ожидается {VERSION}")
    return data


def data_js_path(root: Path) -> Path:
    return root / ".autopilot" / "program.js"


def save(root: Path, data: dict) -> None:
    data["updatedAt"] = now()
    path = program_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    page_data = {**data, "phases": [{"id": p, "name": n, "weight": w} for p, n, w in PHASES], "pageBuild": page_build(),
                 "reserveEmpty": reserve_empty(data)}  # T21.5: страница предупреждает о пустом резерве заранее
    for target, text in ((path, json.dumps(data, ensure_ascii=False, indent=2) + "\n"),
                         (view_path(root), render(data)),
                         (data_js_path(root), "window.PROGRAM =\n" + json.dumps(page_data, ensure_ascii=False) + ";\n")):
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    refresh_page(root)


def stage_of(data: dict, sid: str) -> dict:
    for stage in data["stages"]:
        if stage["id"] == sid:
            return stage
    raise ProgramError(f"нет этапа {sid}")


def question_of(data: dict, qid: str) -> dict:
    for question in data["questions"]:
        if question["id"] == qid:
            return question
    raise ProgramError(f"нет вопроса {qid}")


def active_stage(data: dict) -> dict | None:
    return next((s for s in data["stages"] if s["status"] in ACTIVE), None)


def next_pending(data: dict) -> dict | None:
    return next((s for s in data["stages"] if s["status"] == "pending"), None)


def is_last(data: dict, stage: dict) -> bool:
    later = data["stages"][data["stages"].index(stage) + 1:]
    return all(s["status"] == "skipped" for s in later)


def open_questions(data: dict, stage: dict | None = None) -> list[dict]:
    """Вопросы без ответа; со stage — те, что нужны до этого этапа (его и общие)."""
    return [q for q in data["questions"] if q.get("answer") is None
            and (stage is None or q.get("stage") in (None, stage["id"]))]


def cmd_mode(root: Path, mode: str) -> str:
    """Режим прогонов следующих этапов (D29: full — без вопросов брифинга, решения — допущениями в отчёте)."""
    if mode not in MODES:
        raise ProgramError(f"режим — один из: {', '.join(MODES)}")
    data = load(root)
    old = data.get("mode")
    data["mode"] = mode
    save(root, data)
    note = ""
    plan = root / (data.get("plan") or PLAN_NAME) if data.get("plan") else None
    if plan and plan.is_file():  # строка плана не должна спорить с program.json — оркестратор читает и её
        text = plan.read_text(encoding="utf-8")
        fixed = re.sub(r"^(-\s+Режим прогонов:\s*)\S+", lambda m: m.group(1) + mode, text, count=1, flags=re.M)
        if fixed != text:
            plan.write_text(fixed, encoding="utf-8")
            note = f"; в {data['plan']} тоже"
    return f"режим прогонов: {old} → {mode} (для этапов, которые ещё не начаты){note}"


def cmd_init(root: Path, goal: str, plan: str | None, mode: str) -> str:
    if program_path(root).exists():
        raise ProgramError("программа уже есть — продолжайте её (`program.py status`)")
    data = {"version": VERSION, "goal": goal, "plan": plan, "mode": mode, "createdAt": now(),
            "updatedAt": None, "stages": [], "questions": []}
    save(root, data)
    return f"программа создана: {program_path(root)}"


def cmd_stage_add(root: Path, sid: str, title: str, task: str, plan_ref: str | None,
                  criteria: list[str]) -> str:
    data = load(root)
    if any(s["id"] == sid for s in data["stages"]):
        raise ProgramError(f"этап {sid} уже есть")
    data["stages"].append({
        "id": sid, "title": title, "task": task, "planRef": plan_ref, "criteria": criteria,
        "status": "pending", "sessionId": None, "startedAt": None, "baseCommit": None,
        "adopted": False, "runStartedAt": None, "runDir": None, "finishedAt": None,
        "verdict": None, "note": None,
    })
    save(root, data)
    return f"этап {sid} добавлен"


def open_previous_sessions(stage: dict) -> list[dict]:
    """Прежние сессии этапа, которые не погашены (T21.3): живая старая сессия ломает сдачу — инцидент P0 пилота."""
    return [p for p in stage.get("previousSessions") or []
            if isinstance(p, dict) and p.get("sessionId") and not p.get("closed")]


def cmd_stage_set(root: Path, sid: str, status: str, note: str | None) -> str:
    data = load(root)
    stage = stage_of(data, sid)
    if status not in ("pending", "skipped", "passed"):
        raise ProgramError("вручную ставится только pending, skipped или passed")
    if status == "pending":  # повтор этапа: прошлый запуск забывается, но сессия помнится — её надо погасить (T21.3)
        if stage.get("sessionId"):
            stage.setdefault("previousSessions", []).append(
                {"sessionId": stage["sessionId"], "at": now(), "reason": note or "возврат в очередь", "closed": None})
        stage.update(sessionId=None, startedAt=None, baseCommit=None, adopted=False,
                     runStartedAt=None, runDir=None, finishedAt=None, verdict=None)
    if status == "passed":
        stage["finishedAt"] = stage.get("finishedAt") or now()
    stage["status"], stage["note"] = status, note
    save(root, data)
    out = f"этап {sid}: {status}"
    prev = open_previous_sessions(stage)
    if status == "pending" and prev:
        out += ("\nПрежняя сессия этапа осталась живой: " + ", ".join(p["sessionId"] for p in prev)
                + " — погасите её до нового запуска (T21.3): `stop_session`, затем `archive_session` "
                f"(mcp__ccd_session_mgmt__…), затем `program.py stage prev-done {sid}`. Иначе она может "
                "продолжить работу и сломать сдачу (инцидент P0: удаляла документы нового прогона).")
    return out


def cmd_stage_prev_done(root: Path, sid: str, session: str | None) -> str:
    """Отметка, что прежние сессии этапа погашены (T21.3): предупреждения в bind/check/watch снимаются."""
    data = load(root)
    stage = stage_of(data, sid)
    closed = 0
    for prev in stage.get("previousSessions") or []:
        if isinstance(prev, dict) and not prev.get("closed") and (session is None or prev.get("sessionId") == session):
            prev["closed"] = now()
            closed += 1
    if not closed:
        return f"этап {sid}: незакрытых прежних сессий нет"
    save(root, data)
    return f"этап {sid}: прежние сессии закрыты ({closed})"


MAX_PARTS = 3


# ── автономия программы (D30): оркестратор не ждёт владельца ─────────────────

MAX_REPAIRS = 1  # провал этапа: один автоматический ремонт в той же сессии, дальше — принять и долг


def autonomy(data: dict) -> str:
    """full (по умолчанию, D30) — действовать по рекомендациям; ask — спрашивать владельца, как до D30."""
    return data.get("autonomy") or "full"


def cmd_autonomy(root: Path, value: str) -> str:
    if value not in ("full", "ask"):
        raise ProgramError("автономия: full или ask")
    data = load(root)
    old = autonomy(data)
    data["autonomy"] = value
    save(root, data)
    return f"автономия программы: {old} → {value}"


def cmd_stage_repair(root: Path, sid: str) -> str:
    """Провален → снова идёт в той же сессии: оркестратор отправил ей причины. Один раз; дальше — accept."""
    data = load(root)
    stage = stage_of(data, sid)
    if stage["status"] != "failed":
        raise ProgramError(f"этап {sid} не провален — ремонтировать нечего")
    if stage.get("repairs", 0) >= MAX_REPAIRS:
        raise ProgramError(f"этап {sid} уже ремонтировали — теперь `stage accept {sid}` и этап долга (D30)")
    stage.setdefault("failures", []).append(stage.get("verdict"))
    stage.update(status="running", repairs=stage.get("repairs", 0) + 1, finishedAt=None, verdict=None)
    save(root, data)
    return f"этап {sid}: ремонт {stage['repairs']} — причины отправлены сессии этапа"


def cmd_stage_accept(root: Path, sid: str, note: str | None) -> str:
    """Провален → принят автоматически (D30): программа идёт дальше, провалы уходят в остаток и в этап долга."""
    data = load(root)
    stage = stage_of(data, sid)
    if stage["status"] != "failed":
        raise ProgramError(f"этап {sid} не провален")
    stage.update(status="passed", autoAccepted=True, finishedAt=stage.get("finishedAt") or now(),
                 note=note or "принят автоматически (D30): провалы — в этап долга с повторной слепой приёмкой")
    save(root, data)
    return f"этап {sid} принят автоматически; разберите остаток: `program.py leftovers {sid}`"


SELF_MATCH = re.compile(r"\bpgrep\b[^|;&]*\s-[a-zA-Z]*f|\bps\b[^|;&]*\|\s*grep|\bpidof\b")
BRACKET_TRICK = re.compile(r"\[[^\]\s]\]")
PROGRESS_HINT = re.compile(r"-mmin|-newer|\bstat\b|mtime|\bfind\b|\btail\b|\bnvidia-smi\b")


def probe_warnings(probe: str) -> list[str]:
    """Подозрительные проверки (D50): «жива» там, где работы нет, хуже, чем «упала» — оркестратор считает, что идёт тест."""
    out = []
    if SELF_MATCH.search(probe) and not BRACKET_TRICK.search(probe):
        out.append("`pgrep -f`/`ps | grep` находят саму проверку (её командная строка содержит образец; по ssh — ещё и удалённую "
                   "оболочку): ответ «жива» будет всегда. Образец в скобочной форме (`pgrep -f '[d]fab'`) или `tmux has-session -t <имя>`")
    if not PROGRESS_HINT.search(probe):
        out.append("проверка видит, что процесс есть, а не что тест идёт (зависший процесс или чужой с похожим именем — «жива»). "
                   "Добавь признак движения: свежий лог `find <лог> -mmin -15 | grep -q .`")
    return out


def cmd_job(root: Path, action: str, label: str | None, probe: str | None, until: str | None, check: bool = False) -> str:
    """Долгая работа вне чата (D47): сторож сам проверяет, жива ли она, — состояние прогона Autopilot о ней ничего не знает.

    check (D50, из командной строки): проверка запускается сразу при регистрации — не проходит значит, либо работы нет, либо
    проверка неверна: запись отклоняется, иначе сторож будет считать «упала» (или хуже — «жива») по пустому месту."""
    data = load(root)
    jobs = data.setdefault("jobs", [])
    if action == "list":
        return json.dumps(jobs, ensure_ascii=False, indent=2)
    if not label:
        raise ProgramError(f"job {action} требует --label")
    if action == "clear":
        data["jobs"] = [j for j in jobs if j["label"] != label]
        save(root, data)
        return f"задача {label} снята с наблюдения сторожа"
    if not probe or not until:
        raise ProgramError("job set требует --probe (команда: код 0, если работа жива) и --until (срок ISO)")
    if _instant(until).year == 1:
        raise ProgramError(f"--until: не дата ISO: {until}")
    notes = []
    if check:
        if _instant(until) <= datetime.now(timezone.utc):
            raise ProgramError(f"--until уже в прошлом ({until}): срок — конец всей работы с запасом, а не ближайшего окна")
        result = probe_job({"probe": probe})
        if result == "dead":
            raise ProgramError(f"проверка `{probe}` сейчас не проходит: либо работа не запущена (запусти и повтори), либо проверка "
                               "неверна — наблюдение не заведено. Проверь и обратный случай: при остановленной работе она должна падать")
        if result == "unknown":
            notes.append("проверку выполнить не вышло (нет связи/таймаут) — записано как есть, при первой проверке сторожа выяснится")
        notes += probe_warnings(probe)
    data["jobs"] = [j for j in jobs if j["label"] != label] + [{"label": label, "probe": probe, "until": until, "since": now()}]
    save(root, data)
    text = (f"задача {label} под наблюдением сторожа до {until}: проверка каждые 15 мин, упала — этап будят; "
            "срок вышел, а этап не сдан — будят тоже (продли `job set` или `job clear`)")
    return text + "".join(f"\nВНИМАНИЕ: {n}" for n in notes)


def cmd_owner_task(root: Path, action: str, text: str | None, stage: str | None,
                   kind: str | None = None, unwait: bool = False, note: str | None = None) -> str:
    """Задачи владельца (D30): то, что может сделать только он (пароль, аккаунт, необратимое) — программу не держат.

    kind=pause — «ожидание паузы» (D46): задача нужна, пока программа стоит; `resume` закрывает её сам.
    done связан с ожиданием этапа: если у этапа остался флаг `waiting`, а держать его нечему — подсказка или (--unwait) снятие.
    --note у done (T21.7) — пояснение к закрытию, как у `leftovers --done --note`: попадает в запись задачи и в отчёт."""
    data = load(root)
    tasks = data.setdefault("ownerTasks", [])
    if action == "add":
        if not text:
            raise ProgramError("owner-task add требует текст")
        if kind not in (None, "pause"):
            raise ProgramError("--kind: только pause")
        tid = f"T{len(tasks) + 1}"
        tasks.append({"id": tid, "text": text, "stage": stage, "at": now(), "done": None, "kind": kind})
        save(root, data)
        return f"задача владельца {tid}: {text}" + (" [ожидание паузы: закроет resume]" if kind else "")
    task = next((t for t in tasks if t["id"] == text), None)
    if task is None:
        raise ProgramError(f"нет задачи владельца {text}")
    task["done"] = now()
    if note:
        task["note"] = note
    save(root, data)
    out = f"задача владельца {task['id']} выполнена" + (f" (пояснение: {note})" if note else "")
    stage_row = stage_of(data, task["stage"]) if task.get("stage") in [s["id"] for s in data["stages"]] else active_stage(data)
    if stage_row is not None:
        _mine, waiting = run_waiting(root, stage_row)
        if waiting and not wait_blockers(data, stage_row):
            if unwait:
                try:
                    out += "\n" + cmd_stage_unwait(root, stage_row["id"])
                except ProgramError as error:
                    out += f"\nожидание этапа {stage_row['id']} не снято: {error}"
            else:
                out += (f"\nУ этапа {stage_row['id']} всё ещё стоит ожидание владельца ({waiting['kind']}), а открытых вопросов "
                        f"и задач для него нет. Снять: `program.py stage unwait {stage_row['id']}` "
                        f"(или сразу `owner-task done {task['id']} --unwait`)")
    return out


# ── ожидание владельца в состоянии прогона этапа (D46) ───────────────────────

QUIET_WRITE_SEC = 30  # этап, писавший в state.js позже, считается работающим: чужой флаг в этот момент не трогаем


def run_waiting(root: Path, stage: dict) -> tuple[dict | None, dict | None]:
    """(прогон этапа, его флаг waiting) — флаг только если он поставлен (есть kind)."""
    run = read_run(root)
    mine = run if run and run_belongs(stage, run) else None
    waiting = (mine or {}).get("waiting")
    return mine, waiting if isinstance(waiting, dict) and waiting.get("kind") else None


def wait_blockers(data: dict, stage: dict) -> list[str]:
    """Что ещё держит этап по существу: открытые вопросы владельца и его задачи этого этапа (кроме «ожидания паузы»)."""
    out = [f"вопрос {q['id']}" for q in open_questions(data, stage)]
    out += [f"задача владельца {t['id']}" for t in data.get("ownerTasks") or []
            if not t.get("done") and t.get("stage") == stage["id"] and t.get("kind") != "pause"]
    return out


def stale_wait(data: dict, stage: dict, waiting: dict) -> bool:
    """Флаг ожидания, которого ничто в программе не объясняет: нет вопросов и задач владельца, а ждёт он дольше напоминания
    сторожа (WATCH_REMIND_MIN). Обычный `ask` этапа до этого срока подсказки не вызывает."""
    open_tasks = [t for t in data.get("ownerTasks") or [] if not t.get("done")]
    waited = _minutes_since(waiting.get("since"))
    return not wait_blockers(data, stage) and not open_tasks and waited is not None and waited >= WATCH_REMIND_MIN


def cmd_stage_unwait(root: Path, sid: str, force: bool = False) -> str:
    """Снять ожидание владельца в state.js этапа тем же `ap.py answered`, что вызвал бы сам этап (интервал уйдёт в waits).

    Не снимает, пока есть открытые вопросы и задачи этого этапа или пока этап сам писал в state.js (--force — вопреки)."""
    data = load(root)
    stage = stage_of(data, sid)
    if stage["status"] not in ACTIVE:
        raise ProgramError(f"этап {sid} не идёт ({stage['status']}) — снимать нечего")
    mine, waiting = run_waiting(root, stage)
    if waiting is None:
        if stage["status"] == "waiting":
            stage["status"] = "running"
            save(root, data)
            return f"в state.js ожидания нет; статус этапа {sid}: waiting → running"
        return f"у этапа {sid} нет ожидания владельца — снимать нечего"
    blockers = wait_blockers(data, stage)
    if blockers and not force:
        raise ProgramError(f"этап {sid} ещё держит: {', '.join(blockers)} — закройте (или --force)")
    updated = _instant((mine or {}).get("updatedAt") or "")
    quiet = (datetime.now(timezone.utc) - updated).total_seconds() if updated.year > 1 else None
    if quiet is not None and quiet < QUIET_WRITE_SEC and not force:
        raise ProgramError(f"этап {sid} писал в state.js {int(quiet)} с назад — он работает; повторите через минуту (или --force)")
    ap = root / ".autopilot" / "ap.py"
    if not ap.is_file():
        raise ProgramError("нет .autopilot/ap.py — пусть сессия этапа сама выполнит `python .autopilot/ap.py answered`")
    done = subprocess.run([sys.executable, str(ap), "answered", "--no-serve"], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    _mine, still = run_waiting(root, stage)
    if done.returncode != 0 or still is not None:
        raise ProgramError("ap.py answered не снял ожидание: " + ((done.stderr or done.stdout).strip()[-300:] or f"код {done.returncode}"))
    if stage["status"] == "waiting":
        stage["status"] = "running"
        save(root, data)
    return f"ожидание {waiting['kind']} этапа {sid} снято (ap.py answered)"


# ── разрешения для проверки режима auto (D41) ────────────────────────────────
# Проверка режима auto в Claude Code (классификатор) не даёт скачать и запустить внешний установщик, поставить пакет
# или менять сервер — даже если это и есть цель проекта; режим full этого не меняет, а пересланное оркестратором «да»
# для неё не считается. Разрешение владельца записывается заранее в `autoMode` его ~/.claude/settings.json: настройки
# проекта классификатор не читает.

def claude_user_settings() -> Path:
    return kit_home() / ".claude" / "settings.json"


def merge_auto_mode(allow: list[str], environment: list[str]) -> bool:
    """Добавляет записи в autoMode.allow / autoMode.environment настроек пользователя Claude Code.

    Списка ещё нет — он начинается с "$defaults" (встроенные правила остаются); свой список владельца без "$defaults"
    не перестраиваем. Существующий файл — сначала копия .bak-<UTC>. True, если файл изменён."""
    path = claude_user_settings()
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as error:
        raise ProgramError(f"{path} не разбирается как JSON — разрешение не записано: {error}") from error
    auto = settings.setdefault("autoMode", {})
    for key, entries in (("allow", allow), ("environment", environment)):
        if entries:
            current = auto.setdefault(key, ["$defaults"])
            current.extend(e for e in entries if e not in current)
    text = json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == text:
            return False
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path.with_name(f"{path.name}.bak-{stamp}").write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def merge_permission_allow(permission: str) -> bool:
    """Точное правило `permissions.allow` в настройках пользователя Claude Code (T21.4б).

    Только по явному `approve add --permission` (решение владельца 07.11: автоматически — никогда; файл общий для всех
    профилей приложения на машине). Слияние JSON, копия прежнего `.bak-<UTC>`. True, если файл изменён."""
    path = claude_user_settings()
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as error:
        raise ProgramError(f"{path} не разбирается как JSON — правило не записано: {error}") from error
    if not isinstance(settings, dict):
        raise ProgramError(f"{path}: ожидался объект настроек — правило не записано")
    permissions = settings.get("permissions")
    if not isinstance(permissions, dict):  # в проде встречается "permissions": null
        permissions = settings["permissions"] = {}
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        allow = permissions["allow"] = []
    if permission in allow:
        return False
    allow.append(permission)
    text = json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path.with_name(f"{path.name}.bak-{stamp}").write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


# точное имя MCP-инструмента: mcp__<сервер>__<инструмент>; в сегменте — буквы/цифры/подчёркивания, дефис и точка
# между частями (реальные серверы: scheduled-tasks, Claude_Browser, ccd_session_mgmt — T21.13).
# Шаблоны (*), Bash(...), голые имена встроенных инструментов — отказ: правило было бы шире одного действия
_TOOL_SEGMENT = r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*"
PERMISSION_TOOL = re.compile(rf"^mcp__{_TOOL_SEGMENT}__{_TOOL_SEGMENT}$")


def cmd_approve(root: Path, action: str, text: str | None, environment: list[str], stage: str | None,
                permission: str | None = None) -> str:
    """Разрешение владельца на действие, которое проверка режима auto иначе заблокирует. Только после «да» самого
    владельца в чате оркестратора — его собственными словами.

    --permission (T21.4б, решение владельца: только явный флаг) — точное имя MCP-инструмента: дополнительно пишет
    правило в `permissions.allow` настроек пользователя, чтобы разрешение пережило новый чат («да» словами живёт
    только в текущем чате — инцидент T5 пилота)."""
    data = load(root)
    approvals = data.setdefault("approvals", [])
    if action == "list":
        return json.dumps(approvals, ensure_ascii=False, indent=2)
    if not text:
        raise ProgramError("approve add требует текст действия: что именно, где, откуда")
    if permission is not None and not PERMISSION_TOOL.match(permission):
        raise ProgramError(f"--permission: ожидается точное имя MCP-инструмента вида mcp__<сервер>__<инструмент> "
                           "(в сегменте буквы, цифры и подчёркивания, дефис и точка — между частями; примеры: "
                           "mcp__ccd_session_mgmt__clear_session, mcp__scheduled-tasks__create_scheduled_task). "
                           f"{permission!r} в этот формат не входит: шаблоны со звёздочкой, Bash(…) и голые имена "
                           "встроенных инструментов были бы шире одного действия")
    if stage is not None:
        stage_of(data, stage)
    changed = merge_auto_mode([f"Владелец заранее разрешил (программа Autopilot в папке {root}): {text}"], environment)
    permission_note = ""
    if permission is not None:
        added = merge_permission_allow(permission)
        permission_note = (f"\n{claude_user_settings()}: permissions.allow += {permission}"
                           + " (копия прежнего — settings.json.bak-<UTC>)" if added
                           else f"\n{claude_user_settings()}: правило {permission} уже было в permissions.allow")
    aid = f"A{len(approvals) + 1}"
    approvals.append({"id": aid, "action": text, "environment": environment, "stage": stage, "at": now(),
                      **({"permission": permission} if permission else {})})
    save(root, data)
    return (f"разрешение {aid} записано: {text}\n{claude_user_settings()}: "
            + ("autoMode дополнен" if changed else "такие записи уже были") + permission_note)


def cmd_stage_continue(root: Path, sid: str) -> str:
    """Этап сдан частично (D23): новая часть того же этапа доделывает отложенное. Не больше трёх частей."""
    data = load(root)
    stage = stage_of(data, sid)
    verdict = stage.get("verdict") or {}
    if stage["status"] != "passed" or not verdict.get("partial"):
        raise ProgramError(f"этап {sid} не сдан частично — продолжать нечего")
    part = stage.get("part", 1) + 1
    if part > MAX_PARTS:
        raise ProgramError(f"у этапа {sid} уже {MAX_PARTS} части — дальше решает владелец")
    later = [s["id"] for s in data["stages"][data["stages"].index(stage) + 1:] if s["status"] not in ("pending", "skipped")]
    if later:
        raise ProgramError(f"после {sid} уже начаты этапы {', '.join(later)} — продолжение не по порядку, решает владелец")
    stage.setdefault("parts", []).append({"part": part - 1, "runDir": stage.get("runDir"), "verdict": verdict})
    stage.update(part=part, carryOver=verdict.get("deferred") or [], status="pending", sessionId=None,
                 startedAt=None, baseCommit=None, adopted=False, runStartedAt=None, runDir=None,
                 finishedAt=None, verdict=None, note=None)
    save(root, data)
    return f"этап {sid}: часть {part} — доделать отложенное ({len(stage['carryOver'])})"


# ── план программы (D23): разбор, проверка, загрузка ────────────────────────

PLAN_NAME = "PROGRAM-PLAN.md"
PLAN_TEMPLATE = "program_plan.md"  # рядом с этим файлом
SIZES = ("T0", "T1", "T2", "T3")
DELIVERABLES = {"код": "code", "документы": "docs"}
STAGE_FIELDS = {"результат": "deliverable", "цель": "goal", "входит": "inScope", "не входит": "outScope",
                "критерии сдачи": "criteria", "зависит от": "dependsOn", "передаёт дальше": "handsOver",
                "размер": "size", "источники": "sources"}
PROGRAM_FIELDS = {"цель": "goal", "результат программы": "result", "режим прогонов": "mode", "источники": "sources"}
EMPTY = ("", "—", "-", "нет")


def plan_template_path() -> Path:
    return Path(__file__).with_name(PLAN_TEMPLATE)


def parse_plan(text: str) -> dict:
    """Markdown по шаблону program_plan.md → {title, program, constraints, questions, stages}. Комментарии пропускаются."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    plan = {"title": None, "program": {}, "constraints": [], "questions": [], "stages": []}
    section, stage, field = None, None, None
    for raw in text.splitlines():
        line = raw.rstrip()
        if m := re.match(r"^#\s+(?:План программы:\s*)?(.+)$", line):
            plan["title"] = m.group(1).strip()
        elif m := re.match(r"^##\s+(.+)$", line):
            section, stage, field = m.group(1).strip().lower(), None, None
        elif m := re.match(r"^###\s+([A-Za-zА-Яа-я0-9][\w.-]*)[.:]?\s+(.+)$", line) if section == "этапы" else None:
            stage = {"id": m.group(1).rstrip("."), "title": m.group(2).strip(), "criteria": []}
            plan["stages"].append(stage)
            field = None
        elif section == "программа" and (m := re.match(r"^-\s+([^:]+):\s*(.*)$", line)):
            key = PROGRAM_FIELDS.get(m.group(1).strip().lower())
            if key:
                plan["program"][key] = m.group(2).strip()
        elif section == "ограничения и решения" and (m := re.match(r"^-\s+(.+)$", line)):
            plan["constraints"].append(m.group(1).strip())
        elif section == "вопросы владельцу" and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and not re.fullmatch(r"[-: ]*", cells[0]) and cells[0].lower() != "id":
                plan["questions"].append({"id": cells[0], "question": cells[1], "recommended": cells[2], "stage": cells[3]})
        elif stage is not None and (m := re.match(r"^-\s+([^:]+):\s*(.*)$", line)):
            field = STAGE_FIELDS.get(m.group(1).strip().lower())
            if field and field != "criteria":
                stage[field] = m.group(2).strip()
            elif field == "criteria" and m.group(2).strip():
                stage["criteria"].append(m.group(2).strip())
        elif stage is not None and field == "criteria" and (m := re.match(r"^\s{2,}-\s+(.+)$", line)):
            stage["criteria"].append(m.group(1).strip())
    for s in plan["stages"]:
        deps = s.get("dependsOn", "")
        s["dependsOn"] = [] if deps.strip().lower() in EMPTY else [d.strip() for d in re.split(r"[,;]", deps) if d.strip()]
    return plan


def check_plan(plan: dict) -> dict:
    """Ошибки — план не загрузится; предупреждения — загрузится, но этапу будет хуже."""
    errors, warnings = [], []
    if not plan["program"].get("goal") and not plan.get("title"):
        errors.append("нет цели программы («## Программа» → «- Цель:»)")
    if plan["program"].get("mode") and plan["program"]["mode"] not in MODES:
        errors.append(f"режим прогонов «{plan['program']['mode']}» — ожидается {', '.join(MODES)}")
    if not plan["stages"]:
        errors.append("нет этапов («## Этапы» → «### M1. Название»)")
    seen: list[str] = []
    for s in plan["stages"]:
        sid = s["id"]
        if sid in seen:
            errors.append(f"{sid}: ID повторяется")
        if not s.get("goal"):
            errors.append(f"{sid}: нет цели")
        if not s["criteria"]:
            errors.append(f"{sid}: нет критериев сдачи — без них этап нельзя принять")
        if (s.get("deliverable") or "").lower() not in DELIVERABLES:
            errors.append(f"{sid}: «Результат» — «код» или «документы»")
        size = (s.get("size") or "").split()[0].upper() if s.get("size") else ""
        if size not in SIZES:
            errors.append(f"{sid}: «Размер» — T0, T1, T2 или T3 (больше T3 в один прогон не помещается — разбейте этап)")
        elif size == "T3":
            warnings.append(f"{sid}: размер T3 — предел одного прогона; лучше разбить на два этапа")
        for d in s["dependsOn"]:
            if d not in seen:
                errors.append(f"{sid}: зависит от {d} — такого этапа выше нет")
        if not s.get("outScope"):
            warnings.append(f"{sid}: нет «Не входит» — рамки размыты, прогон может разрастись")
        if not s.get("sources"):
            warnings.append(f"{sid}: нет «Источники» — прогон не узнает, какие документы читать")
        vague = [c for c in s["criteria"] if len(c.split()) < 3]
        if vague:
            warnings.append(f"{sid}: слишком короткий критерий: «{vague[0]}» — нужен проверяемый (команда, тест, поведение)")
        seen.append(sid)
    qids: list[str] = []
    for q in plan["questions"]:
        if q["id"] in qids:
            errors.append(f"вопрос {q['id']}: ID повторяется")
        qids.append(q["id"])
        if q["recommended"].strip() in EMPTY:
            errors.append(f"вопрос {q['id']}: нет рекомендуемого ответа")
        if q["stage"].lower() not in ("все", "—", "-", "") and q["stage"] not in seen:
            errors.append(f"вопрос {q['id']}: этапа {q['stage']} в плане нет")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stages": len(plan["stages"]),
            "questions": len(plan["questions"])}


def cmd_plan_check(path: Path) -> dict:
    return check_plan(parse_plan(Path(path).read_text(encoding="utf-8")))


def cmd_plan_load(root: Path, path: Path) -> list[str]:
    """Создаёт программу из плана или обновляет её: ждущие этапы переписываются, новые добавляются,
    начатые и сданные не трогаются; вопросы добавляются, у неотвеченных обновляется текст."""
    plan = parse_plan(Path(path).read_text(encoding="utf-8"))
    result = check_plan(plan)
    if not result["ok"]:
        raise ProgramError("план не прошёл проверку: " + "; ".join(result["errors"]))
    try:
        rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = Path(path).resolve().as_posix()
    lines = []
    if not program_path(root).exists():
        cmd_init(root, plan["program"].get("goal") or plan["title"], rel, plan["program"].get("mode") or "semi")
        lines.append("программа создана")
    data = load(root)
    data["plan"], data["constraints"] = rel, plan["constraints"]
    if plan["program"].get("result"):
        data["result"] = plan["program"]["result"]
    have = {s["id"]: s for s in data["stages"]}
    for p in plan["stages"]:
        fields = {"title": p["title"], "task": f"{p['id']}. {p['title']} — {p['goal']}", "planRef": f"{p['id']}. {p['title']}",
                  "criteria": p["criteria"], "deliverable": DELIVERABLES[p["deliverable"].lower()],
                  "inScope": p.get("inScope"), "outScope": p.get("outScope"), "dependsOn": p["dependsOn"],
                  "handsOver": None if (p.get("handsOver") or "").strip() in EMPTY else p.get("handsOver"),
                  "size": p["size"].split()[0].upper(), "sources": p.get("sources")}
        if p["id"] not in have:
            data["stages"].append({**fields, "id": p["id"], "status": "pending", "sessionId": None, "startedAt": None,
                                   "baseCommit": None, "adopted": False, "runStartedAt": None, "runDir": None,
                                   "finishedAt": None, "verdict": None, "note": None})
            lines.append(f"этап {p['id']} добавлен")
        elif have[p["id"]]["status"] == "pending":
            have[p["id"]].update(fields)
            lines.append(f"этап {p['id']} обновлён")
        else:
            lines.append(f"этап {p['id']} не тронут ({STATUS_RU[have[p['id']]['status']]})")
    asked = {q["id"]: q for q in data["questions"]}
    for q in plan["questions"]:
        stage = None if q["stage"].lower() in ("все", "—", "-", "") else q["stage"]
        if q["id"] not in asked:
            data["questions"].append({"id": q["id"], "question": q["question"], "recommended": q["recommended"],
                                      "stage": stage, "answer": None, "by": None, "at": None})
        elif asked[q["id"]].get("answer") is None:
            asked[q["id"]].update(question=q["question"], recommended=q["recommended"], stage=stage)
    save(root, data)
    lines.append(f"вопросов в плане: {len(plan['questions'])}; без ответа: {len(open_questions(data))}")
    lines += [f"предупреждение: {w}" for w in result["warnings"]]
    return lines


def cmd_ask(root: Path, qid: str, question: str, recommended: str, stage: str | None, approval: bool = False) -> str:
    data = load(root)
    if stage is not None:
        stage_of(data, stage)
    if any(q["id"] == qid for q in data["questions"]):
        raise ProgramError(f"вопрос {qid} уже есть")
    data["questions"].append({"id": qid, "question": question, "recommended": recommended,
                              "stage": stage, "answer": None, "by": None, "at": None,
                              **({"approval": True} if approval else {})})
    save(root, data)
    return f"вопрос {qid} записан"


def cmd_answer(root: Path, qid: str, answer: str | None, assumption: bool) -> str:
    data = load(root)
    question = question_of(data, qid)
    if question.get("approval") and (answer is None or assumption):
        # D41: разрешение — только словами владельца, не рекомендацией и не допущением
        raise ProgramError(f"{qid} — разрешение владельца: нужен --answer со словами владельца")
    text = answer if answer is not None else question["recommended"]
    if not text:
        raise ProgramError("ответ пустой")
    question.update(answer=text, by="assumption" if assumption else "owner", at=now())
    save(root, data)
    return f"{qid}: {text}"


# ── прогон Autopilot в папке ────────────────────────────────────────────────

def read_run(root: Path) -> dict | None:
    """Текущий прогон Autopilot из .autopilot/state.js («window.STATE = {...}») или None."""
    path = root / ".autopilot" / "state.js"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    body = raw.split("=", 1)[1] if "=" in raw.split("\n", 1)[0] else raw
    try:
        state = json.loads(body.strip().rstrip(";"))
    except ValueError as error:
        raise ProgramError(f".autopilot/state.js не разбирается: {error}") from error
    if not isinstance(state, dict):
        raise ProgramError(".autopilot/state.js: ожидается объект")
    return state


def git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    except OSError:
        return None
    return out.stdout if out.returncode == 0 else None


GIT_IDENTITY = {"user.name": "Autopilot", "user.email": "autopilot@localhost"}


def ensure_git_identity(root: Path) -> list[str]:
    """Нет user.name/user.email в git — ставит нейтральные в локальный конфиг репозитория (не --global).

    Возвращает, что поставлено. Не репозиторий, нет git, уже задано — пусто: чужие настройки не трогаем.
    Без этого коммиты программы и этапов падают, а оркестратор шёл с вопросом к владельцу (D32).
    """
    if git(root, "rev-parse", "--is-inside-work-tree") is None:
        return []
    done = []
    for key, value in GIT_IDENTITY.items():
        if (git(root, "config", key) or "").strip():
            continue
        if git(root, "config", "--local", key, value) is not None:
            done.append(f"{key}={value}")
    return done


def head_commit(root: Path) -> str | None:
    out = git(root, "rev-parse", "HEAD")
    return out.strip() if out else None


def cmd_start(root: Path, sid: str, adopt: bool) -> str:
    data = load(root)
    stage = stage_of(data, sid)
    busy = active_stage(data)
    if busy:
        raise ProgramError(f"этап {busy['id']} ещё идёт ({busy['status']}) — один прогон в папке за раз")
    if stage["status"] != "pending":
        raise ProgramError(f"этап {sid} в статусе {stage['status']}; повтор — `stage set {sid} --status pending`")
    earlier = data["stages"][:data["stages"].index(stage)]
    unfinished = [s["id"] for s in earlier if s["status"] not in ("passed", "skipped")]
    if unfinished:
        raise ProgramError(f"сначала этапы: {', '.join(unfinished)}")
    run = read_run(root)
    run_open = bool(run) and not run.get("finishedAt")
    if run_open and not adopt:
        raise ProgramError(f"в папке идёт прогон {run.get('dir')} — подхватить его этим этапом: `start {sid} --adopt`")
    if adopt and not run_open:
        raise ProgramError("подхватывать нечего: незаконченного прогона в папке нет")
    stage.update(status="running", startedAt=now(), baseCommit=head_commit(root), adopted=adopt,
                 runStartedAt=run.get("startedAt") if adopt else None,
                 runDir=run.get("dir") if adopt else None, finishedAt=None, verdict=None, note=None)
    save(root, data)
    return f"этап {sid} начат" + (f", подхвачен прогон {run.get('dir')}" if adopt else "")


def cmd_bind(root: Path, sid: str, session: str) -> str:
    data = load(root)
    stage = stage_of(data, sid)
    stage["sessionId"] = session
    save(root, data)
    out = f"этап {sid}: сессия {session}"
    prev = [p for p in open_previous_sessions(stage) if p["sessionId"] != session]
    if prev:
        out += ("\nПРЕДУПРЕЖДЕНИЕ (T21.3): прежняя сессия этапа не погашена: " + ", ".join(p["sessionId"] for p in prev)
                + " — она может писать в проект и сломать сдачу. Погасите (`stop_session`, затем `archive_session`) "
                f"и выполните `program.py stage prev-done {sid}`.")
    return out


# ── проверка сдачи ──────────────────────────────────────────────────────────

def run_belongs(stage: dict, run: dict) -> bool:
    if stage.get("adopted"):
        return run.get("startedAt") == stage.get("runStartedAt")
    started = run.get("startedAt") or ""
    return bool(stage.get("startedAt")) and _instant(started) >= _instant(stage["startedAt"])


def _instant(stamp: str) -> datetime:
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def run_gate(root: Path, allow_no_tests: bool = False) -> tuple[bool | None, str]:
    """(None, …) — гейт не настроен; иначе (прошёл ли, хвост вывода).

    allow_no_tests — для документных прогонов (T21.1): pytest-код 5 «тестов нет» не считается провалом вердикта,
    как в хуке по D14; строгий режим без флага не слабеет.
    """
    if not (root / ".autopilot-kit" / "project.toml").is_file():
        return None, "гейт не настроен (.autopilot-kit/project.toml нет)"
    script = gate_script()
    if not script.is_file():
        return False, f"гейт не установлен: {script} — запустите python -m kit install"
    cmd = [sys.executable, str(script), "--project", str(root)]
    if allow_no_tests:
        cmd.append("--allow-no-tests")
    out = subprocess.run(cmd, cwd=root,
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return out.returncode == 0, (out.stdout + out.stderr)[-GATE_TAIL:]


def flaky_since(root: Path, started: str | None) -> list[str]:
    """Нестабильные тесты, которые гейт отметил после старта этапа (.autopilot-kit/flaky.json, D41)."""
    try:
        tests = json.loads((root / ".autopilot-kit" / "flaky.json").read_text(encoding="utf-8"))["tests"]
        since = _instant(started) if started else None
        return [f"{name} (упал и прошёл при повторе: {entry.get('count', 1)} раз)" for name, entry in tests.items()
                if since is None or _instant(str(entry.get("last") or "")) >= since]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def landing_after(root: Path, base: str | None) -> bool | None:
    """Есть ли коммит «Autopilot: сборка сдана» после base; None — проверить нельзя (нет git)."""
    if head_commit(root) is None:
        return None
    span = f"{base}..HEAD" if base else "HEAD"
    out = git(root, "log", "--format=%s", span)
    return out is not None and any(line.strip() == LANDING_SUBJECT for line in out.splitlines())


def next_step_block(root: Path) -> str | None:
    """Раздел «## Следующий шаг» из .autopilot/PROGRESS.md (без заголовка) или None."""
    path = root / ".autopilot" / "PROGRESS.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(NEXT_STEP_HEADING)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else None


def evaluate(root: Path, data: dict, stage: dict, with_gate: bool = True) -> dict:
    run = read_run(root)
    if stage["status"] not in ACTIVE:
        return {"stage": stage["id"], "verdict": "not_started",
                "why": f"этап в статусе {stage['status']} — сначала `start`"}
    if run is None or not run_belongs(stage, run):
        return {"stage": stage["id"], "verdict": "not_started", "why": "прогон этапа ещё не начат (ap.py init не было)"}
    base = {"stage": stage["id"], "runDir": run.get("dir"), "runStartedAt": run.get("startedAt")}
    waiting = run.get("waiting")
    if isinstance(waiting, dict) and waiting.get("kind"):
        return {**base, "verdict": "waiting", "kind": waiting.get("kind"), "note": waiting.get("note")}
    if not run.get("finishedAt"):
        current = next((s.get("id") for s in run.get("stages") or [] if s.get("status") == "active"), None)
        return {**base, "verdict": "unfinished", "autopilotStage": current}
    reasons: list[str] = []
    warnings: list[str] = []
    for s in run.get("stages") or []:
        if s.get("status") == "failed":
            reasons.append(f"этап Autopilot {s.get('id')} провален" + (f": {s['note']}" if s.get("note") else ""))
    for t in run.get("tickets") or []:
        if t.get("status") != "done":
            reasons.append(f"таск {t.get('id')} не сдан ({t.get('status')})")
    gates = run.get("gates") or {}
    names = {"G2": "покрытие спецификации", "G3": "трасса плана", "G4": "слепая приёмка"}
    for gid, name in names.items():
        if gid in gates and not gates[gid].get("ok"):
            reasons.append(f"{gid} ({name}) не пройден")
    if "G4" not in gates:
        reasons.append("слепой приёмки (G4) не было")
    mismatches = (run.get("blind") or {}).get("mismatches") or []
    reasons.extend(f"расхождение слепой приёмки: {m}" for m in mismatches)
    # T21.1: документный прогон (deliverable docs у прогона или у этапа плана) не обязан иметь тесты —
    # пустой сбор pytest не провал вердикта, как в хуке по D14
    docs = run.get("deliverable") == "docs" or stage.get("deliverable") == "docs"
    gate_ok, gate_out = run_gate(root, allow_no_tests=docs) if with_gate else (None, "гейт не запускался (--no-gate)")
    if gate_ok is False:
        reasons.append("гейт проекта не пройден")
    elif gate_ok is None:
        warnings.append(gate_out)
    landed = landing_after(root, stage.get("baseCommit"))
    if landed is False:
        reasons.append(f"после старта этапа нет коммита «{LANDING_SUBJECT}»")
    elif landed is None:
        warnings.append("git нет — коммит сдачи не проверен")
    step = next_step_block(root)
    if step is None and not is_last(data, stage):
        reasons.append(f"в .autopilot/PROGRESS.md нет раздела «{NEXT_STEP_HEADING}»")
    for prev in open_previous_sessions(stage):
        warnings.append(f"прежняя сессия этапа ({prev['sessionId']}, {prev.get('reason') or 'возврат в очередь'}) не погашена "
                        f"— она может писать в проект и сломать сдачу (T21.3): stop_session + archive_session, затем "
                        f"`stage prev-done {stage['id']}`")
    # D23: отложенное прогоном требование брифа — этап сдан не целиком; заглушка — сделано, ждёт данных владельца
    req = [r for r in run.get("reqList") or [] if isinstance(r, dict)]
    pick = lambda st: [{k: r.get(k) for k in ("id", "text", "why")} for r in req if r.get("status") == st]
    deferred, placeholders = pick("deferred"), pick("placeholder")
    return {
        **base, "verdict": "failed" if reasons else "passed", "reasons": reasons, "warnings": warnings,
        "partial": bool(deferred) and not reasons, "deferred": deferred, "placeholders": placeholders,
        "result": run.get("result"), "deliverable": run.get("deliverable"), "tests": run.get("tests"),
        "assumptions": (run.get("debt") or {}).get("assumptions") or [],
        "concerns": run.get("concerns") or [], "left": run.get("report") or [],
        "flaky": flaky_since(root, stage.get("startedAt")),
        "gate": gate_out if gate_ok is False else None, "nextStep": step,
    }


def cmd_check(root: Path, sid: str | None, record: bool, with_gate: bool) -> dict:
    data = load(root)
    stage = stage_of(data, sid) if sid else active_stage(data)
    if stage is None:
        raise ProgramError("нет идущего этапа — укажите ID")
    verdict = evaluate(root, data, stage, with_gate)
    if record and stage["status"] in ACTIVE and verdict["verdict"] != "not_started":
        stage["runStartedAt"] = verdict.get("runStartedAt") or stage.get("runStartedAt")
        stage["runDir"] = verdict.get("runDir") or stage.get("runDir")
        stage["status"] = {"waiting": "waiting", "unfinished": "running"}.get(verdict["verdict"], verdict["verdict"])
        if verdict["verdict"] in ("passed", "failed"):
            stage["finishedAt"] = now()
            stage["verdict"] = verdict
        save(root, data)
    return verdict


# ── задание этапа, вид и отчёт ──────────────────────────────────────────────

def decisions(data: dict) -> list[dict]:
    return [q for q in data["questions"] if q.get("answer") is not None]


def decisions_block(data: dict) -> list[str]:
    made = decisions(data)
    if not made:
        return []
    lines = ["Решения владельца (из `.autopilot/program.json`, не спрашивать повторно):"]
    for q in made:
        tag = (" (допущение, владелец может поменять)" if q.get("by") == "assumption" else
               " (автоответ по рекомендации, владелец может поменять)" if q.get("by") == "auto" else "")
        lines.append(f"- {q['id']}. {q['question']} — {q['answer']}{tag}")
    return lines


def brief(data: dict, stage: dict) -> str:
    """Аргументы Autopilot для этапа: режим, задание по плану, рамки, критерии, связи с этапами, источники, решения."""
    where = f" — по плану `{data['plan']}`" if data.get("plan") else ""
    if stage.get("planRef"):
        where += f", раздел «{stage['planRef']}»"
    lines = [f"{data['mode']}: {stage['task']}{where}", ""]
    if stage.get("carryOver"):  # продолжение этапа: сначала то, что прошлый прогон отложил
        lines.append(f"Это продолжение этапа {stage['id']} (часть {stage.get('part', 2)}). Прошлый прогон сдал этап "
                     "не целиком — доделать отложенное, сделанное не переделывать:")
        lines += [f"- {r.get('id')}: {r.get('text')}" + (f" (отложено: {r['why']})" if r.get("why") else "")
                  for r in stage["carryOver"]] + [""]
    if stage.get("deliverable") == "docs":
        lines += ["Результат этапа — документы, код продукта не пишется.", ""]
    for label, key in (("Входит в этап", "inScope"), ("Не входит в этап", "outScope")):
        if stage.get(key):
            lines += [f"{label}: {stage[key]}"]
    if stage.get("inScope") or stage.get("outScope"):
        lines.append("")
    if stage.get("criteria"):
        lines += ["Критерии сдачи этапа:"] + [f"- {c}" for c in stage["criteria"]] + [""]
    deps = [s for s in data["stages"] if s["id"] in (stage.get("dependsOn") or []) and s.get("handsOver")]
    if deps:
        lines += ["Опирается на сданные этапы:"] + [f"- {s['id']}: {s['handsOver']}" for s in deps] + [""]
    if stage.get("handsOver"):
        lines += [f"Передаёт следующим этапам: {stage['handsOver']}", ""]
    if stage.get("sources"):
        lines += [f"Прочитать до спецификации: {stage['sources']}", ""]
    if data.get("constraints"):
        lines += ["Ограничения и решения программы:"] + [f"- {c}" for c in data["constraints"]] + [""]
    granted = [a for a in data.get("approvals") or [] if a.get("stage") in (None, stage["id"])]
    if granted:  # D41: проверка режима auto их пропустит, если в задании исполнителю действие названо так же точно
        lines += ["Заранее разрешено владельцем (записано в его настройках режима auto, D41) — в задании исполнителю "
                  "называй действие так же точно:"] + [f"- {a['action']}" for a in granted] + [""]
    lines += decisions_block(data)
    return "\n".join(lines).rstrip() + "\n"


STAGE_RULES = (
    "Владелец читает только чат оркестратора; оркестратор пересылает ему твои вопросы и возвращает ответы сюда.\n"
    "- Долгая работа вне чата (тест, сборка, драйвер на сервере — всё, что идёт дольше часа без твоих действий): **до конца "
    "хода** (а) заведи наблюдение, которое разбудит тебя при остановке (фоновая задача с проверкой раз в минуту), и (б) "
    "зарегистрируй проверку у сторожа: `python \"{program_py}\" --project . job set --label <метка> --probe \"<команда: код 0, "
    "если работа жива>\" --until <срок ISO>` — сторож проверяет её сам каждые 15 минут и разбудит тебя, если она упала. "
    "Перезапустил работу — наблюдение заводи заново: прежнее умирает с перезапуском. Закончилась — `job clear <метка>`. "
    "Ход с идущей долгой работой без наблюдения и записи не заканчивай: обрыв в это время никто не увидит (D47). "
    "Правила проверки (D50): (1) она должна падать, когда теста нет, — проверь обратный случай, а не только «сейчас жива» "
    "(`pgrep -f` и `ps | grep` находят саму проверку; по ssh — ещё и удалённую оболочку: образец в скобках `'[d]fab'` или "
    "`tmux has-session`); (2) она ловит движение, а не наличие процесса: свежий лог `find <лог> -mmin -15 | grep -q .` — "
    "зависший процесс или чужой с похожим именем не должен давать «жива»; (3) она покрывает всю цепочку окон работ, а не "
    "первое (после него — другая сессия/другой процесс); (4) `--until` — конец ВСЕЙ цепочки с запасом на несколько часов, "
    "не конец ближайшего окна; цепочка удлинилась — `job set` заново, сторож будит и при вышедшем сроке, но к этому лучше "
    "не доводить; (5) перед концом хода — `job list`: запись есть, срок покрывает работу.\n"
    "- Фоновые субагенты приложения умирают на границе хода/сессии (T21.10): запустил фонового исполнителя — **не заканчивай "
    "ход**, пока он не завершился и его результат не лёг в дерево. Приложение всё же оборвало его (сообщение вида "
    "«Background agent … didn't finish before the previous session ended») — работа НЕ считается сделанной: перезапусти её "
    "или выполни сам в этом же ходе. «Заявил фоновую работу и закончил ход» — запрещено: мёртвый исполнитель оставляет этап "
    "простаивать, а оркестратор сверяет такие заявления по `list_events` и по дереву (коммиты, число тестов), а не по отчёту.\n"
    "- Дашборд этого прогона держи в боковой панели — владелец, заглянув в этот чат, видит подробности этапа. Когда Autopilot "
    "начал прогон (после `ap.py init`: появился `.autopilot/dashboard.html`), открой его: вкладка с адресом {dashboard} уже "
    "есть (`mcp__Claude_Browser__tabs_context`; нет такого инструмента в этом билде — `mcp__Claude_Browser__preview_list`, D48) "
    "— выбери её (`tabs_select`; нет — `mcp__ccd_view__show_pane` с `tab_id` вкладки), иначе `mcp__Claude_Browser__preview_start` "
    "с `url` = {dashboard}; **если `preview_start` в этом билде принимает только `name`** (T21.11) — открой штатную конфигурацию "
    "kit: выполни `python \"{program_py}\" --project . page --launch` (пишет конфигурацию `autopilot-program` в "
    "`.claude/launch.json`, не трогая чужие) и `preview_start` с `name: \"autopilot-program\"` — панель откроет страницу "
    "программы, а с неё перейди на дашборд прогона (ссылка на странице; или `mcp__Claude_Browser__preview_eval` "
    "`location.replace('{dashboard}')`). Своего `http.server` и своих конфигураций запуска не заводи: сервер kit отдаёт обе "
    "страницы и поднимается заново каждой командой программы. Затем **покажи панель**: `mcp__ccd_view__show_pane` с "
    "`pane: \"preview\"` (без этого вкладка работает невидимо). И в конце каждого своего хода снова `show_pane` с "
    "`pane: \"preview\"` — если владелец смотрит этот чат, дашборд будет справа; фокус у другого чата это не отнимает. "
    "Инструменты загрузи одним `ToolSearch` (нет `ToolSearch` в билде — они уже загружены). В браузере компьютера "
    "дашборд НЕ открывай и не проси владельца открыть: `start`, `explorer`, `cmd /c start`, `open`, `Invoke-Item`, "
    "`webbrowser` запрещены (T21.15) — только боковая панель приложения; ссылка в тексте твоего сообщения — это текст, "
    "а не запуск браузера. Не вышло — продолжай без панели.\n"
    "- Когда Autopilot ждёт владельца (`ap.py ask`), задай вопрос текстом в чате — не интерактивной карточкой и не "
    "инструментом вопросов: карточку оркестратор не видит. Последней строкой вопроса напиши: «Отвечать — в чате "
    "оркестратора (его название начинается с «Оркестратор ·»); он передаст ответ сюда.» — и остановись.\n"
    "- Сразу после вопроса, до конца хода, отправь его оркестратору сам: `mcp__ccd_session_mgmt__send_message` с "
    "`session_id: \"parent\"` (загрузи через ToolSearch, если нужно; нет ToolSearch в билде — инструмент уже загружен) — "
    "«Вопрос этапа {stage} · <брифинг | действие | …>», "
    "вопрос дословно и твоя рекомендация. И уведомление владельцу одной строкой: «Этап {stage} спрашивает — "
    "ответь в чате оркестратора» (`PushNotification`; нет его в билде — `mcp__ccd_turn__wrap_up` с `ask` и `blocked: true`, D48). "
    "Так вопрос дойдёт, даже если оркестратор давно не просыпался, а ожидание в state.js "
    "закрылось, пока ты делал другие тикеты.\n"
    "- Сдав этап (коммит «Autopilot: сборка сдана» сделан), так же отправь оркестратору (`session_id: \"parent\"`) "
    "«Этап {stage} сдан: <итог одной строкой>» и уведомление владельцу: «Этап {stage} сдан. Если оркестратор не сообщит о "
    "следующем этапе — напиши ему «продолжай»».\n"
    "- Ответ придёт сообщением от оркестратора. Первой строкой своего ответа напиши: «Ответ владельца получен через "
    "оркестратора: <ответ кратко>» — и продолжай. Если владелец позже повторит ответ здесь, напрямую, не переделывай "
    "уже сделанное: сверь с полученным ответом и продолжай.\n"
    "- Если проверка прав Claude Code отказала («denied by the Claude Code auto mode classifier»), не обходи её. Отправь "
    "оркестратору «Вопрос этапа {stage} · действие» с пометкой «блок проверки прав (D41)»: что именно отклонено и готовую "
    "фразу, которую владелец сам напишет в этом чате, — с точным действием, адресом и сервером. Делай остальные тикеты.\n"
    "- Ожидание владельца (`ap.py ask`) не держи без срока и без причины: `--note` — что именно ждёшь и от кого, сразу после "
    "вопроса закончи ход (флаг в state.js не повод оставаться в ходе). Когда владелец сказал «продолжай», «стоп снят», дал новую "
    "задачу или ответ — **сам** выполни `python .autopilot/ap.py answered` до первой работы, даже если оркестратор уже снял "
    "паузу: флаг `waiting` оставляет дашборд оранжевым, хотя этап работает. Пришло «стоп владельца снят» — то же самое.\n"
    "- `.autopilot/program.json` и `.autopilot/PROGRAM.md` ведёт оркестратор — не правь и не коммить их. Ничего не пушь.\n"
)


# сигнал продолжения после лимита: его шлёт задача по расписанию в чат этапа (D22)
RESUME_SIGNAL = "Лимит подписки восстановился — продолжай прогон этапа (или начинай, если ещё не начинал)."


def stage_prompt(data: dict, stage: dict, manual: bool = False, after_signal: bool = False,
                 dashboard: str | None = None) -> str:
    """Задание сессии этапа. manual — две строки для ручного запуска (Codex): /autopilot-roles и /autopilot.

    after_signal — этап создан заранее, на паузе по лимиту: сейчас только ответить и ждать сигнала (D22, спайк L4).
    """
    if after_signal and not manual:
        wait = ("Сейчас лимит подписки почти исчерпан, поэтому этап начнётся по сигналу. Ничего не вызывай и не читай: "
                "ответь одной строкой «Этап ждёт сигнала после сброса лимита» и закончи ход. Когда придёт сообщение "
                f"«{RESUME_SIGNAL}», выполни задание ниже.\n\n")
        return wait + stage_prompt(data, stage, manual=False, dashboard=dashboard)
    if manual:
        return "/autopilot-roles\n/autopilot" + ("" if stage.get("adopted") else " " + brief(data, stage))
    head = (f"Ты — сессия этапа {stage['id']} программы прогонов Autopilot. Оркестратор — другая сессия; "
            "итог он проверит по файлам `.autopilot/`, гейту и git.\n\n"
            "1. Вызови навык `autopilot-roles` (инструмент Skill).\n")
    if stage.get("adopted"):
        body = ("2. Вызови навык `autopilot-stage` (инструмент Skill) без аргументов — это копия `/autopilot` для "
                "сессий этапов; он продолжит начатый прогон по `.autopilot/state.js`.\n\n"
                + "\n".join(decisions_block(data)))
    else:
        body = ("2. Вызови навык `autopilot-stage` (инструмент Skill) — это копия `/autopilot` для сессий этапов — "
                "с аргументами между линиями ниже, дальше веди прогон по нему, как по `/autopilot`.\n\n"
                "-----\n" + brief(data, stage) + "-----\n")
    rules = STAGE_RULES.replace("{program_py}", Path(__file__).resolve().as_posix()).replace("{stage}", stage["id"]).replace("{dashboard}", dashboard or "дашборда прогона (`.autopilot/dashboard.html`)")
    return head + body.rstrip() + "\n\n" + rules


def cmd_next(root: Path) -> dict:
    data = load(root)
    busy = active_stage(data)
    if busy:
        return {"ready": False, "why": f"этап {busy['id']} ещё идёт ({busy['status']})"}
    stage = next_pending(data)
    if stage is None:
        return {"ready": False, "why": "этапов не осталось — `program.py report`"}
    untriaged = [s for s in data["stages"] if s["status"] == "passed" and leftovers_of(s)["count"] and not s.get("leftoversTriaged")]
    if untriaged:
        first = untriaged[0]
        return {"ready": False, "stage": stage["id"], "untriaged": [s["id"] for s in untriaged],
                "why": (f"этап {first['id']} сдан с остатком ({leftovers_of(first)['summary']}) — сначала разберите его: "
                        f"`program.py leftovers {first['id']}`, разложите по плану, затем "
                        f"`program.py leftovers {first['id']} --done --note \"<куда что ушло>\"`")}
    missing = open_questions(data, stage)
    approvals = [q for q in missing if q.get("approval")]
    if approvals:  # D41: разрешение для проверки режима auto даёт только владелец — этап без него не начинается
        return {"ready": False, "stage": stage["id"],
                "why": "этапу нужно разрешение владельца (D41) — его не взять рекомендацией",
                "approvals": [{k: q[k] for k in ("id", "question", "recommended")} for q in approvals]}
    if missing and autonomy(data) == "full":  # D30: этап не ждёт владельца — ответ по рекомендации, владелец может поменять
        for q in missing:
            q.update(answer=q["recommended"], by="auto", at=now())
        save(root, data)
        auto = [{k: q[k] for k in ("id", "question", "answer")} for q in missing]
        return {"ready": True, "stage": stage["id"], "title": stage["title"], "brief": brief(data, stage), "autoAnswered": auto}
    if missing:
        return {"ready": False, "stage": stage["id"], "why": "нет ответов владельца на вопросы до этапа",
                "questions": [{k: q[k] for k in ("id", "question", "recommended")} for q in missing]}
    return {"ready": True, "stage": stage["id"], "title": stage["title"], "brief": brief(data, stage)}


# ── остаток сданного этапа (D26) ─────────────────────────────────────────────

BLIND_PREFIX = "расхождение слепой приёмки: "


def leftovers_of(stage: dict) -> dict:
    """Всё, что сданный этап оставил: расхождения приёмки, причины провала (если принят как есть), «осталось после ревью»,
    замечания ревьюеров, отложенные требования, заглушки. Из вердикта program.py check — детерминированно."""
    v = stage.get("verdict") or {}
    reasons = v.get("reasons") or []
    accepted = v.get("verdict") == "failed" and stage["status"] == "passed"
    groups = {
        "blind": [r[len(BLIND_PREFIX):] for r in reasons if r.startswith(BLIND_PREFIX)],
        "failures": [r for r in reasons if not r.startswith(BLIND_PREFIX)] if accepted else [],
        "left": list(v.get("left") or []),
        "concerns": list(v.get("concerns") or []),
        "deferred": [f"{d.get('id')}: {d.get('text')}" + (f" (отложено: {d['why']})" if d.get("why") else "")
                     for d in v.get("deferred") or []],
        "placeholders": [f"{d.get('id')}: {d.get('text')}" for d in v.get("placeholders") or []],
        "flaky": list(v.get("flaky") or []),
    }
    names = {"blind": "расхождений приёмки", "failures": "причин провала", "left": "осталось после ревью",
             "concerns": "замечаний", "deferred": "отложено", "placeholders": "заглушек", "flaky": "нестабильных тестов"}
    count = sum(len(items) for items in groups.values())
    summary = ", ".join(f"{names[k]} {len(items)}" for k, items in groups.items() if items) or "пусто"
    return {"stage": stage["id"], "acceptedAsIs": accepted, "count": count, "summary": summary,
            "triaged": stage.get("leftoversTriaged"), **groups}


def cmd_leftovers(root: Path, sid: str, done: bool, note: str | None) -> dict | str:
    data = load(root)
    stage = stage_of(data, sid)
    if stage["status"] != "passed":
        raise ProgramError(f"этап {sid} не сдан — остаток разбирается после сдачи")
    if not done:
        return leftovers_of(stage)
    if not note:
        raise ProgramError("--done требует --note: куда ушёл остаток (этапы плана, новый этап долга, вопросы владельцу)")
    stage["leftoversTriaged"] = {"at": now(), "note": note}
    save(root, data)
    return f"остаток этапа {sid} разобран: {note}"


# ── резерв сессий этапов (D31): этап начинается сообщением, а не start_session ──
# Из хода, начатого сообщением, приложение не запускает сессии (спайк L4). Оркестратор держит готовые резервные
# сессии, пока может их запускать, и начинает этап, отправив резервной задание — сообщения можно слать из любого хода.

POOL_SIZE = 2
POOL_CAP = 4   # D57: резерв растёт вместе с числом неначатых этапов, но не больше — простаивающие сессии тоже занимают память
SIGNAL_HEAD = "Задание этапа"
# D40: запускать сессии приложение даёт только в ходе со словами владельца — резерв из хода по сообщению не пополнить.
# Поэтому чат сданного этапа переиспользуется: оркестратор очищает его (`clear_session`, работает из хода по сообщению,
# спайк L6) и шлёт ему задание следующего этапа. Резерв остаётся запасом на случай, когда очистка отказана.


def recyclable(data: dict) -> list[dict]:
    """Сданные этапы, чей чат можно очистить и отдать следующему этапу: сессия Claude Code, ещё не переиспользована,
    не занята идущим этапом и не чат оркестратора. Свежие — первыми."""
    busy = {s.get("sessionId") for s in data["stages"] if s["status"] in ACTIVE}
    busy.add(data.get("orchestrator"))
    seen, out = set(), []
    for stage in reversed(data["stages"]):
        session = str(stage.get("sessionId") or "")
        if (stage["status"] == "passed" and session.startswith("local_") and not stage.get("recycled")
                and session not in busy and session not in seen):
            seen.add(session)
            out.append(stage)
    return out


def pool_target(data: dict) -> int:
    """Сколько резервных сессий держать (D57): пополнить можно только в ходе владельца, а каждый этап, у которого очистка чата
    сданного этапа отказана, берёт одну сессию — резерв из двух кончался через два этапа, и программа из восьми этапов вставала."""
    pending = sum(1 for s in data["stages"] if s["status"] == "pending")
    return min(POOL_CAP, max(POOL_SIZE, pending))


def pool_prompt(data: dict) -> str:
    return (f"Ты — резервная сессия этапа программы прогонов Autopilot «{data['goal'][:80]}». Сейчас ничего не вызывай и "
            "не читай: ответь одной строкой «Резерв готов» и закончи ход. Когда придёт сообщение, начинающееся с "
            f"«{SIGNAL_HEAD}», переименуй этот чат (`mcp__ccd_session_mgmt__set_session_title` для `self`; загрузи через "
            "ToolSearch, нет его в билде — уже загружен) в «Этап <ID>: <название>» из первой строки сообщения и выполни задание из сообщения целиком.\n")


def cmd_pool(root: Path, action: str, session: str | None, as_json: bool = False) -> str:
    data = load(root)
    if action == "take" and as_json:
        # D40: сначала чат сданного этапа (очистить перед заданием), затем свежий резерв
        for stage in recyclable(data):
            stage["recycled"] = now()
            save(root, data)
            return json.dumps({"sessionId": stage["sessionId"], "clear": True, "from": f"этап {stage['id']}"},
                              ensure_ascii=False)
        pool = data.get("pool") or []
        if not pool:
            raise ProgramError("резерв пуст и чатов сданных этапов нет — запустите сессию этапа (`start_session`, "
                               "только в ходе владельца) или попросите владельца написать «продолжай»")
        taken = pool.pop(0)
        save(root, data)
        return json.dumps({"sessionId": taken["sessionId"], "clear": False, "from": "резерв"}, ensure_ascii=False)
    pool = data.setdefault("pool", [])
    if action == "add":
        if not session:
            raise ProgramError("pool add требует id сессии")
        if all(p["sessionId"] != session for p in pool):
            pool.append({"sessionId": session, "at": now()})
            save(root, data)
        return f"резерв: {len(pool)} (добавлена {session})"
    if action == "drop":
        if not session:
            raise ProgramError("pool drop требует id сессии")
        left = [p for p in pool if p["sessionId"] != session]
        if len(left) == len(pool):
            return f"резерв: {len(pool)} (записи {session} не было)"
        data["pool"] = left
        save(root, data)
        return f"резерв: {len(left)} (убрана {session})"
    if action == "take":
        if not pool:
            raise ProgramError("резерв пуст — запустите сессию этапа обычным способом или долейте резерв")
        taken = pool.pop(0)
        save(root, data)
        return taken["sessionId"]
    if action == "need":
        return str(max(0, pool_target(data) - len(pool)))
    if action == "release":
        # D57: очистку отказали временно («у сессии есть живая работа») — сессия не потеряна, к следующему этапу её можно очистить
        if not session:
            raise ProgramError("pool release требует id сессии")
        released = [s for s in data["stages"] if s.get("sessionId") == session and s.get("recycled")]
        for stage in released:
            stage.pop("recycled", None)
        if released:
            save(root, data)
        return f"чат {session}: снова доступен для очистки ({len(released)})" if released else f"чат {session}: отметки «использован» не было"
    return json.dumps(pool, ensure_ascii=False)


def cmd_signal(root: Path, sid: str) -> str:
    """Сообщение резервной сессии: заголовок с ID и названием, затем полное задание этапа (как `prompt`)."""
    data = load(root)
    stage = stage_of(data, sid)
    # после очистки (D40) у чата нет текста pool-prompt — переименование сказано в самом сигнале
    rename = (f"Переименуй этот чат в «Этап {stage['id']}: {stage['title']}» (`mcp__ccd_session_mgmt__set_session_title` "
              "для `self`; загрузи через ToolSearch, нет его в билде — уже загружен) и выполни задание ниже целиком.\n\n")
    return f"{SIGNAL_HEAD} {stage['id']}: {stage['title']}\n\n" + rename + cmd_prompt(root, sid, manual=False)


def _file_mentions(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def cmd_setup_check(root: Path) -> str:
    """JSON: настроена ли папка проекта для kit. `configured` — есть `.autopilot-kit/project.toml` (это условие для
    настройки при старте программы, D39); `missing` — чего ещё нет из файлов init (для отчёта); `git` — репозиторий ли это."""
    items = {
        ".autopilot-kit/project.toml": (root / ".autopilot-kit" / "project.toml").is_file(),
        ".claude/settings.json (хук гейта)": _file_mentions(root / ".claude" / "settings.json", "gate.py"),
        ".codex/hooks.json (хук гейта)": _file_mentions(root / ".codex" / "hooks.json", "gate.py"),
        "AGENTS.md": (root / "AGENTS.md").is_file(),
        "CLAUDE.md": (root / "CLAUDE.md").is_file(),
    }
    return json.dumps({
        "root": str(root),
        "configured": items[".autopilot-kit/project.toml"],
        "missing": [name for name, present in items.items() if not present],
        "git": git(root, "rev-parse", "--is-inside-work-tree") is not None,
        "kitRepository": (root / "kit").is_dir() and (root / "pyproject.toml").is_file(),
    }, ensure_ascii=False, indent=2)


def drive_confirmed(usage: dict | None) -> str | None:
    """Авторитетное подтверждение привода из ответа get_usage (T19.8): `plan.status` знает сам провайдер.

    `ok` (лимиты подписки читаются) — это не гейтвей, как бы ни выглядело окружение; `not_applicable` — гейтвей
    организации (привод claude-gate). Остальные статусы ничего не подтверждают. Синтетический plan из
    `limits --codex` (поле `source` — файл сессий Codex) подтверждением не является.
    """
    if not isinstance(usage, dict):
        return None
    plan = usage.get("plan") if isinstance(usage.get("plan"), dict) else usage
    if not isinstance(plan, dict) or plan.get("source"):
        return None
    status = plan.get("status")
    if status == "ok":
        return "claude"
    if status == "not_applicable":
        return "claude-gate"
    return None


DRIVES = ("claude", "claude-gate", "codex")


def pinned_drive(root: Path | None = None) -> str | None:
    """Явная фиксация привода владельцем (T19.8): `drive = "…"` в `.autopilot-kit/project.toml` проекта,
    затем в `~/.autopilot-kit/profile.toml` машины. Переопределяет определение по окружению."""
    paths = []
    if root is not None:
        paths.append(Path(root) / ".autopilot-kit" / "project.toml")
    paths.append(kit_home() / ".autopilot-kit" / "profile.toml")
    for path in paths:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        drive = data.get("drive") if isinstance(data, dict) else None
        if drive in DRIVES:
            return drive
    return None


def drive_id(env: dict | None = None, root: Path | None = None) -> str:
    """Привод приложения: claude-gate / codex / claude / unknown (D48, сужено T19.8).

    Порядок: явная фиксация владельца (project.toml, profile.toml), затем живые признаки окружения.
    `ANTHROPIC_BASE_URL` признаком НЕ является: подписочное приложение тоже задаёт его (локальный прокси),
    а настоящий адрес гейтвея лежит в ~/.claude/settings.json. Авторитетная поправка — `drive_confirmed`
    из ответа get_usage (её применяют `limits` и `orchestrator --usage`).
    """
    env = os.environ if env is None else env
    if env.get("CODEX_THREAD_ID"):
        return "codex"  # живой признак Codex однозначен — фиксация его не переопределяет
    pinned = pinned_drive(root)
    if pinned:
        return pinned
    if env.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop-3p":
        return "claude-gate"
    if env.get("CLAUDECODE"):
        return "claude"
    return "unknown"


def machine_id(root: Path | None = None, drive: str | None = None) -> str:
    """Машина, домашний каталог kit и привод: сессии приложения живут только там, где их создали (kit relocate, D41;
    привод — D48, задачи приложения и сессии хранятся в профиле приложения)."""
    return f"{platform.node()}|{os.path.abspath(kit_home())}|{drive or drive_id(root=root)}"


def machines_compatible(recorded: str | None, current: str) -> bool:
    """Та ли машина/профиль: записи до D48 (узел|дом, без привода) совместимы с любым приводом той же машины."""
    if not recorded:
        return True
    old, new = str(recorded).split("|"), current.split("|")
    if old[:2] != new[:2]:
        return False
    old_drive = old[2] if len(old) > 2 else None
    new_drive = new[2] if len(new) > 2 else None
    return old_drive in (None, "unknown", new_drive) or new_drive in (None, "unknown")


def foreign_program(root: Path, data: dict) -> bool:
    """Программу ведёт оркестратор другой машины/профиля/привода (D48): её сессии и резерв отсюда не видны."""
    return bool(data.get("orchestrator")) and not machines_compatible(data.get("orchestratorMachine"), machine_id(root))


def cmd_orchestrator(root: Path, session: str, usage: dict | None = None) -> str:
    data = load(root)
    data["orchestrator"] = session
    # привод: подтверждение из get_usage (T19.8) > ранее подтверждённый > фиксация/окружение
    drive = drive_confirmed(usage) or data.get("drive") or drive_id(root=root)
    data["drive"] = drive
    data["orchestratorMachine"] = machine_id(root, drive)
    save(root, data)
    return f"оркестратор программы: {session} (привод {drive})"


def heal_drive(root: Path, confirmed: str) -> bool:
    """Правит записанный привод программы по авторитетному подтверждению (T19.8): поле `drive` и третий элемент
    `orchestratorMachine` — только если запись сделана на этой машине (иначе это идентичность другой машины)."""
    data = load(root)
    changed = False
    if data.get("drive") != confirmed:
        data["drive"] = confirmed
        changed = True
    recorded = data.get("orchestratorMachine")
    if recorded:
        parts = str(recorded).split("|")
        prefix = machine_id(root).split("|")[:2]
        if len(parts) == 3 and parts[:2] == prefix and parts[2] != confirmed:
            data["orchestratorMachine"] = "|".join([*prefix, confirmed])
            changed = True
    if changed:
        save(root, data)
    return changed


# ── сторож программ (D28): после перезапуска, обрыва сети или сна программы продолжаются сами ──

WATCH_QUIET_MIN = 60       # без перезагрузки этап считается прерванным, если прогон молчит дольше (фоновый субагент
                           # может писать код больше часа, поэтому порог большой); после перезагрузки — сразу
WATCH_ESCALATE_MIN = 60    # разбудили, а программа не сдвинулась — уведомить владельца
WATCH_REWAKE_MIN = 45      # будили, а прогон не сдвинулся: пробуждение повторяется (идущую сессию задача сторожа пропускает), D52
WATCH_REMIND_MIN = 120     # этап ждёт владельца: напоминание раз в 2 часа (D41), а не один пуш, который ночью никто не видел
WATCH_TASK_MIN = 15        # период задачи сторожа (cron */15); её расписание живёт в профиле приложения — отсюда не прочитать
WATCH_TASK_GAP_MIN = 2 * WATCH_TASK_MIN  # разрыв с последним проходом сторожа не меньше этого — приложение было закрыто/спало (T21.16)
WAITING_REMIND = ("Программа {short}: этап {stage} ждёт вашего ответа уже {hours} ч — откройте чат её оркестратора "
                  "(вопрос там)")
WATCH_BETWEEN_MIN = 15     # сданный этап, следующий не начат: субагентов тут нет, оркестратор запускает этап за минуты
WATCH_TASK_ID = "autopilot-program-watchdog"
INTERRUPTED = ("Сторож программы: возможно, было прерывание (перезагрузка машины, перезапуск приложения, обрыв сети или сон). Если ты ждёшь "
               "своего фонового субагента и он ещё работает — ничего не делай, закончи ход одной строкой. Иначе продолжай "
               "прогон Autopilot с места остановки; если прогон ждёт ответа владельца — повтори вопрос оркестратору и закончи ход. "
               "Если процесс чата упал (в начале этого чата — «Claude Code process exited» или уведомления «stopped … didn't finish "
               "before the previous session ended») — фоновые агенты и задачи потеряны: проверь их рабочие папки на частичный результат "
               "и запусти заново то, что не закончено.")
TAKE_SESSION = ("`program.py pool take --json`; при `clear: true` сначала очисти этот чат "
                "(`mcp__ccd_session_mgmt__clear_session`, D40; отказ — `pool take --json` ещё раз), затем отправь ему `program.py "
                "signal <ID>` и привяжи `program.py bind`. `start_session` в этом ходе приложение не даст — не пробуй")
CONTINUE_PROGRAM = ("Сторож программы: продолжай программу — `program.py check --record` у идущего этапа, разбор остатка, затем "
                    f"следующий этап: {TAKE_SESSION}. Ничего у владельца не спрашивай (D30).")
UNBOUND_STAGE = ("Сторож программы: этап {stage} помечен идущим, а сессии у него нет уже {minutes} мин — запусти сессию этапа: "
                 f"{TAKE_SESSION}. Ничего у владельца не спрашивай (D30).")
NO_SESSION = ("Программа {short}: следующий этап {stage} не запустить без вас — свободных чатов нет. Напишите «продолжай» "
              "в чате её оркестратора")
REPORT_AND_STOP = ("Сторож программы: сообщи оркестратору итог этапа одной строкой (send_message, session_id \"parent\") "
                   "и закончи ход — ничего не переделывай.")
UNKNOWN_OWNER = ("Программа «{short}»: сторож не знает, кто её ведёт, — оркестратор `{orchestrator}` зарегистрирован без "
                 "машины/привода (запись до D48), а в этом профиле приложения его сессия не найдена. Программа не разбужена, "
                 "её резерв и сервер дашборда не тронуты. Если она ваша — откройте чат её оркестратора в своём профиле и "
                 "продолжите программу (`/autopilot-program`, он перерегистрируется сам с `--usage`, D49) либо выполните в "
                 "папке проекта `python \"{script}\" --project \"{root}\" confirm-owner`. Если не ваша — ничего не делайте, "
                 "это уведомление не повторится.")


def watch_memory_path() -> Path:
    return kit_home() / ".autopilot-kit" / "watch.json"


def unknown_owner_key(root: Path) -> str:
    """Ключ памяти сторожа для неподтверждённого владения; abspath — реестр, watch и confirm-owner видят одну строку."""
    return f"{os.path.abspath(root)}#unknown-owner"


def load_watch_memory() -> dict:
    path = watch_memory_path()
    try:
        memory = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        memory = {}
    return memory if isinstance(memory, dict) else {}


def save_watch_memory(memory: dict) -> None:
    path = watch_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def watch_last_path() -> Path:
    return kit_home() / ".autopilot-kit" / "watch_last"


def watch_gap_restart() -> datetime | None:
    """T21.16: признак перезапуска приложения без перезагрузки ОС — момент предыдущего прохода сторожа.

    Задача сторожа ходит каждые WATCH_TASK_MIN минут; если разрыв с `watch_last` не меньше WATCH_TASK_GAP_MIN,
    приложение было закрыто или спало, и ход, потерянный на перезапуске, надо будить сразу — как после перезагрузки
    машины, а не через час молчания прогона. Первый проход (файла нет) и нечитаемая метка перезапуском не считаются —
    иначе сторож будил бы всё подряд на первой в жизни проверке.
    """
    try:
        moment = _instant(watch_last_path().read_text(encoding="utf-8").strip())
    except OSError:
        return None
    if moment.year == 1:
        return None
    return moment if (datetime.now(timezone.utc) - moment).total_seconds() / 60 >= WATCH_TASK_GAP_MIN else None


def cmd_confirm_owner(root: Path, absent: bool) -> str:
    """Подтверждение владения программой, записанной до D48 (без `orchestratorMachine`) — T19.9.

    Выполняет задача сторожа по итогу `get_session` оркестратора: сессия найдена в этом профиле — записываем
    машину/привод, программа становится своей; не найдена — `--absent`: сторож молча пропускает её (не будит,
    не поднимает сервер, не трогает резерв), владелец уведомлён один раз.
    """
    key = unknown_owner_key(root)
    memory = load_watch_memory()
    if absent:
        if key not in memory:
            memory[key] = {"at": now()}
            save_watch_memory(memory)
        return ("владение не подтверждено: сторож пропускает программу молча (не будит, сервер и резерв не трогает); "
                "подтверждение — `confirm-owner` из своего профиля")
    data = load(root)
    if not data.get("orchestrator"):
        raise ProgramError("в программе нет зарегистрированного оркестратора — подтверждать нечего")
    data["orchestratorMachine"] = machine_id(root, data.get("drive"))
    save(root, data)
    if memory.pop(key, None) is not None:
        save_watch_memory(memory)
    return f"владение подтверждено: orchestratorMachine = {data['orchestratorMachine']}"


def boot_time() -> datetime | None:
    """Время последней загрузки системы: прогон, замолчавший раньше, точно прерван перезагрузкой."""
    try:
        if os.name == "nt":
            import ctypes
            uptime_ms = ctypes.windll.kernel32.GetTickCount64()
        else:
            uptime_ms = float(Path("/proc/uptime").read_text().split()[0]) * 1000
    except (OSError, AttributeError, ValueError):
        return None
    return datetime.now(timezone.utc) - timedelta(milliseconds=uptime_ms)


def registry_path() -> Path:
    return kit_home() / ".autopilot-kit" / "programs.json"


def write_with_backup(path: Path, text: str) -> None:
    """Запись с резервной копией .bak-<UTC> (правило проекта); program.py самодостаточен — kit.fsutil не зовёт."""
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
        except OSError:
            old = None
        if old is not None and old != text:
            backup = path.with_name(f"{path.name}.bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
            try:
                backup.write_text(old, encoding="utf-8")
            except OSError:
                pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def register_program(root: Path, goal: str | None = None) -> None:
    """Запоминает программу в реестре машины — по нему сторож обходит все программы.

    T21.6: битый реестр больше не перезаписывается молча — прежний код при ошибке разбора делал reg = {} и писал файл
    целиком только с новой программой, теряя все остальные записи; и запись идёт с резервной копией (правило проекта:
    файлы пользователя вне репозитория меняются только с .bak-<UTC>).
    """
    path = registry_path()
    reg = {}
    if path.exists():
        try:
            reg = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise ProgramError(f"реестр программ {path} не читается ({error}) — не перезаписываю: "
                               "исправьте или отложите его вручную и повторите") from error
        if not isinstance(reg, dict):
            raise ProgramError(f"реестр программ {path} испорчен (ожидался объект) — не перезаписываю: "
                               "исправьте или отложите его вручную и повторите")
    programs = [p for p in reg.get("programs") or [] if isinstance(p, dict)]
    key = os.path.abspath(root)
    if any(p.get("root") == key for p in programs):
        return
    programs.append({"root": key, "goal": goal, "registeredAt": now()})
    path.parent.mkdir(parents=True, exist_ok=True)
    write_with_backup(path, json.dumps({**reg, "programs": programs}, ensure_ascii=False, indent=2) + "\n")


def _minutes_since(stamp: str | None) -> float | None:
    moment = _instant(stamp or "")
    if moment.year == 1:
        return None
    return (datetime.now(timezone.utc) - moment).total_seconds() / 60


JOB_PROBE_TIMEOUT_S = 45
JOB_DEAD = ("Сторож программы: проверка долгой работы «{label}» (`{probe}`) не проходит уже {minutes} мин, а срок работы ещё не "
            "вышел ({until}). Посмотри на месте, что с ней: упала — найди причину в логах, перезапусти и заново заведи наблюдение, "
            "которое разбудит тебя при остановке; закончилась штатно — `program.py job clear {label}`. Ничего не жди молча: "
            "итог — одной строкой оркестратору (send_message, session_id \"parent\").")


JOB_EXPIRED = ("Сторож программы: срок наблюдения за долгой работой «{label}» (`{probe}`) вышел ({until}), а этап не сдан; проверка "
               "сейчас: {state}. Выясни на месте, идёт ли работа (по логам, не по процессу): идёт — продли наблюдение "
               "(`program.py job set --label {label} --probe … --until <конец ВСЕЙ работы с запасом>`), закончилась — `job clear "
               "{label}`, упала — перезапусти и заведи наблюдение заново. Молча не оставляй: без записи обрыв никто не увидит. "
               "Итог — одной строкой оркестратору (send_message, session_id \"parent\").")
JOB_STATE_RU = {"alive": "отвечает «жива»", "dead": "НЕ проходит (работа не идёт)", "unknown": "проверить не вышло (нет связи)"}


def job_memory(memory: dict, root: Path, job: dict) -> dict:
    """Состояние проверок работы в watch.json; перерегистрация (`job set`: новые `since`/`until`) начинает его заново (D50)."""
    state = memory.setdefault(f"{root}#job:{job['label']}", {})
    key = f"{job.get('since')}|{job.get('until')}"
    if state.get("jobKey") != key:
        state.clear()
        state["jobKey"] = key
    return state


def split_jobs(data: dict, stage: dict, quiet: float | None) -> tuple[list[dict], list[dict]]:
    """Работы под наблюдением и работы с вышедшим сроком (D50). Вышедший срок значим, только пока этап не сдан, прогон молчит
    (идущий этап и так виден) и работа заведена в этом этапе (запись прежнего этапа — не повод будить следующий)."""
    moment = datetime.now(timezone.utc)
    jobs, expired = [], []
    started = _instant(stage.get("startedAt") or "")
    for job in data.get("jobs") or []:
        if _instant(job.get("until") or "") > moment:
            jobs.append(job)
            continue
        registered = _instant(job.get("since") or "")
        older = started.year > 1 and registered.year > 1 and registered < started
        if not older and (quiet is None or quiet >= WATCH_BETWEEN_MIN):
            expired.append(job)
    return jobs, expired


def probe_job(job: dict) -> str:
    """alive — проверка прошла; dead — работа не отвечает; unknown — проверить не вышло (нет связи, таймаут)."""
    try:
        done = subprocess.run(job["probe"], shell=True, timeout=JOB_PROBE_TIMEOUT_S, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return "alive" if done.returncode == 0 else "unknown" if done.returncode == 255 else "dead"  # 255 — ssh не дозвонился


def watch_jobs(root: Path, data: dict, stage: dict, jobs: list[dict], expired: list[dict], memory: dict, item: dict) -> dict:
    """Решение по этапу с долгой работой вне чата (D47, D50). Состояние проверок — в watch.json, program.json не трогаем."""
    short = data["goal"].split(" — ")[0].split(":")[0][:40]
    dead, unknown = [], []
    for job in jobs:
        state = job_memory(memory, root, job)
        result = probe_job(job)
        if result == "alive":
            key = state.get("jobKey")
            state.clear()
            state["jobKey"] = key
        elif result == "dead":
            state.pop("unknownSince", None)
            state.setdefault("deadSince", now())
            dead.append((job, state))
        else:
            state.setdefault("unknownSince", now())
            unknown.append((job, state))
    base = {**item, "stage": stage["id"]}
    for job in expired:  # D50: срок вышел, этап не сдан — наблюдение не гаснет молча, а будит и напоминает как «упала»
        state = job_memory(memory, root, job)
        state.setdefault("expiredSince", now())
        minutes = int(_minutes_since(state["expiredSince"]) or 0)
        if not state.get("woken"):
            state["woken"] = now()
            return {**base, "action": "wake_stage", "sessionId": stage.get("sessionId"),
                    "message": JOB_EXPIRED.format(label=job["label"], probe=job["probe"], until=job["until"],
                                                  state=JOB_STATE_RU[probe_job(job)]),
                    "note": f"этап {stage['id']}: срок наблюдения за «{job['label']}» вышел ({job['until']}), этап не сдан — бужу этап"}
        since = _minutes_since(state.get("remindedAt") or state["woken"]) or 0
        if since >= (WATCH_REMIND_MIN if state.get("remindedAt") else WATCH_ESCALATE_MIN):
            state["remindedAt"] = now()
            return {**base, "action": "notify_owner", "sessionId": None, "note": f"срок наблюдения за «{job['label']}» вышел {minutes} мин назад",
                    "message": f"Программа {short}: срок наблюдения за работой «{job['label']}» этапа {stage['id']} вышел, этап не сдан, "
                               "а наблюдение не продлено — напишите «продолжай» её оркестратору"}
        return {**base, "note": f"срок наблюдения за «{job['label']}» вышел {minutes} мин назад, этап будили — ждём"}
    for job, state in dead:
        minutes = int(_minutes_since(state["deadSince"]) or 0)
        if not state.get("woken"):
            state["woken"] = now()
            return {**base, "action": "wake_stage", "sessionId": stage.get("sessionId"),
                    "message": JOB_DEAD.format(label=job["label"], probe=job["probe"], minutes=minutes, until=job["until"]),
                    "note": f"этап {stage['id']}: работа «{job['label']}» не отвечает {minutes} мин — бужу этап"}
        since = _minutes_since(state.get("remindedAt") or state["woken"]) or 0
        if since >= (WATCH_REMIND_MIN if state.get("remindedAt") else WATCH_ESCALATE_MIN):
            state["remindedAt"] = now()
            return {**base, "action": "notify_owner", "sessionId": None, "note": f"работа «{job['label']}» не отвечает {minutes} мин",
                    "message": f"Программа {short}: работа «{job['label']}» этапа {stage['id']} стоит уже {minutes} мин, этап будили — "
                               "напишите «продолжай» её оркестратору"}
        return {**base, "note": f"работа «{job['label']}» не отвечает {minutes} мин, этап будили — ждём"}
    for job, state in unknown:
        minutes = int(_minutes_since(state["unknownSince"]) or 0)
        since = _minutes_since(state.get("remindedAt")) if state.get("remindedAt") else minutes
        if minutes >= WATCH_ESCALATE_MIN and (since or 0) >= WATCH_REMIND_MIN:
            state["remindedAt"] = now()
            return {**base, "action": "notify_owner", "sessionId": None, "note": f"работу «{job['label']}» не проверить {minutes} мин",
                    "message": f"Программа {short}: не удаётся проверить работу «{job['label']}» этапа {stage['id']} уже {minutes} мин "
                               "(нет связи с сервером?)"}
        return {**base, "note": f"работу «{job['label']}» проверить не вышло ({minutes} мин) — повторю"}
    return {**base, "note": "этап работает: " + ", ".join(f"«{j['label']}» жива" for j in jobs)}


def watch_program(root: Path, memory: dict, app_restart: datetime | None = None) -> dict:
    """Решение сторожа по одной программе: none / wake_stage / notify_owner — с сессией и текстом сообщения.

    app_restart (T21.16): момент предыдущего прохода сторожа, если разрыв с ним выдал перезапуск приложения —
    идущий этап, замолчавший до этого момента, будится сразу (как после перезагрузки машины).
    """
    data = load(root)
    result = _watch_decide(root, data, memory, app_restart)
    stage = next((s for s in data["stages"] if s["id"] == result.get("stage")), None)
    if stage is not None:
        prev = open_previous_sessions(stage)
        if prev:  # T21.3: живая прежняя сессия — в пометку каждого решения, пока её не погасили
            result = {**result, "note": (result.get("note") or "") + " · прежняя сессия не погашена ("
                      + ", ".join(p["sessionId"] for p in prev) + ") — stop_session/archive_session + `stage prev-done`"}
    return result


def _watch_decide(root: Path, data: dict, memory: dict, app_restart: datetime | None = None) -> dict:
    item = {"root": str(root), "goal": data["goal"], "action": "none", "stage": None, "sessionId": None, "message": None,
            "orchestrator": data.get("orchestrator"),
            "pool": [p["sessionId"] for p in data.get("pool") or [] if isinstance(p, dict) and p.get("sessionId")]}
    if foreign_program(root, data):
        # D48: оркестратор зарегистрирован другим профилем приложения/приводом — его сессии и резерв отсюда не видны;
        # будить и чистить резерв (`pool drop` в задаче сторожа) значит ломать чужую программу. Проверка раньше
        # остальных: задача сторожа разбирает `pool` каждой записи до действий
        parts = str(data.get("orchestratorMachine") or "").split("|")
        who = parts[2] if len(parts) > 2 else f"машина {parts[0]}" if parts and parts[0] != platform.node() else "другой профиль"
        return {**item, "foreign": True,
                "note": f"программу ведёт оркестратор из другого профиля/привода ({who}) — отсюда не трогаю"}
    if data.get("orchestrator") and not data.get("orchestratorMachine"):
        # T19.9: запись до D48 — какому профилю принадлежит программа, неизвестно. Видимость сессии знает только
        # приложение (get_session), поэтому решает задача сторожа: найдена — `confirm-owner`, нет — `--absent`
        if memory.get(unknown_owner_key(root)):
            return {**item, "action": "none", "message": None, "unknownOwner": True,
                    "note": "владелец не подтверждён: сессию оркестратора этот профиль не видит, владельцу сообщили — "
                            "жду подтверждения (`confirm-owner`), не трогаю"}
        item["unknownOwner"] = True
        short = data["goal"].split(" — ")[0].split(":")[0][:40]
        item["ownerMessage"] = UNKNOWN_OWNER.format(
            short=short, orchestrator=data["orchestrator"], script=Path(__file__).resolve().as_posix(), root=root)
    pause = data.get("pause")
    if pause and pause_reason(pause) != "limit":  # D46: стоп владельца — сторож его не снимает и не будит этапы
        return {**item, "note": f"пауза по слову владельца: {pause.get('text') or 'без пояснения'} — снимет только владелец (resume)"}
    if pause and _instant(pause.get("until") or "") > datetime.now(timezone.utc):
        return {**item, "note": f"пауза по лимиту до {pause.get('until')} — продолжит задача сброса"}
    stage = active_stage(data)
    if stage is None:
        if next_pending(data) is None:
            return {**item, "note": "все этапы сданы или пропущены"}
        decision = cmd_next(root)
        if decision.get("questions"):
            return {**item, "note": "следующий этап ждёт ответов владельца — вопросы уже у оркестратора"}
        delivered = [s for s in data["stages"] if s["status"] == "passed" and s.get("sessionId")]
        quiet = _minutes_since(data.get("updatedAt"))
        if not delivered or quiet is None or quiet < WATCH_BETWEEN_MIN:
            return {**item, "note": "между этапами, оркестратор работает"}
        last = delivered[-1]
        if data.get("orchestrator") and not item["pool"] and not recyclable(data):
            # D40: ни резерва, ни чата сданного этапа — будить оркестратора бесполезно (сессию из хода по сообщению не
            # запустить), сразу владельцу, один раз
            short = data["goal"].split(" — ")[0].split(":")[0][:40]
            item.update(action="notify_owner", stage=decision.get("stage"), message=NO_SESSION.format(
                short=short, stage=decision.get("stage") or "?"), note="между этапами: свободных чатов нет — нужен владелец")
        elif data.get("orchestrator"):  # D31: оркестратор начнёт этап сообщением резервной сессии — из любого хода
            item.update(action="wake_orchestrator", stage=last["id"], sessionId=data["orchestrator"], message=CONTINUE_PROGRAM,
                        note=f"этап {last['id']} сдан, следующий не начат {int(quiet)} мин — бужу оркестратора")
        else:
            item.update(action="wake_stage", stage=last["id"], sessionId=last["sessionId"], message=REPORT_AND_STOP,
                        note=f"этап {last['id']} сдан, следующий не начат {int(quiet)} мин — конец хода этапа разбудит оркестратора")
    elif (not stage.get("sessionId") and data.get("orchestrator")
          and (_minutes_since(stage.get("startedAt")) or 0) >= WATCH_BETWEEN_MIN):
        # этап начат (`start`), а сессию так и не привязали (`bind`): сам этап не проснётся и не сообщит — будим оркестратора
        quiet = int(_minutes_since(stage.get("startedAt")))
        item.update(action="wake_orchestrator", stage=stage["id"], sessionId=data["orchestrator"],
                    message=UNBOUND_STAGE.format(stage=stage["id"], minutes=quiet),
                    note=f"этап {stage['id']}: начат {quiet} мин назад, сессии нет — бужу оркестратора")
    else:
        if str(stage.get("sessionId") or "").startswith("codex-exec:"):
            return {**item, "stage": stage["id"], "note": "этап в Codex — оркестратор Codex следит сам задачей в чате"}
        run = read_run(root)
        verdict = evaluate(root, data, stage, with_gate=False)["verdict"]
        if verdict == "waiting" or stage["status"] == "waiting":
            # D41: ответ может быть нужен только от владельца (блок проверки прав) — напоминать, пока ждёт, а не один раз
            waited = _minutes_since((run or {}).get("updatedAt") or stage.get("startedAt"))
            prev = memory.get(str(root)) or {}
            reminded = _minutes_since(prev.get("remindedAt"))
            if waited is not None and waited >= WATCH_REMIND_MIN and (reminded is None or reminded >= WATCH_REMIND_MIN):
                memory[str(root)] = {**prev, "remindedAt": now()}
                short = data["goal"].split(" — ")[0].split(":")[0][:40]
                return {**item, "action": "notify_owner", "stage": stage["id"],
                        "message": WAITING_REMIND.format(short=short, stage=stage["id"], hours=int(waited // 60)),
                        "note": f"этап {stage['id']} ждёт владельца {int(waited)} мин — напоминаю"}
            return {**item, "stage": stage["id"], "note": "этап ждёт ответа владельца — вопрос у оркестратора"}
        last = (run or {}).get("updatedAt") if verdict != "not_started" else stage.get("startedAt")
        quiet = _minutes_since(last)
        jobs, expired = split_jobs(data, stage, quiet)
        if (jobs or expired) and verdict not in ("passed", "failed"):  # D47: этап ждёт долгую работу вне чата — судим по ней, а не по молчанию прогона
            return watch_jobs(root, data, stage, jobs, expired, memory, item)
        boot = boot_time()
        rebooted = boot is not None and _instant(last or "").year > 1 and _instant(last) < boot
        # T21.16: перезапуск приложения (разрыв с прошлым проходом сторожа) будит так же сразу, но причина в note другая
        restarted = (not rebooted and app_restart is not None
                     and _instant(last or "").year > 1 and _instant(last) < app_restart)
        finished = verdict in ("passed", "failed")
        threshold = WATCH_BETWEEN_MIN if finished else WATCH_QUIET_MIN
        if quiet is None or not stage.get("sessionId") or (quiet < threshold and not rebooted and not restarted):
            return {**item, "stage": stage["id"], "note": "этап работает"}
        if finished and data.get("orchestrator"):  # прогон сдан, а программа его не учла — оркестратор не проснулся
            item.update(action="wake_orchestrator", stage=stage["id"], sessionId=data["orchestrator"], message=CONTINUE_PROGRAM,
                        note=f"этап {stage['id']}: прогон закончен ({verdict}) {int(quiet)} мин назад, программа не учла — бужу оркестратора")
        else:
            message = REPORT_AND_STOP if finished else INTERRUPTED
            item.update(action="wake_stage", stage=stage["id"], sessionId=stage["sessionId"], message=message,
                        note=f"этап {stage['id']}: {verdict}, прогон молчит {int(quiet)} мин"
                             + (" (с перезагрузки)" if rebooted else " (с перезапуска приложения)" if restarted else ""))
    # разбудили в прошлый раз, а программа и прогон не сдвинулись — будить снова бесполезно, нужен владелец
    key = str(root)
    mark = f"{data.get('updatedAt')}|{(read_run(root) or {}).get('updatedAt')}"
    prev = memory.get(key) or {}
    if prev.get("mark") == mark and item["action"] == "notify_owner" and prev.get("action") == "notify_owner":
        return {**item, "action": "none", "message": None, "note": (item.get("note") or "") + " · владельцу уже сообщили"}
    if prev.get("mark") == mark and prev.get("action") in ("wake_stage", "wake_orchestrator"):
        since = _minutes_since(prev.get("at"))
        if since is not None and since >= WATCH_ESCALATE_MIN and not prev.get("notified"):
            memory[key] = {**prev, "notified": now(), "wokeAt": now()}
            short = data["goal"].split(" — ")[0].split(":")[0][:40]
            return {**item, "action": "notify_owner", "sessionId": None,
                    "message": f"Программа {short} стоит — напишите «продолжай» её оркестратору", "note": item.get("note")}
        reminded = _minutes_since(prev.get("notified")) if prev.get("notified") else None
        if reminded is not None and reminded >= WATCH_REMIND_MIN:  # D47: один пуш и вечное молчание — ночью его никто не видел
            memory[key] = {**prev, "notified": now(), "wokeAt": now()}
            short = data["goal"].split(" — ")[0].split(":")[0][:40]
            return {**item, "action": "notify_owner", "sessionId": None,
                    "message": f"Программа {short} всё ещё стоит — напишите «продолжай» её оркестратору", "note": item.get("note")}
        if item["action"] in ("wake_stage", "wake_orchestrator"):
            # D52: «будили, не сдвинулось — ждём» вечно не годится: первое пробуждение могло прийти, пока этап работал
            # (задача сторожа такой этап пропускает), а потом процесс чата упал (код 3221226505 при нехватке памяти) — без нового
            # пробуждения программа так и стоит. Задача сторожа и так пропускает идущую сессию, поэтому повтор дёшев
            again = _minutes_since(prev.get("wokeAt") or prev.get("at"))
            if again is not None and again >= WATCH_REWAKE_MIN:
                memory[key] = {**prev, "wokeAt": now()}
                return {**item, "note": (item.get("note") or "") + " · повторное пробуждение (прогон не сдвинулся)"}
        if prev.get("notified") or (since is not None and since < WATCH_ESCALATE_MIN):
            return {**item, "action": "none", "sessionId": None, "message": None,
                    "note": (item.get("note") or "") + " · уже будили, ждём"}
    memory[key] = {"mark": mark, "action": item["action"], "at": now()}
    return item


def cmd_watch() -> list[dict]:
    """Обход всех программ реестра: решения сторожа. Поднимает серверы дашбордов (кроме тестов)."""
    path = registry_path()
    try:
        reg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        reg = {}
    memory = load_watch_memory()
    app_restart = watch_gap_restart()  # T21.16: до обхода — в конце прохода watch_last перезаписывается
    results = []
    for entry in reg.get("programs") or []:
        root = Path(entry.get("root") or "")
        try:
            there = program_path(root).exists()
        except OSError as error:  # нет прав / сетевой диск моргнул: одна программа не должна ронять сторожа для всех
            results.append({"root": str(root), "action": "none", "note": f"папка недоступна ({error.__class__.__name__}) — пропускаю"})
            continue
        if not there:
            results.append({"root": str(root), "action": "none", "note": "программы нет на диске — пропускаю"})
            continue
        # T19.9: чужая программа (другой профиль/привод) и заглушённая неподтверждённая запись сервера не получают —
        # ensure_server пишет в общую папку проекта и по D45 заменяет «зависший» сервер, который может вести другая машина
        quiet = False
        try:
            data = load(root)
            quiet = foreign_program(root, data) or bool(
                data.get("orchestrator") and not data.get("orchestratorMachine") and memory.get(unknown_owner_key(root)))
        except (OSError, ProgramError, ValueError):
            pass
        if not quiet and not os.environ.get("AUTOPILOT_KIT_NO_SERVE"):
            try:
                ensure_server(root)
            except (OSError, ProgramError):
                pass
        try:
            results.append(watch_program(root, memory, app_restart))
        except (OSError, ProgramError, ValueError) as error:
            results.append({"root": str(root), "action": "none", "note": f"не разобрать: {error}"})
    save_watch_memory(memory)
    watch_last_path().write_text(now() + "\n", encoding="utf-8")  # по нему пульт видит, что сторож не запускался (D43); разрыв по нему же ловит перезапуск приложения (T21.16)
    return results


def watch_prompt() -> str:
    """Текст задачи приложения «Сторож программ» (D28): исполняет решения `program.py watch`, сам ничего не решает."""
    script = Path(__file__).resolve().as_posix()
    return (
        "Сторож программ прогонов Autopilot (autopilot-kit, решение D28). Ты исполняешь решения скрипта и больше ничего: "
        "не меняешь файлы проектов, не запускаешь сессии, не коммитишь и не пушишь (исключения — `pool drop` (шаг 4) и "
        "`confirm-owner` (шаг 3): они правят файлы kit и программы, не код проекта). Решения о побудке принимает сам "
        "скрипт (T21.16): после перезагрузки машины — сразу; после перезапуска приложения (разрыв с его прошлым "
        "проходом ≥ 30 мин) — сразу; иначе — когда прогон молчит 60 мин (15 мин между этапами).\n\n"
        f"1. Выполни `python \"{script}\" watch --json` — список программ с полем `action`.\n"
        "2. Записи с `foreign: true` пропусти целиком (резерв не проверяй, сообщений не отправляй): программу ведёт "
        "оркестратор из другого профиля приложения/привода (D48) — её сессии отсюда не видны, а `pool drop` их бы сломал.\n"
        "3. Записи с `unknownOwner: true` (оркестратор зарегистрирован без машины — запись до D48, T19.9): посмотри сессию "
        "`orchestrator` (`mcp__ccd_session_mgmt__get_session`). Найдена и не в архиве — выполни "
        f"`python \"{script}\" --project \"<root записи>\" confirm-owner` (программа станет своей) и действуй по `action` как обычно. "
        "Не найдена — не буди сессии записи, не проверяй её резерв и не делай `pool drop`; если в записи есть `ownerMessage`, "
        "отправь его владельцу уведомлением одной строкой (PushNotification; нет его в этом билде — `mcp__ccd_turn__wrap_up` с "
        f"`recap`/`ask` и `blocked: true`), затем выполни `python \"{script}\" --project \"<root записи>\" confirm-owner --absent` "
        "— следующие проверки будут молча пропускать программу, пока владелец не подтвердит владение.\n"
        "4. Резерв (D34): для каждой записи с непустым `pool` проверь каждую сессию из него "
        "(`mcp__ccd_session_mgmt__get_session`). «Не найдена» или `isArchived: true` — сессия мёртвая (переезд на другую машину, "
        f"удалённый чат): `python \"{script}\" --project \"<root записи>\" pool drop <id>`. Мёртвая запись иначе считалась бы резервом, "
        "и следующий этап не смог бы стартовать из хода по сообщению. Живые не трогай.\n"
        "5. Для каждой записи:\n"
        "   - `wake_stage` или `wake_orchestrator`: посмотри сессию `sessionId` (`mcp__ccd_session_mgmt__get_session`). Если `isRunning: true` — пропусти. "
        "Иначе отправь ей `message` дословно инструментом `mcp__ccd_session_mgmt__send_message` (SendMessage из этой сессии не "
        "работает). Загрузи инструменты через ToolSearch, если нужно (нет ToolSearch в этом билде — они уже загружены, D48).\n"
        "   - `notify_owner`: отправь `message` уведомлением (PushNotification; нет его в этом билде — `mcp__ccd_turn__wrap_up` "
        "с `recap`/`ask` и `blocked: true`, приложение покажет баннер) одной строкой.\n"
        "   - `none`: ничего.\n"
        "6. Ответь одной строкой на программу: что сделал («разбудил этап M3a», «ничего: этап работает» и т. п.).\n"
        "7. Затем убери этот чат в архив, чтобы проверки не копились в боковой панели: "
        "`mcp__ccd_session_mgmt__archive_session` с `session_id: \"self\"`.\n"
    )


# ── привод Codex (D24): этап — фоновый `codex exec`, ответ владельца — `codex exec resume` ──

# доступ этапа: папка проекта + автоматическая проверка запросов (решение владельца D24); проверяется спайком C6,
# заменяется на запуске: `codex-run <ID> --exec-arg …` (запоминается для resume этого этапа)
CODEX_EXEC_ARGS = ("--sandbox", "workspace-write", "--approve-for-me")
CODEX_RULES = (
    "Владелец читает только чат оркестратора; оркестратор пересылает ему твои вопросы и возвращает ответы сюда.\n"
    "- Когда Autopilot ждёт владельца (`ap.py ask`), задай вопрос текстом **последним сообщением хода** — дословно, с "
    "вариантами и твоей рекомендацией — и закончи ход. Не используй интерактивный вопрос (`request_user_input`): этот "
    "прогон идёт без человека. Ответ придёт следующим запуском этой же сессии (`codex exec resume`); первой строкой ответа "
    "напиши «Ответ владельца получен через оркестратора: <ответ кратко>» и продолжай.\n"
    "- Сдав этап (коммит «Autopilot: сборка сдана» сделан), закончи ход сообщением «Этап {stage} сдан: <итог одной строкой>».\n"
    "- Ожидание владельца (`ap.py ask`) не держи без срока и без причины: `--note` — что именно ждёшь и от кого, сразу после "
    "вопроса закончи ход (флаг в state.js не повод оставаться в ходе). Когда владелец сказал «продолжай», «стоп снят», дал новую "
    "задачу или ответ — **сам** выполни `python .autopilot/ap.py answered` до первой работы, даже если оркестратор уже снял "
    "паузу: флаг `waiting` оставляет дашборд оранжевым, хотя этап работает. Пришло «стоп владельца снят» — то же самое.\n"
    "- `.autopilot/program.json` и `.autopilot/PROGRAM.md` ведёт оркестратор — не правь и не коммить их. Ничего не пушь.\n"
    "- Долгая работа вне чата (тест, сборка, драйвер на сервере — всё, что идёт дольше часа без твоих действий): **до конца "
    "хода** зарегистрируй проверку: `python \"{program_py}\" --project . job set --label <метка> --probe \"<команда: код 0, "
    "если работа жива>\" --until <срок ISO>`. Оркестратор проверяет её каждые 10 минут и, если работа упала, возобновит тебя "
    "(`codex exec resume`) с описанием. Закончилась — `job clear <метка>`. Ход с идущей долгой работой без записи не "
    "заканчивай: обрыв в это время никто не увидит (D47). Проверка должна падать, когда теста нет (`pgrep -f` находит саму "
    "проверку — образец в скобках `'[d]fab'` или `tmux has-session`), ловить движение (свежий лог `find <лог> -mmin -15 | "
    "grep -q .`), покрывать всю цепочку окон работ, а `--until` — конец всей цепочки с запасом, не ближайшего окна; "
    "перед концом хода — `job list` (D50).\n"
)


def codex_stage_prompt(data: dict, stage: dict) -> str:
    """Задание этапа для фонового `codex exec`: навыки вызываются упоминанием `$имя` (у Codex нет запрета вызова моделью)."""
    head = (f"Ты — сессия этапа {stage['id']} программы прогонов Autopilot. Оркестратор — другой чат Codex; итог он "
            "проверит по файлам `.autopilot/`, гейту и git.\n\n1. Вызови навык $autopilot-roles.\n")
    if stage.get("adopted"):
        body = ("2. Вызови навык $autopilot без аргументов — он продолжит начатый прогон по `.autopilot/state.js`.\n\n"
                + "\n".join(decisions_block(data)))
    else:
        body = ("2. Вызови навык $autopilot с аргументами между линиями ниже и веди прогон по нему.\n\n"
                "-----\n" + brief(data, stage) + "-----\n")
    return head + body.rstrip() + "\n\n" + CODEX_RULES.replace("{program_py}", Path(__file__).resolve().as_posix()).replace("{stage}", stage["id"])


def codex_command() -> list[str]:
    """Как запускать codex: `CODEX_CLI_PATH` (бинарник приложения Codex) или `codex` из PATH; .py — через python (тесты)."""
    import shutil
    path = os.environ.get("CODEX_CLI_PATH") or shutil.which("codex")
    if not path:
        raise ProgramError("codex не найден: нет CODEX_CLI_PATH и codex в PATH")
    return [sys.executable, path] if path.endswith(".py") else [path]


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":  # os.kill(pid, 0) на Windows убивает процесс — только OpenProcess
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _codex_spawn(root: Path, stage: dict, args: list[str], tag: str) -> dict:
    runs = root / ".autopilot" / "program-runs"
    runs.mkdir(parents=True, exist_ok=True)
    ignore = root / ".autopilot" / ".gitignore"
    have = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if "program-runs/" not in have:
        ignore.write_text("\n".join(have + ["program-runs/"]) + "\n", encoding="utf-8")
    n = len((stage.get("codex") or {}).get("runs") or []) + 1
    base = runs / f"{stage['id']}-{n:02d}-{tag}"
    events, last, errors = base.with_suffix(".jsonl"), base.with_suffix(".last.txt"), base.with_suffix(".log")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with open(events, "wb") as out, open(errors, "wb") as err:
        proc = subprocess.Popen([*codex_command(), *args[:-1], "-o", str(last), args[-1]], cwd=root,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=err, creationflags=flags,
                                start_new_session=os.name != "nt")
    return {"pid": proc.pid, "events": events.relative_to(root).as_posix(), "last": last.relative_to(root).as_posix(),
            "log": errors.relative_to(root).as_posix(), "tag": tag, "at": now()}


def cmd_codex_run(root: Path, sid: str, exec_args: list[str] | None = None) -> str:
    data = load(root)
    stage = stage_of(data, sid)
    if stage["status"] not in ACTIVE:
        raise ProgramError(f"этап {sid} не начат — сначала `start {sid}`")
    codex = stage.setdefault("codex", {"runs": [], "threadId": None})
    if codex["runs"] and pid_alive(codex["runs"][-1]["pid"]):
        raise ProgramError(f"прогон этапа {sid} уже идёт (pid {codex['runs'][-1]['pid']}) — `codex-status {sid}`")
    codex["execArgs"] = list(exec_args) if exec_args else codex.get("execArgs") or list(CODEX_EXEC_ARGS)
    run = _codex_spawn(root, stage, ["exec", "--json", *codex["execArgs"], codex_stage_prompt(data, stage)], "exec")
    codex["runs"].append(run)
    stage["sessionId"] = f"codex-exec:{run['pid']}"
    save(root, data)
    return f"этап {sid}: codex exec запущен (pid {run['pid']}), события — {run['events']}"


def _codex_events(root: Path, run: dict) -> tuple[str | None, str | None]:
    """thread_id из `thread.started` и тип последнего значимого события (`turn.completed`, `turn.failed`, `error`)."""
    path = root / run["events"]
    thread, last = None, None
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type") if isinstance(event, dict) else None
            if kind == "thread.started":
                thread = event.get("thread_id") or thread
            if kind in ("turn.started", "turn.completed", "turn.failed", "error"):
                last = kind
    return thread, last


def job_states(data: dict) -> list[dict]:
    """Проверка долгих работ вне чата (D47) для оркестратора Codex: у него нет сторожа, он проверяет при каждом пробуждении."""
    out = []
    stage = active_stage(data)
    jobs, expired = split_jobs(data, stage or {}, None)
    for job in jobs + expired:
        state = probe_job(job)
        entry = {"label": job["label"], "state": "expired" if job in expired else state, "until": job["until"]}
        if job in expired:  # D50: срок вышел, этап не сдан — «срок вышел», а не тишина
            entry["message"] = JOB_EXPIRED.format(label=job["label"], probe=job["probe"], until=job["until"], state=JOB_STATE_RU[state])
        elif state == "dead":  # готовый текст для `codex-answer`
            entry["message"] = JOB_DEAD.format(label=job["label"], probe=job["probe"], minutes="несколько", until=job["until"])
        out.append(entry)
    return out


def cmd_codex_status(root: Path, sid: str | None) -> dict:
    """Процесс жив / ход закончен, thread_id, последнее сообщение этапа и вердикт program.py (без записи)."""
    data = load(root)
    stage = stage_of(data, sid) if sid else active_stage(data)
    if stage is None or not (stage.get("codex") or {}).get("runs"):
        raise ProgramError("нет этапа с запуском codex — сначала `codex-run <ID>`")
    codex = stage["codex"]
    run = codex["runs"][-1]
    thread, last_event = _codex_events(root, run)
    if thread and thread != codex.get("threadId"):
        codex["threadId"] = thread
        save(root, data)
    last_file = root / run["last"]
    alive = pid_alive(run["pid"])
    return {"stage": stage["id"], "process": "running" if alive else "exited", "pid": run["pid"],
            "threadId": codex.get("threadId"), "lastEvent": last_event,
            "lastMessage": last_file.read_text(encoding="utf-8", errors="replace").strip() if last_file.exists() else None,
            "check": evaluate(root, data, stage, with_gate=False) if not alive else None,
            "jobs": job_states(data), "log": run["log"]}


def cmd_codex_answer(root: Path, sid: str, text: str) -> str:
    data = load(root)
    stage = stage_of(data, sid)
    codex = stage.get("codex") or {}
    if not codex.get("runs"):
        raise ProgramError(f"у этапа {sid} не было запуска codex — `codex-run {sid}`")
    if pid_alive(codex["runs"][-1]["pid"]):
        raise ProgramError(f"прогон этапа {sid} ещё идёт — ответ отправляется, когда он закончит ход")
    thread = codex.get("threadId") or _codex_events(root, codex["runs"][-1])[0]
    if not thread:
        raise ProgramError(f"нет thread_id у прогона этапа {sid} — см. {codex['runs'][-1]['events']}")
    run = _codex_spawn(root, stage, ["exec", "resume", thread, "--json", *codex.get("execArgs", CODEX_EXEC_ARGS), text], "resume")
    codex["runs"].append(run)
    codex["threadId"] = thread
    stage["sessionId"] = f"codex-exec:{run['pid']}"
    save(root, data)
    return f"этап {sid}: ответ отправлен (codex exec resume {thread}, pid {run['pid']})"


def cmd_prompt(root: Path, sid: str, manual: bool, after_signal: bool = False) -> str:
    data = load(root)
    stage = stage_of(data, sid)
    if stage["status"] not in ACTIVE:
        raise ProgramError(f"этап {sid} не начат — сначала `start {sid}`")
    return stage_prompt(data, stage, manual, after_signal, dashboard=page_url(root, "dashboard.html"))


def cmd_wake_prompt(root: Path) -> str:
    """Самодостаточное задание разовой задачи приложения «продолжить программу после сброса лимита» (D22).

    Задача не может запускать сессии и писать через SendMessage (спайк L1, L2): она будит чат этапа инструментом
    send_message, а оркестратор продолжает цепочку по уведомлению о нём (L3).
    """
    data = load(root)
    stage = active_stage(data)
    if stage is None or not stage.get("sessionId"):
        raise ProgramError("нет идущего этапа с сессией — сначала start, сессия этапа и bind")
    orchestrator = (data.get("pause") or {}).get("orchestrator") or data.get("orchestrator")
    script = Path(__file__).resolve().as_posix()
    cmd = f'python "{script}" --project "{root.as_posix()}"'
    tell = (f"отправь оркестратору (`mcp__ccd_session_mgmt__send_message`, session_id `{orchestrator}`)"
            if orchestrator else "напиши в итоге")
    return (
        f"Продолжение программы прогонов Autopilot «{data['goal']}» после сброса лимита подписки (решение D22 autopilot-kit).\n"
        f"Проект: `{root}`. Файлы проекта не меняй, кроме команды program.py ниже. Ничего не коммить и не пушь.\n"
        "Инструмент SendMessage из этой сессии не работает — для сообщений только `mcp__ccd_session_mgmt__send_message` "
        "(загрузи через ToolSearch, если нужно; нет ToolSearch в этом билде — он уже загружен). Запускать новые сессии эта сессия не может — и не нужно.\n\n"
        f"1. `{cmd} status`. Если этап {stage['id']} уже не идёт (сдан, провален) — ответь «Программа уже продолжилась, "
        "ничего не делаю» и закончи.\n"
        "2. Прочитай лимиты (`mcp__ccd_session_mgmt__get_usage`). Если 5-часовой или недельный лимит всё ещё 100% — "
        f"{tell} «Лимит ещё не сброшен: <окно>, сброс <время>. Поставь новую задачу продолжения» и закончи.\n"
        f"3. Посмотри сессию этапа `{stage['sessionId']}` (`mcp__ccd_session_mgmt__get_session`). Если `isRunning: true` — "
        f"ответь «Этап работает, ничего не делаю», выполни `{cmd} resume` и закончи.\n"
        f"4. Выполни `{cmd} resume`, затем отправь сессии этапа `{stage['sessionId']}` (`send_message`) сообщение: "
        f"«{RESUME_SIGNAL}»\n"
        f"5. Если доставка не удалась — {tell} «Лимит восстановился, но чат этапа {stage['id']} не принял сигнал — "
        "продолжи программу» и закончи.\n"
        f"6. Отправь уведомление одной строкой: «Лимит восстановился — этап {stage['id']} продолжен» (PushNotification; "
        "нет его в этом билде — `mcp__ccd_turn__wrap_up` с `recap`, D48). "
        "Ответь итогом одной строкой.\n"
    )


STATUS_RU = {"pending": "ждёт", "running": "идёт", "waiting": "ждёт владельца", "passed": "сдан",
             "failed": "провален", "skipped": "пропущен"}


def cell(text) -> str:
    return str(text or "—").replace("|", "\\|").replace("\n", " ")


def render(data: dict) -> str:
    out = [MARKER, f"# Программа: {data['goal']}", ""]
    plan = f"`{data['plan']}`" if data.get("plan") else "нет (этапы заданы в программе)"
    out.append(f"План: {plan} · режим прогонов: {data['mode']} · обновлено: {data.get('updatedAt') or '—'}")
    if data.get("pause"):
        out += ["", f"**{pause_text(data['pause'])}**"]
    out += ["", "## Этапы", "", "| Этап | Что | Статус | Итог |", "|---|---|---|---|"]
    for s in data["stages"]:
        verdict = s.get("verdict") or {}
        outcome = verdict.get("result") or "; ".join(verdict.get("reasons") or []) or s.get("note")
        out.append(f"| {cell(s['id'])} | {cell(s['title'])} | {STATUS_RU[s['status']]} | {cell(outcome)} |")
    made = decisions(data)
    out += ["", "## Решения владельца", ""]
    out += [f"- {q['id']}. {q['question']} — **{q['answer']}**"
            + (" *(допущение)*" if q.get("by") == "assumption" else "") for q in made] or ["—"]
    pending = open_questions(data)
    out += ["", "## Открытые вопросы", ""]
    out += [f"- {q['id']}" + (f" (до {q['stage']})" if q.get("stage") else "") + f". {q['question']}"
            f" Рекомендация: {q['recommended']}" for q in pending] or ["—"]
    tasks = [t for t in data.get("ownerTasks") or [] if not t.get("done")]
    out += ["", "## Задачи для владельца", ""]
    out += [f"- {t['id']}" + (f" (этап {t['stage']})" if t.get("stage") else "") + f". {t['text']}" for t in tasks] or ["—"]
    out += ["", "## Как продолжить", "",
            "Новый чат Claude Code в папке проекта → `/autopilot-program`: оркестратор продолжит с этого файла."]
    return "\n".join(out) + "\n"


def cmd_status(root: Path) -> str:
    return render(load(root))


# ── ход программы: проценты, строка трека, страница ─────────────────────────

def stage_percent(stage: dict, run: dict | None) -> int:
    """Процент этапа: сданный — 100; идущий — по фазам Autopilot, внутри «Разработки» — по тикетам."""
    if stage["status"] == "passed":
        return 100
    if stage["status"] not in ACTIVE or not run or not run_belongs(stage, run):
        return 0
    if run.get("finishedAt"):
        return 100
    status = {s.get("id"): s.get("status") for s in run.get("stages") or []}
    tickets = run.get("tickets") or []
    done_tickets = sum(t.get("status") == "done" for t in tickets)
    total = 0.0
    for pid, _name, weight in PHASES:
        if status.get(pid) in ("done", "skipped"):
            total += weight
        elif status.get(pid) == "active":
            share = done_tickets / len(tickets) if pid == "build" and tickets else 0.5
            total += weight * share
    return min(99, int(total))


def current_phase(run: dict | None) -> str | None:
    active = next((s.get("id") for s in (run or {}).get("stages") or [] if s.get("status") == "active"), None)
    return next((name for pid, name, _ in PHASES if pid == active), None)


def program_percent(data: dict, run: dict | None) -> int:
    counted = [s for s in data["stages"] if s["status"] != "skipped"]
    if not counted:
        return 0
    return int(sum(stage_percent(s, run) for s in counted) / len(counted))


# ── лимиты подписки (D22) ───────────────────────────────────────────────────

START_LIMITS = {"5h": 85, "week": 90}   # новый этап не начинается, если хоть одно окно не ниже порога
INSURE_LIMITS = {"5h": 80, "week": 90}  # во время этапа — заранее поставить задачу продолжения
RESUME_DELAY_MIN = 2


def window_kind(label: str) -> str | None:
    text = (label or "").lower()
    if "5-hour" in text or "5 hour" in text or "5-час" in text:
        return "5h"
    if "week" in text or "недел" in text:
        return "week"
    return None


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    return Path(override) if override else kit_home() / ".codex"


def _find_rate_limits(node):
    if isinstance(node, dict):
        if isinstance(node.get("rate_limits"), dict):
            return node["rate_limits"]
        for value in node.values():
            found = _find_rate_limits(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_rate_limits(value)
            if found is not None:
                return found
    return None


def codex_usage(home: Path | None = None) -> dict:
    """Лимиты Codex в виде ответа get_usage Claude (D24): последние `rate_limits` из самого свежего файла сессии.

    Окно до 5 часов — «5-hour limit (Codex)», от недели — «Weekly (Codex)»; resets_at — секунды Unix.
    """
    sessions = (home or codex_home()) / "sessions"
    files = sorted(sessions.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if sessions.is_dir() else []
    for path in files[:20]:
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                limits = _find_rate_limits(json.loads(line))
            except ValueError:
                continue
            if not limits:
                continue
            windows = []
            for key in ("primary", "secondary"):
                w = limits.get(key)
                if not isinstance(w, dict) or not isinstance(w.get("used_percent"), (int, float)):
                    continue
                minutes = w.get("window_minutes") or 0
                label = "5-hour limit (Codex)" if minutes <= 300 else "Weekly (Codex)" if minutes >= 7 * 24 * 60 else f"{minutes}-minute limit (Codex)"
                resets = w.get("resets_at")
                windows.append({"label": label, "percentUsed": w["used_percent"],
                                "resetsAt": datetime.fromtimestamp(resets, timezone.utc).isoformat() if isinstance(resets, (int, float)) else None})
            return {"plan": {"status": "ok", "plan": limits.get("plan_type"), "windows": windows, "source": path.name}}
    return {"plan": {"status": "unavailable", "note": f"в {sessions} нет rate_limits — запустите любой ход в Codex"}}


def cmd_limits(usage: dict, phase: str, root: Path | None = None) -> dict:
    """Решение по лимитам из ответа get_usage: go / pause (новый этап не начинать) / insure (поставить задачу продолжения).

    phase: start — перед запуском этапа или между этапами; running — этап идёт.
    Окно на 100% — пауза в любой фазе. Время продолжения — сброс самого позднего из сработавших окон + 2 минуты.
    `plan.status` — авторитетное подтверждение привода (T19.8): `ok` → drive claude (лимиты подписки читаются —
    это не гейтвей, как бы ни выглядело окружение), `not_applicable` → drive claude-gate. При заданном root
    подтверждение пишется в program.json (`drive`) и правит привод в `orchestratorMachine`, если он был записан
    неверно, — сторож не примет своего оркестратора за чужой.
    """
    plan = usage.get("plan") if isinstance(usage.get("plan"), dict) else usage
    if not isinstance(plan, dict) or plan.get("status") != "ok":
        status = (plan or {}).get("status")
        if root is not None:
            confirmed = drive_confirmed(usage)
            if confirmed:
                try:
                    heal_drive(root, confirmed)
                except (OSError, ProgramError, ValueError):
                    pass  # program.json ещё нет или не читается — нечем лечить
        if status == "not_applicable":
            # D48: привод «Claude Desktop Gate» — трафик через гейтвей организации, окон подписки нет;
            # это не «лимиты не прочитаны», а «лимиты не применяются»: §5a навыка пропускается целиком
            return {"decision": "go", "limits": "not_applicable", "drive": "claude-gate", "status": status,
                    "note": "лимиты подписки не применяются (трафик через гейтвей организации — привод Claude "
                            "Desktop Gate, D48): пауз и задач продолжения нет; за остановками следят сторож (D28) "
                            "и `job set` (D47)"}
        return {"decision": "go", "note": "лимиты не прочитаны — продолжаю без них", "status": status}
    if root is not None:
        confirmed = drive_confirmed(usage)
        if confirmed:
            try:
                heal_drive(root, confirmed)  # статус ok: подписка настоящая — окружение могло врать (прокси в BASE_URL)
            except (OSError, ProgramError, ValueError):
                pass
    drive_field = {"drive": "claude"} if drive_confirmed(usage) else {}
    limits = START_LIMITS if phase == "start" else INSURE_LIMITS
    hit = []
    for window in plan.get("windows") or []:
        kind = window_kind(window.get("label", ""))
        percent = window.get("percentUsed")
        if kind is None or not isinstance(percent, (int, float)):
            continue
        if percent >= 100 or percent >= limits[kind]:
            hit.append(window)
    if not hit:
        return {"decision": "go", **drive_field}
    binding = max(hit, key=lambda w: _instant(w.get("resetsAt") or ""))
    resets = _instant(binding.get("resetsAt") or "")
    resume = (resets + timedelta(minutes=RESUME_DELAY_MIN)).astimezone() if resets.year > 1 else None
    exhausted = any(w.get("percentUsed", 0) >= 100 for w in hit)
    return {"decision": "pause" if phase == "start" or exhausted else "insure", **drive_field,
            "window": binding.get("label"), "percent": binding.get("percentUsed"),
            "resetsAt": binding.get("resetsAt"), "resumeAt": resume.isoformat(timespec="seconds") if resume else None}


PAUSE_REASONS = ("limit", "owner", "other")
OWNER_RESUME_SIGNAL = ("Стоп владельца снят — продолжай прогон этапа с того места, где остановился. Ожидание владельца в "
                       "state.js снято; если нет — выполни `python .autopilot/ap.py answered`.")


def pause_reason(pause: dict) -> str:
    return pause.get("reason") or "limit"  # записи до D46 — всегда лимит


def local_when(stamp: str | None) -> str | None:
    """Время для человека; год — когда он не текущий (2099-01-01 в местном поясе — это 31.12.2098, а не «31.12»)."""
    moment = _instant(stamp or "")
    if moment.year == 1:
        return stamp
    local = moment.astimezone()
    return local.strftime("%d.%m %H:%M" if local.year == datetime.now().year else "%d.%m.%Y %H:%M")


def auto_resumes(pause: dict) -> bool:
    """Продолжится ли программа сама: только пауза по лимиту со сроком (D22); стоп владельца снимает только владелец."""
    return pause_reason(pause) == "limit" and bool(pause.get("until"))


def pause_text(pause: dict) -> str:
    reason = pause_reason(pause)
    detail = pause.get("text") or pause.get("window")
    when = local_when(pause.get("until")) if pause.get("until") else None
    if reason == "limit":
        return f"Пауза до {when} — {detail or 'лимит'}; продолжу сам"
    head = "Пауза по слову владельца" if reason == "owner" else "Пауза"
    return (head + (f" (срок {when})" if when else "") + (f": {detail}" if detail else "")
            + " — продолжу только после снятия: `program.py resume`")


def cmd_pause(root: Path, until: str | None = None, window: str | None = None, orchestrator: str | None = None,
              reason: str | None = None, text: str | None = None) -> str:
    """Пауза программы. limit (по умолчанию) — продолжит задача сброса лимита (D22);
    owner/other (D46) — автопродолжения нет, срок необязателен и только справочный, снимает `resume`."""
    reason = reason or "limit"
    if reason not in PAUSE_REASONS:
        raise ProgramError(f"--reason — одно из: {', '.join(PAUSE_REASONS)}")
    if until is None and reason == "limit":
        raise ProgramError("для паузы по лимиту нужен --until (ISO 8601 с поясом); остановка владельцем — `--reason owner`")
    if until is not None and _instant(until).year == 1:
        raise ProgramError("--until — время в ISO 8601 с поясом, например 2026-10-23T11:12:00+03:00")
    data = load(root)
    data["pause"] = {"reason": reason, "until": until, "window": window, "text": text, "since": now(),
                     "orchestrator": orchestrator}
    save(root, data)
    out = pause_text(data["pause"])
    if reason != "limit":
        out += "\nАвтопродолжения нет. Вернуть в работу — `program.py resume`; что ещё держит дашборд — `program.py why-paused`."
    return out


def wake_task_id(root: Path) -> str:
    """Имя разовой задачи приложения «продолжить после сброса лимита» (навык §5a)."""
    return f"autopilot-program-resume-{root.name}"


# ── квота гейтвея (T21.9): на приводе claude-gate единственный сигнал лимита — текст отказа 429 ──

QUOTA_MARK = re.compile(r"\b429\b|quota|квот", re.I)
QUOTA_RESET = re.compile(r"reset(?:s|ting)?\s+(?:at|on)?\s*(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", re.I)
GATEWAY_WINDOW = "квота гейтвея (token-plan)"


def parse_quota_reset(text: str) -> datetime | None:
    """Время сброса квоты из текста отказа гейтвея («The quota will reset at 12-07 16:00:00 UTC»).

    Года в тексте нет — берётся ближайший будущий (квота месячная, сброс не может быть позже чем через год);
    время считается UTC — отказ пилота logscan 08.11.2026 печатал именно так.
    """
    match = QUOTA_RESET.search(text or "")
    if not match:
        return None
    month, day, hour, minute = (int(match.group(i)) for i in (1, 2, 3, 4))
    second = int(match.group(5) or 0)
    now_utc = datetime.now(timezone.utc)
    for year in (now_utc.year, now_utc.year + 1):
        try:
            moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except ValueError:
            return None
        if moment > now_utc:
            return moment
    return None


def cmd_quota_pause(root: Path, text: str | None, orchestrator: str | None = None) -> str:
    """Исчерпание квоты гейтвея (T21.9): пауза по лимиту до сброса + 2 мин — механика D22, но сигнал не из get_usage.

    На приводе claude-gate `get_usage.plan.status = not_applicable`, поэтому §5a квоту не видит, и исчерпание выглядит
    как обычный сбой: без этой команды программа продолжала бы будить этапы, а они — бить в мёртвый гейтвей.
    Квота месячная (подтверждено пилотом 08.11: владелец сменил тариф, работа продолжилась) — сброс может быть очень
    далеко, поэтому инструкция включает обязательное уведомление владельцу с вариантами (смена тарифа/провайдера,
    перенос программы, другая машина), а зарегистрированные долгие работы помечаются `quotaSuspect`: остановка по квоте
    рвёт фоновых исполнителей приложения, и их «жива» больше не достоверно.
    """
    if not text or not QUOTA_MARK.search(text):
        raise ProgramError("текст не похож на отказ квоты (нет «429» или «quota») — передайте текст отказа дословно")
    reset = parse_quota_reset(text)
    if reset is None:
        raise ProgramError("в тексте отказа не найдено время сброса (ожидалось вида «will reset at 12-07 16:00:00 UTC»); "
                           "если время неизвестно — `pause --reason other --text \"квота гейтвея исчерпана\"` и вопрос владельцу")
    resume = (reset + timedelta(minutes=RESUME_DELAY_MIN)).astimezone()
    out = cmd_pause(root, until=resume.isoformat(timespec="seconds"), window=GATEWAY_WINDOW,
                    orchestrator=orchestrator, reason="limit",
                    text=f"квота гейтвея исчерпана (429); сброс {reset.strftime('%d.%m.%Y %H:%M UTC')}")
    data = load(root)
    stage = active_stage(data)
    lines = [out, "", "Что сделать дальше (T21.9):"]
    if stage is not None and stage.get("sessionId"):
        lines.append(f"1. Разовая задача приложения `{wake_task_id(root)}`: fireAt = {resume.isoformat(timespec='seconds')}, "
                     "prompt = вывод `program.py wake-prompt` без правок — она разбудит чат этапа на сбросе (D22).")
    else:
        lines.append("1. Идущего этапа с сессией нет — задача продолжения не нужна: пауза стоит до слова владельца "
                     "(`resume` или `/autopilot-program` после сброса).")
    lines.append(f"2. ОБЯЗАТЕЛЬНО уведомление владельцу — сброс может быть очень далеко (квота месячная): «Квота гейтвея "
                 f"исчерпана — пауза до {resume.strftime('%d.%m.%Y %H:%M')}» и варианты: сменить тариф или провайдера "
                 "(на ваше «продолжай» сниму паузу — `resume`, он же отключит задачу продолжения), перенести программу, "
                 "продолжить на другой машине (подписочный привод); ничего не делать — продолжу сам в это время. "
                 "`why-paused` и дашборд показывают причину («квота гейтвея») и срок.")
    jobs = [j for j in data.get("jobs") or []
            if isinstance(j, dict) and _instant(j.get("until") or "") > datetime.now(timezone.utc)]
    if jobs:
        for job in jobs:
            job["quotaSuspect"] = now()  # проверка «жива» больше не достоверна: остановка рвёт фоновых исполнителей приложения
        save(root, data)
        lines.append("3. Зарегистрированные долгие работы помечены как требующие перепроверки (`quotaSuspect` в `job list`): "
                     "отказ квоты рвёт фоновых исполнителей приложения — после возобновления проверь каждую по месту "
                     "(не по слову этапа), мёртвые перезапусти и перерегистрируй (`job set`), закончившиеся сними "
                     f"(`job clear`). Работы: " + ", ".join(f"«{j.get('label')}»" for j in jobs) + ".")
    lines.append("4. Не повторяй запросы к гейтвею и не буди этап до сброса: каждая попытка бьёт в мёртвую квоту. Закончи ход.")
    return "\n".join(lines)


def cmd_resume(root: Path, keep_wait: bool = False) -> str:
    """Снимает всё, что держит дашборд «ждущим» после слов владельца (D46): паузу, задачи «ожидание паузы», флаг ожидания
    идущего этапа. Задачу продолжения в приложении и сообщение сессии этапа делает оркестратор — команда их называет."""
    data = load(root)
    was = data.pop("pause", None)
    lines = ["пауза снята" if was else "паузы не было"]
    closed = [t for t in data.get("ownerTasks") or [] if not t.get("done") and t.get("kind") == "pause"]
    for task in closed:
        task["done"] = now()
    if closed:
        lines.append("закрыты задачи владельца «ожидание паузы»: " + ", ".join(t["id"] for t in closed))
    save(root, data)
    stage = active_stage(data)
    if stage is not None and not keep_wait:
        _mine, waiting = run_waiting(root, stage)
        if waiting:
            try:
                lines.append(cmd_stage_unwait(root, stage["id"]))
            except ProgramError as error:
                lines.append(f"ожидание этапа {stage['id']} ({waiting['kind']}) осталось: {error}")
    if was:
        lines.append(f"Задача продолжения в приложении: если `{wake_task_id(root)}` включена — отключи "
                     "(`mcp__scheduled-tasks__update_scheduled_task`, `enabled: false`).")
        if stage is not None and stage.get("sessionId"):
            if str(stage["sessionId"]).startswith("codex-exec:"):
                lines.append(f"Этап {stage['id']} в Codex: `program.py codex-answer {stage['id']} \"{OWNER_RESUME_SIGNAL}\"`")
            else:
                lines.append(f"Сессии этапа {stage['id']} (`{stage['sessionId']}`) — `send_message`: «{OWNER_RESUME_SIGNAL}»")
    return "\n".join(lines)


def cmd_why_paused(root: Path) -> str:
    """Диагностика (D46): все причины, по которым дашборд «ждущий» (оранжевый или фиолетовый), и чем снять каждую."""
    data = load(root)
    items: list[str] = []
    pause = data.get("pause")
    if pause:
        late = auto_resumes(pause) and _instant(pause["until"]) <= datetime.now(timezone.utc)
        items.append(f"Пауза программы ({pause_reason(pause)}){' — срок вышел, но не снята' if late else ''}: "
                     f"{pause_text(pause)}\n   снять: `program.py resume`")
    for q in open_questions(data):
        items.append(f"Вопрос владельцу {q['id']}" + (f" (до {q['stage']})" if q.get("stage") else "") + f": {q['question']}\n"
                     f"   снять: `program.py answer {q['id']}` (без --answer — по рекомендации)")
    for t in data.get("ownerTasks") or []:
        if not t.get("done"):
            pause_kind = t.get("kind") == "pause"
            items.append(f"Задача владельца {t['id']}{' [ожидание паузы]' if pause_kind else ''}"
                         + (f" (этап {t['stage']})" if t.get("stage") else "") + f": {t['text']}\n"
                         f"   снять: `program.py owner-task done {t['id']}`" + (" или `resume`" if pause_kind else ""))
    stage = active_stage(data)
    if stage is not None:
        _mine, waiting = run_waiting(root, stage)
        if waiting:
            held = wait_blockers(data, stage)
            since = _minutes_since(waiting.get("since"))
            age = f", {int(since // 60)} ч {int(since % 60)} мин" if since is not None else ""
            how = (f"держат: {', '.join(held)} — сначала их; затем " if held else "вопросов и задач для него нет — ")
            items.append(f"Этап {stage['id']} ждёт владельца в state.js ({waiting['kind']}{age}): "
                         f"{waiting.get('note') or 'без пояснения'}\n   {how}"
                         f"снять: `program.py stage unwait {stage['id']}` (или `resume`); либо сессия этапа сама `ap.py answered`")
        elif stage["status"] == "waiting":
            items.append(f"Этап {stage['id']} в program.json «waiting», а в state.js ожидания нет\n"
                         f"   снять: `program.py stage unwait {stage['id']}`")
    app = (f"Не видно отсюда: задача продолжения в приложении `{wake_task_id(root)}` "
           "(`mcp__scheduled-tasks__list_scheduled_tasks`) — если включена, а программа уже идёт, отключи.")
    if not items:
        return ("Явных причин нет: паузы, вопросов и задач владельца нет, флага ожидания у идущего этапа нет."
                + (f"\n{app}" if stage is not None else ""))
    numbered = [f"{n}. {text}" for n, text in enumerate(items, 1)]
    return "\n".join(["Что держит дашборд (снимать по порядку; потом `program.py track`):", *numbered, app])


def reserve_empty(data: dict) -> bool:
    """Следующий этап некуда запустить (T21.5): резерв пуст, чата сданного этапа для очистки нет, а ждущий этап есть.

    Резерв пополняется только в ходе, начатом словами владельца (D40) — предупреждать надо заранее, пока этап идёт,
    а не в момент перехода, когда программа уже встала и просит «продолжай».
    """
    return bool(next_pending(data)) and not (data.get("pool") or []) and not recyclable(data)


def cmd_track(root: Path) -> str:
    """Строка для чата: «M1 ✓ → M2 ● Разработка · тикеты 5/12 · 47% → M3 ○ · программа 36%»."""
    data = load(root)
    run = read_run(root)
    marks = {"passed": "✓", "pending": "○", "failed": "✗", "skipped": "–"}
    parts = []
    for stage in data["stages"]:
        if stage["status"] == "skipped":  # пропущенные (в том числе разбитые на части) только шумят
            continue
        if stage["status"] not in ACTIVE:
            parts.append(f"{stage['id']} {marks[stage['status']]}")
            continue
        mine = run if run and run_belongs(stage, run) else None
        waiting = (mine or {}).get("waiting")
        if isinstance(waiting, dict) and waiting.get("kind"):
            parts.append(f"{stage['id']} ⏸ ждёт тебя ({waiting['kind']})"
                         + (" — вопросов и задач в программе нет, флаг мог устареть: `why-paused`"
                            if stale_wait(data, stage, waiting) else ""))
            continue
        bits = [f"{stage['id']} ●", current_phase(mine) or "запускается"]
        tickets = (mine or {}).get("tickets") or []
        if tickets:
            bits.append(f"тикеты {sum(t.get('status') == 'done' for t in tickets)}/{len(tickets)}")
        bits.append(f"{stage_percent(stage, run)}%")
        parts.append(" ".join(bits[:2]) + "".join(f" · {b}" for b in bits[2:]))
    line = " → ".join(parts) + f" · программа {program_percent(data, run)}%"
    if not data.get("pause") and reserve_empty(data):
        line += (" · ⚠ резерв пуст: когда этап сдастся, следующий не запустить без вашего слова — "
                 "напишите что-нибудь оркестратору, он пополнит резерв")
    return f"⏸ {pause_text(data['pause'])} · {line}" if data.get("pause") else line


def page_port(root: Path) -> int:
    """Порт страницы программы: постоянный для папки проекта, разный у разных проектов."""
    import zlib
    return 8700 + zlib.crc32(os.path.abspath(root).lower().encode("utf-8")) % 200


def page_template() -> Path:
    return Path(__file__).with_name(PAGE_TEMPLATE)


PAGE_MARKER = "autopilot-kit: дашборд программы"
BUILD_PLACEHOLDER = "__PAGE_BUILD__"


def page_build() -> str:
    """Версия шаблона страницы: уходит в program.js и в саму страницу — открытая вкладка со старым кодом перезагружается."""
    import hashlib
    template = page_template()
    return hashlib.sha1(template.read_bytes()).hexdigest()[:10] if template.is_file() else ""


def page_text() -> str:
    return page_template().read_text(encoding="utf-8").replace(BUILD_PLACEHOLDER, page_build())


def refresh_page(root: Path) -> None:
    """Страница, которая уже лежит в проекте, обновляется вместе с program.js: иначе вкладка, открытая со старым кодом
    (приложение держит панель месяцами), так и осталась бы со старой логикой опроса."""
    page = root / ".autopilot" / PAGE_NAME
    if not page.exists() or not page_template().is_file():
        return
    text = page_text()
    try:
        if page.read_text(encoding="utf-8") != text:
            page.write_text(text, encoding="utf-8")
    except OSError:
        pass
SERVE_FILES = ("program-serve.pid", "program-serve.log")


def page_url(root: Path, name: str = PAGE_NAME) -> str:
    return f"http://localhost:{page_port(root)}/{name}"


def links_line(root: Path) -> str:
    """Вторая строка трека: ссылки на дашборды — всегда под рукой, листать чат не нужно (D25)."""
    return f"Дашборд: [программа]({page_url(root)}) · [текущий прогон]({page_url(root, 'dashboard.html')})"


def server_state(port: int) -> str:
    """ours — наш сервер отдаёт страницу программы; foreign — порт занят чем-то другим; down — никого;
    stuck — порт слушают, но не отвечают (зависший сервер: запускать второй рядом нельзя)."""
    import socket
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/{PAGE_NAME}", timeout=3) as reply:
            return "ours" if PAGE_MARKER in reply.read(4096).decode("utf-8", "replace") else "foreign"
    except urllib.error.HTTPError:
        return "foreign"
    except OSError:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        except OSError:
            return "down"
        return "stuck"
    except Exception:  # RemoteDisconnected и подобное: сервер принял соединение и оборвал его
        return "stuck"


def stop_listeners(port: int) -> None:
    """Останавливает наши зависшие http.server на порту (только процессы http.server/program.py; чужие не трогает)."""
    if os.name != "nt":
        return
    # и слушатель порта, и все дубли, которые когда-то сели на тот же порт (на Windows их пускал SO_REUSEADDR)
    script = (f"Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object {{ $_.CommandLine -match "
              f"'(http\\.server|serve_forever).*\\b{port}\\b.*\\.autopilot' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], timeout=20, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def ensure_page(root: Path) -> None:
    autopilot = root / ".autopilot"
    template = page_template()
    if not template.is_file():
        raise ProgramError(f"нет шаблона страницы {template} — запустите python -m kit install")
    page = autopilot / PAGE_NAME
    text = page_text()
    if not page.exists() or page.read_text(encoding="utf-8") != text:
        page.write_text(text, encoding="utf-8")
    ignore = autopilot / ".gitignore"
    have = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    missing = [name for name in (PAGE_NAME, data_js_path(root).name, *SERVE_FILES) if name not in have]
    if missing:
        ignore.write_text("\n".join(have + missing) + "\n", encoding="utf-8")


def ensure_server(root: Path) -> str:
    """Свой фоновый сервер дашборда на постоянном порту проекта: поднимает, если не отвечает (D25).

    Не зависит от того, закрыло ли приложение панель: оркестратор вызывает program.py на каждом пробуждении.
    """
    import time
    ensure_page(root)
    port = page_port(root)
    state = server_state(port)
    if state == "ours":
        return f"сервер дашборда работает: {page_url(root)}"
    if state == "foreign":
        return f"порт {port} занят другим процессом — дашборд можно открыть файлом {root / '.autopilot' / PAGE_NAME}"
    if state == "stuck":  # слушают, но не отвечают: старый зависший сервер убираем, второй рядом не заводим
        stop_listeners(port)
        time.sleep(0.5)
        if server_state(port) == "stuck":
            return f"порт {port} занят зависшим процессом, который не удалось остановить"
    autopilot = root / ".autopilot"
    log = open(autopilot / "program-serve.log", "ab")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    # без SO_REUSEADDR: на Windows http.server иначе позволяет второму процессу сесть на тот же порт (так копились дубли)
    # корень отдаёт страницу программы: панель приложения открывает конфигурацию launch.json по origin, без пути (T21.11)
    runner = ("import sys; from functools import partial; from http.server import SimpleHTTPRequestHandler as H, "
              "ThreadingHTTPServer as S\nS.allow_reuse_address = False\n"
              "class R(H):\n"
              "    def do_GET(self):\n"
              "        if self.path in ('/', ''):\n"
              "            self.send_response(302); self.send_header('Location', '/program.html'); self.end_headers()\n"
              "        else:\n"
              "            H.do_GET(self)\n"
              "S(('127.0.0.1', int(sys.argv[1])), partial(R, directory=sys.argv[2])).serve_forever()")
    proc = subprocess.Popen([sys.executable, "-c", runner, str(port), str(autopilot)],
                            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                            creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    log.close()
    (autopilot / "program-serve.pid").write_text(str(proc.pid), encoding="utf-8")
    for _ in range(20):
        if server_state(port) == "ours":
            return f"сервер дашборда поднят: {page_url(root)}"
        time.sleep(0.25)
    return f"сервер дашборда не ответил — см. {autopilot / 'program-serve.log'}"


def cmd_serve_foreground(root: Path) -> int:
    """Для старой конфигурации приложения (`.claude/launch.json`): держит порт за нашим сервером или сам отдаёт страницу."""
    import time
    ensure_page(root)
    port = page_port(root)
    if server_state(port) == "ours":
        while server_state(port) == "ours":  # наш фоновый сервер уже работает — приложению достаточно, что порт отвечает
            time.sleep(30)
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class RootToPage(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", ""):  # панель открывает конфигурацию по origin — сразу отдаём страницу программы (T21.11)
                self.send_response(302)
                self.send_header("Location", f"/{PAGE_NAME}")
                self.end_headers()
                return
            super().do_GET()

    handler = partial(RootToPage, directory=str(root / ".autopilot"))
    ThreadingHTTPServer.allow_reuse_address = False
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
    return 0


KIT_SERVER_CMD = re.compile(r"serve_forever|http\.server|program\.py")


def _cmdline_is_kit_server(cmdline: str, port: int) -> bool:
    """Командная строка похожа на наш фоновый сервер: код сервера + порт проекта или папка .autopilot.

    Фоновый сервер запускается как `python -c <runner> <port> <…/.autopilot>` (в коде есть serve_forever),
    панель приложения — `python …/program.py --project . serve --foreground` (ни порта, ни .autopilot там нет —
    её убивать нельзя: pid-файл ей не принадлежит, но совпадение pid возможно).
    """
    return bool(KIT_SERVER_CMD.search(cmdline)) and (str(port) in cmdline or ".autopilot" in cmdline)


def _process_cmdline(pid: int) -> str:
    """Командная строка процесса (best effort): пустая строка, если узнать не удалось — тогда решаем по имени образа."""
    if os.name != "nt":
        try:
            return Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace").replace("\0", " ").strip()
        except OSError:
            return ""
    # wmic из Windows 11 убирают — тот же источник, что у stop_listeners: PowerShell CIM
    script = f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (out.stdout or "").strip() if out.returncode == 0 else ""


def process_is_kit_server(pid: int, port: int) -> tuple[bool, str]:
    """(похож на наш сервер, пояснение для сообщения). T21.15a: личность перед остановкой обязательна —
    система могла переиспользовать pid из устаревшего pid-файла, а `taskkill /F` не оставляет процессу шанса
    сохраниться. Признаки: образ python*/pythonw (Windows) и, если командная строка доступна, — код сервера kit
    с портом проекта или .autopilot. Командная строка недоступна — достаточно имени образа."""
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False, "tasklist не ответил"
        first = (out.stdout or "").strip().splitlines()
        if not first or first[0].lower().startswith("info:"):
            return False, f"процесс {pid} не найден"
        image = first[0].split('","')[0].strip('"').lower()
        if image not in ("python.exe", "pythonw.exe"):
            return False, f"образ процесса — {image}, а не python"
    else:
        image = "posix"
        if not Path(f"/proc/{int(pid)}").exists():
            return False, f"процесс {pid} не найден"
    cmdline = _process_cmdline(pid)
    if cmdline and not _cmdline_is_kit_server(cmdline, port):
        return False, "командная строка не похожа на сервер kit"
    return True, image


def release_port_for_panel(root: Path) -> str | None:
    """T21.15: освободить порт проекта для панели приложения — она отказывается стартовать на занятом порту
    («Port <port> is required by this server but is in use by "python.exe"» — факт пилота logscan; autoPort уводит
    панель на свободный порт, где `serve --foreground` не работает, т.к. порт проекта занят).

    Останавливаем только свой фоновый сервер и только проверив личность процесса (T21.15a: pid из устаревшего
    pid-файла мог быть переиспользован системой — `taskkill /F` убил бы постороннего). Сервер панели
    (`serve --foreground`, pid-файл не пишет) и чужие процессы не трогаем. После этого панель занимает порт,
    а `track`/`check`/`page` видят его живым («ours» — страница та же, с маркером) и второго сервера не заводят (D25).
    """
    port = page_port(root)
    if server_state(port) != "ours":
        return None
    pid_file = root / ".autopilot" / "program-serve.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None  # порт держит не наш фоновый сервер (например, уже панель) — освобождать нечего
    if not pid_alive(pid):
        return None  # pid-файл устарел — живой процесс не наш
    ok, why = process_is_kit_server(pid, port)
    if not ok:
        return (f"ВНИМАНИЕ: порт {port} отвечает страницей kit, но процесс {pid} из pid-файла не похож на наш сервер "
                f"({why}) — не останавливаю: pid мог быть переиспользован, а принудительная остановка необратима. "
                "Панель может не стартовать на занятом порту: закройте процесс сами (или дождитесь перезапуска "
                "приложения) и повторите `page --launch`.")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return None
    try:
        pid_file.unlink()
    except OSError:
        pass
    return f"порт {port} освобождён для панели: фоновый сервер kit (pid {pid}) остановлен — панель займёт его сама"


def cmd_page(root: Path, launch: bool) -> list[str]:
    """Кладёт страницу в .autopilot/, прячет её с данными от git; с launch — конфигурация сервера в .claude/launch.json
    и освобождение порта под панель приложения (T21.15)."""
    data = load(root)
    ensure_page(root)
    save(root, data)  # свежий program.js
    port = page_port(root)
    lines = [f"страница: {root / '.autopilot' / PAGE_NAME}", f"адрес: {page_url(root)}"]
    if launch:
        lines.append(write_launch(root, port))
        released = release_port_for_panel(root)
        if released:
            lines.append(released)
        lines.append('теперь откройте панель: mcp__Claude_Browser__preview_start с name: "autopilot-program", '
                     "затем mcp__ccd_view__show_pane с pane: \"preview\" (T21.15)")
    return lines


def write_launch(root: Path, port: int) -> str:
    """Сливает конфигурацию autopilot-program в .claude/launch.json проекта; чужие конфигурации не трогает."""
    path = root / ".claude" / "launch.json"
    # приложение запускает serve --foreground: если фоновый сервер program.py уже держит порт, он его не перебивает (D25)
    config = {"name": LAUNCH_NAME, "runtimeExecutable": "python",
              "runtimeArgs": [Path(__file__).resolve().as_posix(), "--project", ".", "serve", "--foreground"],
              "port": port}
    if path.exists():
        try:
            launch = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ProgramError(f"{path} не разбирается ({error}) — поправьте файл или удалите его") from error
    else:
        launch = {"version": "0.0.1", "configurations": []}
    others = [c for c in launch.get("configurations") or [] if c.get("name") != LAUNCH_NAME]
    launch["configurations"] = others + [config]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(launch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"сервер страницы: {path}, конфигурация «{LAUNCH_NAME}», порт {port}"


def cmd_report(root: Path) -> str:
    data = load(root)
    out = [f"# Отчёт программы: {data['goal']}", ""]
    passed = [s for s in data["stages"] if s["status"] == "passed"]
    left = [s for s in data["stages"] if s["status"] not in ("passed", "skipped")]
    out += ["## Сданы", ""]
    for s in passed:
        verdict = s.get("verdict") or {}
        kind = " (документы, кода продукта нет)" if verdict.get("deliverable") == "docs" else ""
        out.append(f"- {s['id']} {s['title']}{kind}: {verdict.get('result') or s.get('note') or '—'}")
    out += ["—"] if not passed else []
    out += ["", "## Осталось", ""]
    out += [f"- {s['id']} {s['title']} — {STATUS_RU[s['status']]}"
            + (": " + "; ".join((s.get("verdict") or {}).get("reasons") or []) if s["status"] == "failed" else "")
            for s in left] or ["—"]
    owner = [q for q in decisions(data) if q.get("by") == "owner"]
    assumed = [q for q in decisions(data) if q.get("by") in ("assumption", "auto")]
    out += ["", "## Решения владельца", ""] + ([f"- {q['id']}. {q['question']} — {q['answer']}" for q in owner] or ["—"])
    assumptions = [f"- {q['id']}. {q['question']} — {q['answer']}" for q in assumed]
    for s in passed:
        assumptions += [f"- {s['id']}: {a}" for a in (s.get("verdict") or {}).get("assumptions") or []]
    out += ["", "## Допущения за владельца", ""] + (assumptions or ["—"])
    tasks = [t for t in data.get("ownerTasks") or [] if not t.get("done")]
    if tasks:
        out += ["", "## Задачи для владельца", ""] + [f"- {t['id']}. {t['text']}" for t in tasks]
    closed_noted = [t for t in data.get("ownerTasks") or [] if t.get("done") and t.get("note")]
    if closed_noted:  # T21.7: пояснения к закрытым задачам видны в отчёте
        out += ["", "## Закрытые задачи владельца", ""] + [f"- {t['id']}. {t['text']} — {t['note']}" for t in closed_noted]
    remaining = open_questions(data)
    if remaining:
        out += ["", "## Вопросы без ответа", ""] + [f"- {q['id']}. {q['question']}" for q in remaining]
    return "\n".join(out) + "\n"


def read_gate_log(root: Path) -> list[dict]:
    """Строки журнала гейта .autopilot-kit/gate_log.jsonl (T17.3); битые строки пропускаются."""
    entries = []
    try:
        lines = (root / ".autopilot-kit" / "gate_log.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _duration(started: str | None, finished: str | None) -> str:
    if not started:
        return "—"
    end = _instant(finished) if finished else datetime.now(timezone.utc)
    minutes = max(0, int((end - _instant(started)).total_seconds() // 60))
    return f"{minutes // 60} ч {minutes % 60:02d} мин" + ("" if finished else " (идёт)")


METRIC_COLUMNS = ("Этап", "Вердикт", "Длительность", "Гейт: прогонов", "блоков", "отпусков", "Нестабильные",
                  "Вопросы владельцу", "Автоответы и допущения", "Ремонты", "Этап долга")


def stage_metrics(data: dict, stage: dict, log: list[dict]) -> dict:
    sid = stage["id"]
    mine = [e for e in log if e.get("stage") == sid]
    flaky = {t for e in mine for t in e.get("flaky") or []}
    flaky |= {f.split(" (", 1)[0] for f in (stage.get("verdict") or {}).get("flaky") or []}
    questions = [q for q in data["questions"] if q.get("stage") == sid and q.get("answer") is not None]
    verdict = STATUS_RU.get(stage["status"], stage["status"])
    if stage.get("autoAccepted"):
        verdict += " (принят автоматически)"
    elif stage["status"] == "passed" and (stage.get("verdict") or {}).get("verdict") == "failed":
        verdict += " (принят как есть)"
    return {
        "stage": sid, "verdict": verdict, "duration": _duration(stage.get("startedAt"), stage.get("finishedAt")),
        "runs": sum(e.get("result") in ("pass", "block", "loop-release") for e in mine),
        "blocks": sum(e.get("result") == "block" for e in mine),
        "releases": sum(e.get("result") == "loop-release" for e in mine),
        "flaky": len(flaky),
        "owner": sum(q.get("by") == "owner" for q in questions),
        "auto": sum(q.get("by") in ("auto", "assumption") for q in questions),
        "repairs": int(stage.get("repairs") or 0),
        "debt": any(s["id"] == f"{sid}f" for s in data["stages"]),
    }


def cmd_metrics(root: Path) -> str:
    """Отчёт о пользе комплекта (T17.3, основа T9.1): по этапам и итог — гейт, нестабильные, вопросы, ремонты, долги."""
    data = load(root)
    log = read_gate_log(root)
    rows = [stage_metrics(data, s, log) for s in data["stages"] if s["status"] not in ("pending", "skipped")]
    out = [f"# Метрики программы: {data['goal']}", "",
           "| " + " | ".join(METRIC_COLUMNS) + " |", "|" + "---|" * len(METRIC_COLUMNS)]
    keys = ("stage", "verdict", "duration", "runs", "blocks", "releases", "flaky", "owner", "auto", "repairs")
    for row in rows:
        out.append("| " + " | ".join(cell(row[k]) if row[k] != 0 else "0" for k in keys)
                   + " | " + ("да" if row["debt"] else "нет") + " |")
    totals = {k: sum(row[k] for row in rows) for k in keys[3:]}
    out.append("| **Итого** | " + f"сдано {sum(s['status'] == 'passed' for s in data['stages'])} из "
               f"{sum(s['status'] != 'skipped' for s in data['stages'])} | — | "
               + " | ".join(str(totals[k]) for k in keys[3:]) + f" | {sum(row['debt'] for row in rows)} |")
    results: dict[str, int] = {}
    for entry in log:
        results[str(entry.get("result"))] = results.get(str(entry.get("result")), 0) + 1
    out += ["", "## Журнал гейта", ""]
    if not log:
        out.append("Журнала нет (`.autopilot-kit/gate_log.jsonl`): гейт ещё не запускался с T17.3 — "
                   "колонки гейта и нестабильных показывают нули.")
    else:
        out.append(f"Записей {len(log)} с {log[0].get('at')} по {log[-1].get('at')}; вне этапов программы — "
                   f"{sum(1 for e in log if not e.get('stage'))}.")
        out.append("Итоги: " + ", ".join(f"{name} {count}" for name, count in sorted(results.items())) + ".")
        seconds = [c.get("seconds") or 0 for e in log for c in e.get("commands") or []]
        if seconds:
            out.append(f"Время команд гейта: всего {round(sum(seconds) / 60)} мин, самая долгая {max(seconds)} с.")
    return "\n".join(out) + "\n"


# ── командная строка ────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="program", description="Программа прогонов Autopilot")
    parser.add_argument("--project", type=Path, default=None, help="папка проекта (по умолчанию — ближайшая вверх)")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--goal", required=True)
    init.add_argument("--plan")
    init.add_argument("--mode", choices=MODES, default="full")  # D29: этапы без вопросов брифинга
    stage = sub.add_parser("stage").add_subparsers(dest="action", required=True)
    add = stage.add_parser("add")
    add.add_argument("id")
    add.add_argument("--title", required=True)
    add.add_argument("--task", required=True)
    add.add_argument("--plan-ref")
    add.add_argument("--criterion", action="append", default=[])
    put = stage.add_parser("set")
    put.add_argument("id")
    put.add_argument("--status", required=True, choices=("pending", "skipped", "passed"))
    put.add_argument("--note")
    rep = stage.add_parser("repair")
    rep.add_argument("id")
    acc = stage.add_parser("accept")
    acc.add_argument("id")
    acc.add_argument("--note")
    pdn = stage.add_parser("prev-done")
    pdn.add_argument("id")
    pdn.add_argument("--session", help="закрыть только эту прежнюю сессию (по умолчанию все незакрытые)")
    aut = sub.add_parser("autonomy")
    aut.add_argument("value", choices=("full", "ask"))
    appr = sub.add_parser("approve")
    appr.add_argument("action", choices=("add", "list"))
    appr.add_argument("text", nargs="?")
    appr.add_argument("--env", action="append", default=[])
    appr.add_argument("--stage")
    appr.add_argument("--permission", help="точное имя MCP-инструмента (mcp__…__…): дописать в permissions.allow "
                                           "настроек пользователя (T21.4б); шаблоны и широкие правила отклоняются")
    job = sub.add_parser("job")
    job.add_argument("action", choices=("set", "clear", "list"))
    job.add_argument("--label")
    job.add_argument("--probe")
    job.add_argument("--until")
    job.add_argument("--no-check", action="store_true", help="не запускать проверку при регистрации (работа ещё не стартует)")
    otask = sub.add_parser("owner-task")
    otask.add_argument("action", choices=("add", "done"))
    otask.add_argument("text")
    otask.add_argument("--stage")
    otask.add_argument("--kind", choices=("pause",), help="pause — «ожидание паузы»: закроет resume (D46)")
    otask.add_argument("--unwait", action="store_true", help="done: заодно снять ожидание этапа, если держать нечему (D46)")
    otask.add_argument("--note", help="done: пояснение к закрытию задачи — в её запись и в отчёт (T21.7)")
    cont = stage.add_parser("continue")
    cont.add_argument("id")
    unw = stage.add_parser("unwait")
    unw.add_argument("id")
    unw.add_argument("--force", action="store_true", help="вопреки открытым вопросам, задачам и свежей записи этапа")
    mode = sub.add_parser("mode")
    mode.add_argument("value", choices=MODES)
    plan_check = sub.add_parser("plan-check")
    plan_check.add_argument("file", type=Path)
    plan_load = sub.add_parser("plan-load")
    plan_load.add_argument("file", type=Path)
    sub.add_parser("plan-template")
    wat = sub.add_parser("watch")
    wat.add_argument("--json", action="store_true")
    sub.add_parser("watch-prompt")
    conf = sub.add_parser("confirm-owner")
    conf.add_argument("--absent", action="store_true",
                      help="сессия оркестратора в этом профиле не найдена — глушить программу до подтверждения (T19.9)")
    pl = sub.add_parser("pool")
    pl.add_argument("action", choices=("add", "drop", "take", "need", "list", "release"))
    pl.add_argument("session", nargs="?")
    pl.add_argument("--json", action="store_true")
    sub.add_parser("pool-prompt")
    sig = sub.add_parser("signal")
    sig.add_argument("id")
    sub.add_parser("setup-check")
    orc = sub.add_parser("orchestrator")
    orc.add_argument("--session", required=True)
    orc.add_argument("--usage", help="ответ get_usage: авторитетное подтверждение привода (T19.8) — plan.status ok/not_applicable")
    crun = sub.add_parser("codex-run")
    crun.add_argument("id")
    crun.add_argument("--exec-arg", action="append", default=[], help="замена доступа по умолчанию (повторяемый)")
    cstat = sub.add_parser("codex-status")
    cstat.add_argument("id", nargs="?")
    cans = sub.add_parser("codex-answer")
    cans.add_argument("id")
    cans.add_argument("text")
    cprompt = sub.add_parser("codex-prompt")
    cprompt.add_argument("id")
    left = sub.add_parser("leftovers")
    left.add_argument("id")
    left.add_argument("--done", action="store_true")
    left.add_argument("--note")
    ask = sub.add_parser("ask")
    ask.add_argument("id")
    ask.add_argument("--question", required=True)
    ask.add_argument("--recommended", required=True)
    ask.add_argument("--stage")
    ask.add_argument("--approval", action="store_true")
    answer = sub.add_parser("answer")
    answer.add_argument("id")
    answer.add_argument("--answer")
    answer.add_argument("--assumption", action="store_true")
    start = sub.add_parser("start")
    start.add_argument("id")
    start.add_argument("--adopt", action="store_true")
    bind = sub.add_parser("bind")
    bind.add_argument("id")
    bind.add_argument("--session", required=True)
    check = sub.add_parser("check")
    check.add_argument("id", nargs="?")
    check.add_argument("--record", action="store_true")
    check.add_argument("--no-gate", action="store_true")
    nxt = sub.add_parser("next")
    nxt.add_argument("--json", action="store_true")
    prompt = sub.add_parser("prompt")
    prompt.add_argument("id")
    prompt.add_argument("--manual", action="store_true")
    prompt.add_argument("--after-signal", action="store_true", help="этап на паузе по лимиту: начать по сигналу")
    sub.add_parser("status")
    sub.add_parser("track")
    limits = sub.add_parser("limits")
    limits.add_argument("--phase", choices=("start", "running"), required=True)
    source = limits.add_mutually_exclusive_group(required=True)
    source.add_argument("--usage", help="ответ get_usage (Claude Code): JSON-строка или путь к файлу")
    source.add_argument("--codex", action="store_true", help="лимиты Codex из файлов его сессий")
    pause = sub.add_parser("pause")
    pause.add_argument("--until", help="ISO 8601 с поясом; обязателен для --reason limit, у owner/other только справочный")
    pause.add_argument("--window")
    pause.add_argument("--reason", choices=PAUSE_REASONS, help="limit (по умолчанию) — продолжу сам; owner — стоп владельца; other")
    pause.add_argument("--text", help="пояснение для дашборда и track: что остановлено и почему")
    pause.add_argument("--orchestrator", help="id сессии оркестратора — задача продолжения напишет ему при сбое")
    quota = sub.add_parser("quota-pause")
    quota.add_argument("--text", required=True, help="текст отказа 429 дословно: из него берётся время сброса квоты гейтвея (T21.9)")
    quota.add_argument("--orchestrator", help="id сессии оркестратора — задача продолжения напишет ему при сбое")
    res = sub.add_parser("resume")
    res.add_argument("--keep-wait", action="store_true", help="не снимать ожидание владельца в state.js этапа")
    sub.add_parser("why-paused")
    sub.add_parser("wake-prompt")
    page = sub.add_parser("page")
    page.add_argument("--launch", action="store_true")
    serve = sub.add_parser("serve")
    serve.add_argument("--foreground", action="store_true", help="для конфигурации приложения в .claude/launch.json")
    rep_cmd = sub.add_parser("report")
    rep_cmd.add_argument("--metrics", action="store_true")
    return parser


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = build_parser().parse_args(argv)
    root = Path(os.path.abspath(args.project)) if args.project else find_project_root(Path.cwd())
    try:
        if (args.command in ("track", "page", "check", "status") and program_path(root).exists()
                and not os.environ.get("AUTOPILOT_KIT_NO_SERVE")):  # тесты не поднимают серверы
            try:  # дашборд всегда доступен: сервер поднимается заново, если приложение или перезагрузка его остановили
                serve_note = ensure_server(root)
            except (OSError, ProgramError) as error:
                serve_note = f"сервер дашборда не поднят: {error}"
            if args.command == "page":
                print(serve_note)
        if program_path(root).exists() and not os.environ.get("AUTOPILOT_KIT_NO_SERVE"):
            try:  # реестр программ машины — по нему ходит сторож (D28)
                register_program(root, load(root).get("goal"))
            except (OSError, ProgramError, ValueError):
                pass
        if program_path(root).exists() or args.command == "init":
            set_identity = ensure_git_identity(root)
            if set_identity:  # в stderr: stdout у команд бывает JSON
                print("git: не было автора коммитов, поставлен локально (без --global): " + ", ".join(set_identity),
                      file=sys.stderr)
        if args.command == "init":
            print(cmd_init(root, args.goal, args.plan, args.mode))
            if not os.environ.get("AUTOPILOT_KIT_NO_SERVE"):
                try:
                    register_program(root, args.goal)
                except ProgramError as error:
                    # T21.6: program.json уже создан — сказать об этом, иначе владелец не поймёт, что повторять init не нужно
                    print(f"Предупреждение: программа создана, но НЕ зарегистрирована в реестре машины ({error}).\n"
                          "Почините реестр и выполните любую команду (track/status) — регистрация повторится сама.",
                          file=sys.stderr)
                    raise
        elif args.command == "stage" and args.action == "add":
            print(cmd_stage_add(root, args.id, args.title, args.task, args.plan_ref, args.criterion))
        elif args.command == "stage" and args.action == "repair":
            print(cmd_stage_repair(root, args.id))
        elif args.command == "stage" and args.action == "accept":
            print(cmd_stage_accept(root, args.id, args.note))
        elif args.command == "stage" and args.action == "prev-done":
            print(cmd_stage_prev_done(root, args.id, args.session))
        elif args.command == "autonomy":
            print(cmd_autonomy(root, args.value))
        elif args.command == "approve":
            print(cmd_approve(root, args.action, args.text, args.env, args.stage, args.permission))
        elif args.command == "job":
            print(cmd_job(root, args.action, args.label, args.probe, args.until, check=not args.no_check))
        elif args.command == "owner-task":
            print(cmd_owner_task(root, args.action, args.text, args.stage, args.kind, args.unwait, args.note))
        elif args.command == "stage" and args.action == "continue":
            print(cmd_stage_continue(root, args.id))
        elif args.command == "stage" and args.action == "unwait":
            print(cmd_stage_unwait(root, args.id, args.force))
        elif args.command == "stage":
            print(cmd_stage_set(root, args.id, args.status, args.note))
        elif args.command == "mode":
            print(cmd_mode(root, args.value))
        elif args.command == "plan-check":
            result = cmd_plan_check(args.file)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        elif args.command == "plan-load":
            print("\n".join(cmd_plan_load(root, args.file)))
        elif args.command == "watch":
            results = cmd_watch()
            print(json.dumps(results, ensure_ascii=False, indent=2) if args.json else
                  "\n".join(f"{r.get('goal') or r['root']}: {r['action']} — {r.get('note')}" for r in results) or "программ нет")
        elif args.command == "watch-prompt":
            print(watch_prompt(), end="")
        elif args.command == "confirm-owner":
            print(cmd_confirm_owner(root, args.absent))
        elif args.command == "pool":
            print(cmd_pool(root, args.action, args.session, args.json))
        elif args.command == "pool-prompt":
            print(pool_prompt(load(root)), end="")
        elif args.command == "signal":
            print(cmd_signal(root, args.id), end="")
        elif args.command == "setup-check":
            print(cmd_setup_check(root))
        elif args.command == "orchestrator":
            usage = None
            if args.usage:
                raw = Path(args.usage).read_text(encoding="utf-8") if Path(args.usage).is_file() else args.usage
                try:
                    usage = json.loads(raw)
                except ValueError as error:
                    raise ProgramError(f"--usage: не JSON ({error})") from error
            print(cmd_orchestrator(root, args.session, usage))
        elif args.command == "codex-run":
            print(cmd_codex_run(root, args.id, args.exec_arg))
        elif args.command == "codex-status":
            print(json.dumps(cmd_codex_status(root, args.id), ensure_ascii=False, indent=2))
        elif args.command == "codex-answer":
            print(cmd_codex_answer(root, args.id, args.text))
        elif args.command == "codex-prompt":
            data = load(root)
            print(codex_stage_prompt(data, stage_of(data, args.id)), end="")
        elif args.command == "leftovers":
            result = cmd_leftovers(root, args.id, args.done, args.note)
            print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "plan-template":
            print(plan_template_path().read_text(encoding="utf-8"), end="")
        elif args.command == "ask":
            print(cmd_ask(root, args.id, args.question, args.recommended, args.stage, args.approval))
        elif args.command == "answer":
            print(cmd_answer(root, args.id, args.answer, args.assumption))
        elif args.command == "start":
            print(cmd_start(root, args.id, args.adopt))
        elif args.command == "bind":
            print(cmd_bind(root, args.id, args.session))
        elif args.command == "check":
            print(json.dumps(cmd_check(root, args.id, args.record, not args.no_gate), ensure_ascii=False, indent=2))
        elif args.command == "next":
            result = cmd_next(root)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(result["brief"] if result["ready"] else f"Нельзя начать: {result['why']}")
                for q in result.get("questions", []):
                    print(f"- {q['id']}. {q['question']} Рекомендация: {q['recommended']}")
            return 0 if result["ready"] else 1
        elif args.command == "prompt":
            print(cmd_prompt(root, args.id, args.manual, args.after_signal), end="")
        elif args.command == "track":
            print(cmd_track(root))
            print(links_line(root))
        elif args.command == "limits":
            if args.codex:
                usage = codex_usage()
            else:
                raw = Path(args.usage).read_text(encoding="utf-8") if Path(args.usage).is_file() else args.usage
                try:
                    usage = json.loads(raw)
                except ValueError as error:
                    raise ProgramError(f"--usage: не JSON ({error})") from error
            print(json.dumps(cmd_limits(usage, args.phase, None if args.codex else root), ensure_ascii=False, indent=2))
        elif args.command == "pause":
            print(cmd_pause(root, args.until, args.window, args.orchestrator, args.reason, args.text))
        elif args.command == "quota-pause":
            print(cmd_quota_pause(root, args.text, args.orchestrator))
        elif args.command == "wake-prompt":
            print(cmd_wake_prompt(root), end="")
        elif args.command == "resume":
            print(cmd_resume(root, args.keep_wait))
        elif args.command == "why-paused":
            print(cmd_why_paused(root))
        elif args.command == "serve":
            if args.foreground:
                return cmd_serve_foreground(root)
            print(ensure_server(root))
        elif args.command == "page":
            print("\n".join(cmd_page(root, args.launch)))
        elif args.command == "status":
            print(cmd_status(root), end="")
        elif args.command == "report":
            print(cmd_metrics(root) if args.metrics else cmd_report(root), end="")
    except ProgramError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
