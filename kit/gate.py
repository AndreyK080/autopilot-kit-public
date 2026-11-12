"""Гейт качества: запускает проверки проекта из .autopilot-kit/project.toml.

Файл самодостаточен (только стандартная библиотека): install копирует его в ~/.autopilot-kit/bin/gate.py.
Обычный запуск: код 0 — гейт пройден или не настроен, 1 — провал.
--hook claude-stop / codex-stop: хук Stop Claude Code или Codex (JSON со stdin; поля те же: cwd, transcript_path, stop_hook_active);
провал — код 2 и вывод в stderr, приложение продолжает работу. В чате оркестратора программы гейт не проверяется, но хук (только
claude-stop) возвращает его к работе, если за ход не вызван show_pane (D38: дашборд всегда справа); второй раз за ход не требует.
--hook agy-stop: хук Stop Antigravity (JSON со stdin: conversationId, workspacePaths, fullyIdle, terminationReason);
ответ — JSON в stdout, всегда код 0: {"decision": "continue", "reason": …} возвращает агента к работе, любое другое значение отпускает.
Хук не блокирует остановку, когда Autopilot ждёт владельца (поле waiting в .autopilot/state.js)
и когда тестов ещё нет (pytest вернул код 5). Обычный запуск в обоих случаях строгий.
Без --project корень проекта ищется вверх от текущей папки (или cwd события хука) до .autopilot-kit/project.toml.
Вывод всегда в UTF-8: и в консоли cp1251, и в канале хука.
Когда команды прошли, гейт сверяет тесты с базой этапа (D41): удалённые файлы тестов, меньше собранных тестов pytest,
новые пропуски (skip, xfail) у тестов из базы и любой .only блокируют, если тест не назван в строке D## прогона.
Нет базы — только предупреждение.
Упавшая команда pytest повторяется один раз только для упавших (--lf): прошли — гейт пройден с пометкой «нестабильные»,
тесты копятся в .autopilot-kit/flaky.json (program.py check выносит их в остаток этапа).
Каждый запуск в проекте с папкой .autopilot-kit дописывает строку в .autopilot-kit/gate_log.jsonl (время, режим, хост,
этап, команды с кодами и длительностью, итог, нестабильные) — по нему program.py report --metrics считает пользу.
Хост claude-stop уточняется (D48, сужено T19.8): явная фиксация владельца `drive = "…"` в project.toml проекта или
profile.toml машины, иначе CLAUDE_CODE_ENTRYPOINT=claude-desktop-3p → в журнал пишется host claude-gate.
ANTHROPIC_BASE_URL признаком привода НЕ является: подписочное приложение тоже задаёт его (локальный прокси).
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

TAIL_CHARS = 4000
DEFAULT_TIMEOUT = 600
LOOP_LIMIT = 2  # столько провалов подряд (с stop_hook_active) — и остановку пропускаем
PYTEST_NO_TESTS = 5  # код выхода pytest «не собрано ни одного теста»
PYTEST_FAILED = 1  # код выхода pytest «есть упавшие тесты»; остальные коды (прерван, ошибка вызова) не повторяются
FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (.+?)(?: - .*)?$")
# pytest отдельным словом: «-m pytest», «pytest», «…\Scripts\pytest.exe», но не папка «pytest-of-user»
PYTEST_WORD = re.compile(r"""(?:^|[\s"'\\/])py\.?test(?:\.exe)?["']?(?:\s|$)""")
GATE_ENTRYPOINT = "claude-desktop-3p"  # признак привода «Claude Desktop Gate» (D48). ANTHROPIC_BASE_URL признаком
GATE_HOST = "claude-gate"              # НЕ является (T19.8): подписочное приложение тоже задаёт его (локальный прокси)
DRIVES = ("claude", "claude-gate", "codex")


def drive_of(env: dict | None = None) -> str:
    """Привод приложения по окружению процесса: claude-gate / codex / claude / unknown (D48, сужено T19.8).

    Хуки и program.py наследуют окружение приложения. Единственный признак гейтвея здесь — CLAUDE_CODE_ENTRYPOINT;
    он документацией не покрыт, поэтому владелец может зафиксировать привод явно (`drive` в project.toml/profile.toml,
    см. pinned_drive), а авторитетная поправка у оркестратора — plan.status из get_usage (program.py limits, T19.8).
    """
    env = os.environ if env is None else env
    if env.get("CLAUDE_CODE_ENTRYPOINT") == GATE_ENTRYPOINT:
        return GATE_HOST
    if env.get("CODEX_THREAD_ID"):
        return "codex"
    if env.get("CLAUDECODE"):
        return "claude"
    return "unknown"


def pinned_drive(project: Path | None = None) -> str | None:
    """Явная фиксация привода владельцем (T19.8): `drive = "…"` в `.autopilot-kit/project.toml` проекта,
    затем в `~/.autopilot-kit/profile.toml` машины."""
    home = Path(os.environ.get("AUTOPILOT_KIT_HOME") or Path.home())
    paths = ([Path(project) / ".autopilot-kit" / "project.toml"] if project is not None else [])
    paths.append(home / ".autopilot-kit" / "profile.toml")
    for path in paths:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        drive = data.get("drive") if isinstance(data, dict) else None
        if drive in DRIVES:
            return drive
    return None


def is_pytest(command: str) -> bool:
    return bool(PYTEST_WORD.search(command))


def config_path(project: Path) -> Path:
    return project / ".autopilot-kit" / "project.toml"


def state_path(project: Path) -> Path:
    return project / ".autopilot-kit" / "gate_state.json"


def flaky_path(project: Path) -> Path:
    return project / ".autopilot-kit" / "flaky.json"


def log_path(project: Path) -> Path:
    return project / ".autopilot-kit" / "gate_log.jsonl"


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def running_stage(project: Path) -> dict | None:
    """Идущий этап программы (последний начатый), если в .autopilot/program.json он есть."""
    try:
        program = json.loads((project / ".autopilot" / "program.json").read_text(encoding="utf-8"))
        stages = [s for s in program.get("stages", []) if isinstance(s, dict) and s.get("status") == "running"]
    except (OSError, ValueError, AttributeError):
        return None
    return max(stages, key=lambda s: str(s.get("startedAt") or "")) if stages else None


def log_run(project: Path, mode: str, host: str | None, result: str, record: dict | None = None) -> None:
    """Строка журнала гейта (T17.3). Пишется только в настроенный проект; ошибка записи гейт не ломает.

    result: pass, block, loop-release (отпуск по защите от зацикливания), skip-waiting (Autopilot ждёт владельца),
    skip-program-chat (чат оркестратора или сторожа), skip-unchanged (проект не менялся с зелёного гейта, D51), pane-reminder (D38), not-configured, config-error.
    """
    if not (project / ".autopilot-kit").is_dir():
        return
    stage = running_stage(project)
    entry = {"at": _stamp(), "mode": mode, "host": host, "stage": stage.get("id") if stage else None,
             "result": result, **(record or {})}
    try:
        with log_path(project).open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def find_project_root(start: Path) -> Path:
    """Ближайшая к start папка (она сама или выше), где есть .autopilot-kit/project.toml; иначе start.

    Оболочка Claude может стоять в подпапке проекта, и cwd в событии хука — тоже подпапка.
    """
    start = Path(os.path.abspath(start))  # не resolve: он превращает сетевой диск P: в UNC, а cmd.exe не умеет в нём работать
    for folder in (start, *start.parents):
        if config_path(folder).is_file():
            return folder
    return start


def load_config(project: Path) -> dict | None:
    path = config_path(project)
    if not path.exists():
        return None
    gate = tomllib.loads(path.read_text(encoding="utf-8")).get("gate", {})
    commands = gate.get("commands", [])
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        raise ValueError("gate.commands должен быть списком строк")
    timeout = int(gate.get("timeout_seconds", DEFAULT_TIMEOUT))
    hook_commands = gate.get("hook_commands")
    if hook_commands is not None and (not isinstance(hook_commands, list) or not hook_commands
                                      or not all(isinstance(c, str) for c in hook_commands)):
        raise ValueError("gate.hook_commands должен быть непустым списком строк")
    # D51: быстрый набор для хука Stop (приложение обрывает ход без вывода ~1000 с); полный `commands` — для приёмки и ручного гейта
    return {"commands": commands, "timeout": timeout, "hook_commands": hook_commands,
            "hook_timeout": int(gate.get("hook_timeout_seconds", min(timeout, HOOK_SLOW_SECONDS)))}


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, 9)


def autopilot_state(project: Path) -> dict | None:
    """Содержимое .autopilot/state.js оригинального Autopilot («window.STATE = {...}»); формат чужой — при неожиданности None."""
    try:
        raw = (project / ".autopilot" / "state.js").read_text(encoding="utf-8")
        body = raw.split("=", 1)[1] if "=" in raw.split("\n", 1)[0] else raw
        state = json.loads(body.strip().rstrip(";"))
    except (OSError, ValueError, IndexError):
        return None
    return state if isinstance(state, dict) else None


def autopilot_waiting(project: Path) -> str | None:
    """Чего ждёт Autopilot от владельца (briefing, spec, plan, action, stop) или None — тогда гейт работает как обычно."""
    waiting = (autopilot_state(project) or {}).get("waiting")
    kind = waiting.get("kind") if isinstance(waiting, dict) else None
    return kind if isinstance(kind, str) and kind else None


def run_command(command: str, cwd: Path, timeout: int, tail: bool = True) -> tuple[int | None, str]:
    """(код выхода или None при таймауте, хвост вывода ≤ 4000 символов; tail=False — весь вывод)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    kwargs = {} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(
        command, shell=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        code, note = proc.returncode, ""
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, _ = proc.communicate()
        code, note = None, f"[превышен таймаут {timeout} с]\n"
    text = note + out.decode("utf-8", errors="replace")
    return code, text[-TAIL_CHARS:] if tail else text


TEST_PATH = re.compile(
    r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.py|conftest\.py|[^/]+\.(?:test|spec)\.[^/]+)$"
    r"|(?:^|/)(?:tests|__tests__)/(?:[^/]+/)*[^/]+\.(?:py|js|jsx|ts|tsx|mjs|cjs)$"
)
SKIP_ADDED = re.compile(
    r"mark\.(?:skip|skipif|xfail)\b|\bpytest\.xfail\s*\(|\.skip\s*\(|\bunittest\.skip|@skip(?:If|Unless)?\b"
    r"|\.skipTest\s*\(|\bx(?:it|test|describe)\s*\("
)
FOCUS_ADDED = re.compile(r"\.only\s*\(")  # .only отключает все остальные тесты — блок и у нового теста
TEST_NAME = re.compile(
    r"""^\s*(?:async\s+)?def\s+(test\w*)|^\s*class\s+(Test\w*)|\b(?:it|test|describe)(?:\.\w+)?\s*\(\s*['"`]([^'"`]+)"""
)
DECISION_ROW = re.compile(r"\bD\d{2,}\b")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
COLLECTED = re.compile(r"(\d+)(?:/\d+)? tests? collected|collected (\d+) items?")
SUMMARY_PART = re.compile(r"(\d+) (?:passed|failed|skipped|xfailed|xpassed|errors?)\b")
VENV_DIR = re.compile(r"""(?<![\w.\-:/\\])(\.?venv)(?=[\\/])""")
MIN_NAME = 5  # короче — слишком легко случайно найти в строке D##


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search(path.replace("\\", "/")))


def _git(project: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=project, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None


def _paths(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


def stage_base(project: Path) -> tuple[str, str, str | None] | None:
    """(коммит базы, откуда он, папка прогона в .autopilot) или None.

    База — коммит старта идущего этапа программы (program.py start), иначе baseCommit незаконченного прогона Autopilot.
    """
    stage = running_stage(project)
    state = autopilot_state(project) or {}
    run_dir = state.get("dir") if isinstance(state.get("dir"), str) else None
    if stage and stage.get("baseCommit"):
        return str(stage["baseCommit"]), f"старт этапа {stage.get('id')}", stage.get("runDir") or run_dir
    if state.get("baseCommit") and not state.get("finishedAt"):
        return str(state["baseCommit"]), "начало прогона Autopilot", run_dir
    return None


def decision_rows(project: Path, run_dir: str | None) -> list[str]:
    """Строки D## из документов прогона (spec, manifest, решения): так записывается осознанное исключение."""
    folder = project / ".autopilot" / run_dir if run_dir else None
    rows = []
    for path in sorted(folder.rglob("*.md")) if folder and folder.is_dir() else ():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rows += [line for line in text.splitlines() if DECISION_ROW.search(line)]
    return rows


def _explained(names: list[str], rows: list[str]) -> bool:
    return any(len(name) >= MIN_NAME and any(name in row for row in rows) for name in names)


def _file_names(path: str) -> list[str]:
    name = path.rsplit("/", 1)[-1]
    return [path, name, name.split(".")[0]]


def _test_names(lines: list[str], index: int) -> list[str]:
    """Имя теста для добавленной строки: у декоратора — ниже, у пропуска в теле теста или describe — выше (включая её саму)."""
    around = lines[index:index + 15] if lines[index].lstrip().startswith("@") else reversed(lines[:index + 1])
    for line in around:
        match = TEST_NAME.search(line)
        if match:
            return [next(group for group in match.groups() if group)]
    return []


def _added_lines(diff: str) -> dict[str, list[int]]:
    """Номера добавленных строк (в рабочем дереве) по файлам из `git diff -U0`."""
    added, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None
        elif path and (match := HUNK.match(line)):
            start, count = int(match.group(1)), int(match.group(2) or 1)
            added.setdefault(path, []).extend(range(start, start + count))
    return added


def _renamed(project: Path, commit: str, path: str, candidates: list[str]) -> bool:
    """Удалённый файл тестов похож на один из новых — это переименование (число тестов сверит pytest)."""
    old = (_git(project, "show", f"{commit}:{path}") or "").splitlines()
    for new in candidates:
        try:
            lines = (project / new).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if difflib.SequenceMatcher(None, old, lines).ratio() >= 0.5:
            return True
    return False


def _existed_at_base(project: Path, commit: str, path: str, names: list[str], known: set[str], texts: dict) -> bool:
    """Был ли тест в базе: пропуск нового теста ничего не ослабляет (решение владельца к T17.1).

    Имя не найдено (пропуск всего модуля) — решает то, был ли в базе сам файл.
    """
    if path not in known:
        return False
    if path not in texts:
        texts[path] = _git(project, "show", f"{commit}:{path}") or ""
    return not names or any(name in texts[path] for name in names)


def _collect(command: str, cwd: Path, timeout: int) -> tuple[int, list[str]] | None:
    """(число собранных тестов, их id) для команды pytest или None, если сбор не удался."""
    code, out = run_command(f"{command} --collect-only --verbosity=-1", cwd, timeout, tail=False)
    if code == PYTEST_NO_TESTS:
        return 0, []
    if code != 0:
        return None
    ids = sorted({line.strip() for line in out.splitlines() if "::" in line and not line[:1].isspace()})
    match = COLLECTED.search(out)
    if match:
        return int(match.group(1) or match.group(2)), ids
    return (len(ids), ids) if ids else None


def _summary_count(output: str | None) -> int | None:
    """Число тестов из итоговой строки pytest («5 passed, 1 skipped in 0.1s»): без повторного сбора."""
    for line in reversed((output or "").splitlines()):
        parts = SUMMARY_PART.findall(line)
        if parts and " in " in line:
            return sum(int(number) for number in parts)
    return None


def _collect_at(project: Path, commit: str, command: str, timeout: int) -> tuple[int, list[str]] | None:
    """Сбор тестов на копии базы (git archive во временную папку); окружение .venv берётся из проекта."""
    with tempfile.TemporaryDirectory(prefix="gate-base-", ignore_cleanup_errors=True) as tmp:
        try:
            proc = subprocess.Popen(["git", "archive", "--format=tar", commit], cwd=project,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return None
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                archive.extractall(tmp, filter="data")
        except (tarfile.TarError, OSError):
            return None
        finally:
            proc.stdout.close()
            proc.wait()
        if proc.returncode != 0:
            return None
        local = VENV_DIR.sub(lambda m: str(project / m.group(1)) if (project / m.group(1)).is_dir() else m.group(1), command)
        return _collect(local, Path(tmp), timeout)


def _base_collection(project: Path, commit: str, command: str, timeout: int) -> tuple[int, list[str]] | None:
    """Сбор тестов базы: один раз на коммит и команду, дальше из gate_state.json."""
    cache = _load_state(project).get("testBase")
    if isinstance(cache, dict) and cache.get("commit") == commit:
        entry = (cache.get("counts") or {}).get(command)
        if isinstance(entry, dict):
            return int(entry.get("count", 0)), list(entry.get("ids") or [])
    else:
        cache = {"commit": commit, "counts": {}}
    result = _collect_at(project, commit, command, timeout)
    if result is not None:
        cache.setdefault("counts", {})[command] = {"count": result[0], "ids": result[1]}
        state = _load_state(project)
        state["testBase"] = cache
        _save_state(project, state)
    return result


def _node_names(node: str) -> list[str]:
    path, _, rest = node.partition("::")
    return [rest.rsplit("::", 1)[-1].split("[", 1)[0], node, *_file_names(path)]


def check_tests_kept(project: Path, commands: list[str], timeout: int,
                     outputs: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """(нарушения, пояснения) по сравнению с базой этапа (D41): удалённые файлы тестов, меньше тестов pytest,
    новые пропуски у тестов из базы, .only.

    Исключение — тест (или его файл) назван в строке D## прогона. Нет базы или git — проверка пропускается с пояснением.
    outputs: вывод уже выполненных команд гейта — число тестов берётся из итога pytest, сбор только при уменьшении.
    """
    base = stage_base(project)
    if base is None:
        return [], ["Проверка подгонки тестов пропущена: нет базы этапа (program.json или .autopilot/state.js)."]
    ref, origin, run_dir = base
    commit = (_git(project, "rev-parse", "--verify", "--quiet", ref + "^{commit}") or "").strip()
    listing = _git(project, "ls-tree", "-r", "-z", "--name-only", commit) if commit else None
    files = _git(project, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    untracked = _git(project, "ls-files", "-z", "--others", "--exclude-standard")
    diff = _git(project, "diff", "--no-color", "--no-ext-diff", "--no-renames", "-U0", commit, "--") if commit else None
    if None in (listing, files, untracked, diff):
        return [], [f"Проверка подгонки тестов пропущена: git не ответил или не нашёл коммит базы {ref} ({origin})."]
    notes = [f"Тесты сверены с базой: {origin}, коммит {commit[:7]}."]
    rows = decision_rows(project, run_dir)
    base_tests = [p for p in _paths(listing) if is_test_path(p)]
    known = set(base_tests)
    new_tests = [p for p in _paths(files) if is_test_path(p) and p not in known and (project / p).is_file()]
    problems = []
    for path in base_tests:
        if not (project / path).exists() and not _explained(_file_names(path), rows) \
                and not _renamed(project, commit, path, new_tests):
            problems.append(f"удалён файл тестов: {path}")
    base_texts: dict[str, str] = {}
    added: dict[str, list[int] | None] = dict(_added_lines(diff))
    for path in _paths(untracked):
        added.setdefault(path, None)  # новый файл вне git целиком — добавленные строки
    for path, numbers in added.items():
        if not is_test_path(path):
            continue
        try:
            lines = (project / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        indexes = range(len(lines)) if numbers is None else [n - 1 for n in numbers if 0 < n <= len(lines)]
        for index in indexes:
            line = lines[index]
            if not (FOCUS_ADDED.search(line) or SKIP_ADDED.search(line)):
                continue
            names = _test_names(lines, index)
            if not FOCUS_ADDED.search(line) and not _existed_at_base(project, commit, path, names, known, base_texts):
                continue
            if not _explained(names + _file_names(path), rows):
                problems.append(f"новый пропуск теста: {path}:{index + 1}: {line.strip()[:120]}")
    removed = any(not (project / p).exists() for p in base_tests)
    if removed or any(is_test_path(p) for p in added):
        for command in filter(is_pytest, commands):
            before = _base_collection(project, commit, command, timeout)
            quick = _summary_count((outputs or {}).get(command))
            if before is not None and quick is not None and quick >= before[0]:
                continue
            after = _collect(command, project, timeout)
            if before is None or after is None:
                notes.append(f"Число тестов не сравнить: сбор тестов не удался ({command}).")
                continue
            if after[0] >= before[0]:
                continue
            present = set(after[1])
            missing = [node for node in before[1] if node not in present]
            unexplained = [node for node in missing if not _explained(_node_names(node), rows)]
            if missing and not unexplained:
                continue
            listed = f": нет {', '.join(unexplained[:5])}" + (" и др." if len(unexplained) > 5 else "") if unexplained else ""
            problems.append(f"тестов стало меньше: {before[0]} → {after[0]} ({command}){listed}")
    return problems, notes


def failed_tests(output: str) -> list[str]:
    """id упавших тестов из краткой сводки pytest (строки «FAILED …» и «ERROR …»)."""
    found = []
    for line in output.splitlines():
        match = FAILED_TEST.match(line.strip())
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def record_flaky(project: Path, tests: list[str]) -> None:
    """Дописывает нестабильные тесты в flaky.json: сколько раз, когда впервые и последний раз."""
    path = flaky_path(project)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = data["tests"] if isinstance(data, dict) and isinstance(data.get("tests"), dict) else {}
    except (OSError, ValueError):
        known = {}
    stamp = _stamp()
    for test in tests:
        entry = known.get(test) if isinstance(known.get(test), dict) else {"count": 0, "first": stamp}
        entry.update(count=int(entry.get("count", 0)) + 1, last=stamp)
        known[test] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tests": known}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


TAMPER_HINT = (
    "Верни тесты. Если так и решено — запиши решение строкой D## с именем теста (или файла) в документах прогона "
    "(spec.md, manifest.md) и повтори."
)
LOOP_HINT = (
    "Подсказка (T21.8): если тесты написаны раньше реализации (ошибка сбора, модуль не найден) — это нормальная "
    "стадия работы: продолжай писать код и не заканчивай ход. Остановка разрешена вторым провалом подряд только "
    "чтобы не зациклиться — она не значит, что работу можно объявить готовой."
)


def run_gate(project: Path, allow_no_tests: bool = False, record: dict | None = None, hook: bool = False) -> tuple[bool, str]:
    """Выполняет команды по очереди, останавливаясь на первой неудачной; затем сверяет тесты с базой этапа.

    allow_no_tests: pytest без единого теста (код 5) не считается провалом — проект ещё без кода.
    record: сюда кладутся данные для журнала — commands (команда, код, секунды, повтор), flaky, tamper.
    hook: вызов из хука Stop — если в project.toml есть `hook_commands`, идёт быстрый набор вместо полного (D51).
    """
    config = load_config(project)
    if config is None:
        return True, "гейт не настроен"
    if hook and config.get("hook_commands"):
        config = {**config, "commands": config["hook_commands"], "timeout": config["hook_timeout"]}
    record = {} if record is None else record
    record.update(commands=[], flaky=[], tamper=[])
    lines, outputs, flaky = [], {}, record["flaky"]

    def timed(command: str, retry: bool = False) -> tuple[int | None, str]:
        started = time.monotonic()
        code, tail = run_command(command, project, config["timeout"])
        record["commands"].append({"command": command, "code": code, "seconds": round(time.monotonic() - started, 1),
                                   "retry": retry})
        return code, tail

    for command in config["commands"]:
        code, tail = timed(command)
        outputs[command] = tail
        lines.append(f"$ {command}\n{tail.rstrip()}")
        if allow_no_tests and code == PYTEST_NO_TESTS and is_pytest(command):
            lines.append("тестов пока нет — команда не считается провалом")
            continue
        if code == PYTEST_FAILED and is_pytest(command):
            retry_code, retry_tail = timed(f"{command} --lf", retry=True)
            lines.append(f"$ {command} --lf  (повтор только упавших)\n{retry_tail.rstrip()}")
            if retry_code == 0:
                tests = failed_tests(tail) or ["(имена в выводе не найдены)"]
                record_flaky(project, tests)
                flaky += tests
                lines.append(f"нестабильные: {', '.join(tests)} — упали и прошли при повторе")
                continue
        if code != 0:
            lines.append(f"ГЕЙТ НЕ ПРОЙДЕН: команда завершилась с ошибкой: {command}")
            return False, "\n".join(lines)
    if config["commands"]:
        problems, notes = check_tests_kept(project, config["commands"], config["timeout"], outputs)
        lines += notes
        record["tamper"] = problems
        if problems:
            lines.append("ГЕЙТ НЕ ПРОЙДЕН: тесты ослаблены по сравнению с базой этапа:")
            lines += [f"- {problem}" for problem in problems]
            lines.append(TAMPER_HINT)
            return False, "\n".join(lines)
    lines.append("ГЕЙТ ПРОЙДЕН" + (f" (нестабильные: {', '.join(flaky)})" if flaky else ""))
    return True, "\n".join(lines)


def _load_state(project: Path) -> dict:
    try:
        state = json.loads(state_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(project: Path, state: dict) -> None:
    path = state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_state(project: Path, conversation: str | None = None) -> int:
    """Провалы подряд; при заданной беседе чужой счётчик не учитывается."""
    state = _load_state(project)
    if conversation is not None and state.get("conversation") != conversation:
        return 0
    try:
        return int(state.get("consecutive_failures", 0))
    except (TypeError, ValueError):
        return 0


def _write_state(project: Path, failures: int, conversation: str | None = None) -> None:
    state = {"consecutive_failures": failures}
    if conversation is not None:
        state["conversation"] = conversation
    old = _load_state(project)
    if old.get("testBase"):
        state["testBase"] = old["testBase"]  # сбор тестов базы дорогой — не терять его вместе со счётчиком
    if old.get("green"):
        state["green"] = old["green"]
    _save_state(project, state)


GREEN_TTL_SECONDS = 6 * 3600
SERVICE_PREFIXES = (".autopilot/", ".autopilot-kit/", ".claude/", ".agents/", ".codex/")


def tree_fingerprint(project: Path) -> str | None:
    """Отпечаток проверяемого состояния проекта (D51): коммитнутое дерево и изменения рабочей копии без служебных папок
    программы/kit, конфигурация гейта и идущий этап. None — не git или git не ответил (пропускать гейт нельзя)."""
    tree = _git(project, "ls-tree", "-r", "-z", "HEAD")
    status = _git(project, "status", "--porcelain=v1", "-z", "-uall")
    if tree is None or status is None:
        return None
    digest = hashlib.sha256()
    for record in tree.split("\0"):
        if record and not record.split("\t", 1)[-1].startswith(SERVICE_PREFIXES):
            digest.update(record.encode("utf-8", "replace") + b"\0")
    items, index = status.split("\0"), 0
    while index < len(items):
        entry, index = items[index], index + 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            index += 1  # у переименования следом идёт прежний путь
        if path.startswith(SERVICE_PREFIXES):
            continue
        digest.update(f"{code} {path}\0".encode("utf-8", "replace"))
        try:
            target = project / path
            data = target.read_bytes() if target.stat().st_size <= 20_000_000 else f"big:{target.stat().st_size}".encode()
        except OSError:
            data = b"gone"
        digest.update(hashlib.sha256(data).digest())
    try:
        digest.update((project / ".autopilot-kit" / "project.toml").read_bytes())
    except OSError:
        pass
    stage = running_stage(project)
    digest.update(str(stage.get("id") if stage else None).encode())
    return digest.hexdigest()


def green_unchanged(project: Path, fingerprint: str | None) -> bool:
    """Прошлый гейт в хуке был зелёным на том же состоянии не позже GREEN_TTL_SECONDS назад (D51)."""
    if not fingerprint or os.environ.get("AUTOPILOT_KIT_GATE_ALWAYS"):
        return False
    green = _load_state(project).get("green")
    if not isinstance(green, dict) or green.get("fingerprint") != fingerprint:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(green["at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return False
    return 0 <= age <= GREEN_TTL_SECONDS


def mark_green(project: Path, fingerprint: str | None) -> None:
    if not fingerprint:
        return
    state = _load_state(project)
    state["green"] = {"fingerprint": fingerprint, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        _save_state(project, state)
    except OSError:
        pass


PROGRAM_CHAT_MARKERS = ("<command-name>/autopilot-program", '<scheduled-task name="autopilot-program-watchdog"')
PROGRAM_CHAT_STARTS = ("$autopilot-program", "/autopilot-program")  # Codex: навык вызывается словом `$имя` в начале сообщения
# Codex кладёт в начало транскрипта служебные «сообщения пользователя» (AGENTS.md, окружение) — это не первая реплика
CODEX_CONTEXT_STARTS = ("# AGENTS.md", "<environment_context>", "<user_instructions>", "<INSTRUCTIONS>", "<permissions")


def _user_text(entry: dict) -> str | None:
    """Текст реплики пользователя из строки транскрипта Claude Code или Codex; None — это не реплика."""
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    if isinstance(payload, dict):  # Codex: rollout-*.jsonl
        if entry.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
            content = payload.get("content")
        elif entry.get("type") == "event_msg" and payload.get("type") == "user_message":
            content = payload.get("message")
        else:
            return None
    elif entry.get("type") == "user" and not entry.get("isMeta"):  # Claude Code
        content = (entry.get("message") or {}).get("content")
    else:
        return None
    if isinstance(content, list):
        content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        return None
    return content


CONTINUED_START = "This session is being continued from a previous conversation"
PREVIOUS_TRANSCRIPT = re.compile(r"read the full transcript at:\s*(\S+\.jsonl)")
INVOKED_PROGRAM = re.compile(r"invoked\s+[`'\"]?/autopilot-program")
CHAIN_LIMIT = 8


def _first_user_text(path: str) -> str | None:
    """Первая реплика пользователя в транскрипте (служебные «сообщения» Codex пропускаются); None — не нашли или не прочесть."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    text = _user_text(json.loads(line))
                except ValueError:
                    continue
                if text is None or text.lstrip().startswith(CODEX_CONTEXT_STARTS):
                    continue
                return text
    except OSError:
        pass
    return None


def _kind_of_text(text: str) -> str | None:
    head = text[:300]
    if PROGRAM_CHAT_MARKERS[1] in head:
        return "watchdog"
    if PROGRAM_CHAT_MARKERS[0] in head:
        return "orchestrator"
    return "orchestrator-codex" if text.lstrip().startswith(PROGRAM_CHAT_STARTS) else None


def program_chat_kind(event: dict) -> str | None:
    """Вид чата программы по первой реплике пользователя в транскрипте: orchestrator (Claude), orchestrator-codex,
    watchdog или None (этап, обычный чат).

    Они не пишут код проекта, а гейт идёт минуты на каждом ходу и сбивает их красными тестами этапа.
    id чата в приложении (local_…) и session_id хука не совпадают, поэтому смотрим на начало транскрипта.
    Формат транскрипта Codex хук не гарантирует стабильным: при любой неожиданности чат считается обычным.

    D51: после сжатия контекста первая реплика транскрипта — «This session is being continued…» (пересказ), а не вызов
    навыка: оркестратор проект D стал «обычным чатом», и его хук гонял набор тестов по 8–20 мин на каждом
    ходу (приложение обрывает ход без вывода ~1000 с — владельцу выскакивало «Try again»). Вид берём у предыдущего
    транскрипта по ссылке из пересказа («read the full transcript at: …»), а если ссылки нет или она на тот же файл —
    по фразе пересказа «invoked /autopilot-program».
    """
    path = event.get("transcript_path")
    seen: set[str] = set()
    while path and len(seen) < CHAIN_LIMIT and path not in seen:
        seen.add(path)
        text = _first_user_text(str(path))
        if text is None:
            return None
        if not text.startswith(CONTINUED_START):
            return _kind_of_text(text)
        found = PREVIOUS_TRANSCRIPT.search(text)
        previous = found.group(1) if found else None
        if previous and previous not in seen and os.path.isfile(previous):
            path = previous
            continue
        return "orchestrator" if INVOKED_PROGRAM.search(text) else None
    return None


def is_program_chat(event: dict) -> bool:
    return program_chat_kind(event) is not None


PANE_REMINDER = (
    "Дашборд программы должен быть в панели справа при каждом ходе (D38). Перед концом хода вызови "
    "`mcp__ccd_view__show_pane` с `pane: \"preview\"` (инструмент не загружен и есть `ToolSearch` — загрузи "
    "`select:mcp__ccd_view__show_pane`; нет `ToolSearch` в этом билде — инструменты уже загружены, D48; "
    "вкладки с дашбордом нет — сначала `program.py page --launch`, затем `mcp__Claude_Browser__preview_start` "
    "с `name: \"autopilot-program\"` (T21.11), своего сервера не заводи). В браузере компьютера страницу не открывай "
    "и не проси владельца открыть: `start`, `explorer`, `open`, `Invoke-Item`, `webbrowser` запрещены (T21.15) — "
    "только панель приложения. Если приложение ответит, что чат не открыт "
    "в окне, — так и есть, ничего больше не делай. "
    "Текст пользователю повторно не пиши: вызови инструмент и закончи ход."
)


def _is_prompt(entry: dict) -> bool:
    """Строка транскрипта Claude Code — начало хода: реплика, уведомление или ответ хука; не результат инструмента."""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(p, dict) and p.get("type") != "tool_result" for p in content)
    return False


def turn_called_show_pane(path: str) -> bool | None:
    """Был ли в текущем ходу (после последней реплики) вызов show_pane для панели preview; None — транскрипт не прочесть."""
    called = False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if _is_prompt(entry):
                    called = False
                elif entry.get("type") == "assistant":
                    content = (entry.get("message") or {}).get("content")
                    for part in content if isinstance(content, list) else ():
                        if (isinstance(part, dict) and part.get("type") == "tool_use"
                                and str(part.get("name", "")).endswith("show_pane")
                                and (part.get("input") or {}).get("pane") == "preview"):
                            called = True
    except OSError:
        return None
    return called


def program_exists(project: Path) -> bool:
    return (project / ".autopilot" / "program.json").is_file()


def _passed(record: dict) -> str:
    return "pass" if "commands" in record else "not-configured"


HOOK_SLOW_SECONDS = 900   # приложение обрывает ход без вывода ~1000 с («timed out after … of inactivity» → «Try again»)
SLOW_NOTE = ("ВНИМАНИЕ: гейт в хуке шёл {seconds} с. Приложение обрывает ход, в котором нет вывода дольше ~1000 с, и владельцу "
             "выскакивает «Try again»: ускорь набор проверок (параллельный запуск, быстрый набор для хука, тяжёлое — в ручной "
             "`gate.py`) или раздели его (D51).")


def mark_slow(record: dict) -> str | None:
    """Пометка `slow` в записи журнала и текст предупреждения, если команды гейта шли дольше предела хука (D51)."""
    seconds = sum(c.get("seconds") or 0 for c in record.get("commands") or [] if isinstance(c, dict))
    if seconds < HOOK_SLOW_SECONDS:
        return None
    record["slow"] = True
    return SLOW_NOTE.format(seconds=int(seconds))


def hook_claude_stop(project: Path, event: dict, host: str = "claude") -> int:
    kind = program_chat_kind(event)
    if kind == "orchestrator" and not event.get("stop_hook_active") and program_exists(project):
        # D38: панель с дашбордом возвращается каждым ходом; второй раз за ход не требуем — защита от зацикливания
        if turn_called_show_pane(str(event.get("transcript_path"))) is False:
            log_run(project, "hook", host, "pane-reminder")
            print(PANE_REMINDER, file=sys.stderr)
            return 2
    if kind:
        log_run(project, "hook", host, "skip-program-chat", {"chat": kind})
        print("Гейт не проверяется: это чат оркестратора программы, код проекта в нём не меняется.", file=sys.stderr)
        return 0
    waiting = autopilot_waiting(project)
    if waiting:
        log_run(project, "hook", host, "skip-waiting", {"waiting": waiting})
        print(f"Гейт не проверяется: Autopilot ждёт владельца ({waiting}).", file=sys.stderr)
        return 0
    fingerprint = tree_fingerprint(project) if (project / ".autopilot-kit" / "project.toml").is_file() else None
    if green_unchanged(project, fingerprint):
        log_run(project, "hook", host, "skip-unchanged")
        print("Гейт не запускается: проект не менялся с прошлого зелёного гейта (D51); "
              "принудительно — `gate.py` вручную или AUTOPILOT_KIT_GATE_ALWAYS=1.", file=sys.stderr)
        return 0
    record: dict = {}
    ok, report = run_gate(project, allow_no_tests=True, record=record, hook=True)
    slow = mark_slow(record)
    if slow:
        report = report + "\n" + slow
    if ok:
        if state_path(project).exists():
            _write_state(project, 0)
        if "commands" in record and fingerprint:  # отпечаток после прогона: файлы, которые создали сами тесты, не считаются правкой
            mark_green(project, tree_fingerprint(project))
        log_run(project, "hook", host, _passed(record), record)
        print(report, file=sys.stderr)
        return 0
    active = bool(event.get("stop_hook_active"))
    failures = (_read_state(project) if active else 0) + 1
    if active and failures >= LOOP_LIMIT:
        _write_state(project, 0)
        log_run(project, "hook", host, "loop-release", record)
        message = ("ГЕЙТ НЕ ПРОЙДЕН: повторный провал, остановка разрешена, чтобы не зациклиться.\n"
                   + LOOP_HINT + "\n" + report)
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))
        print(message, file=sys.stderr)
        return 0
    _write_state(project, failures)
    log_run(project, "hook", host, "block", record)
    print(report, file=sys.stderr)
    return 2


def _agy_answer(decision: str, reason: str = "") -> int:
    # ensure_ascii: ответ читает Antigravity, кодовая страница консоли Windows не должна ничего испортить
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=True))
    return 0


def hook_agy_stop(project: Path, event: dict) -> int:
    """Хук Stop Antigravity. В протоколе нет признака «уже продолжали», поэтому провалы считаются по беседе."""
    conversation = str(event.get("conversationId") or "")
    if event.get("fullyIdle") is False:
        return _agy_answer("allow", "Гейт не проверяется: ещё идут фоновые задачи.")
    if event.get("error") or event.get("terminationReason") == "error":
        return _agy_answer("allow", "Гейт не проверяется: ход завершился ошибкой.")
    waiting = autopilot_waiting(project)
    if waiting:
        log_run(project, "hook", "agy", "skip-waiting", {"waiting": waiting})
        print(f"Гейт не проверяется: Autopilot ждёт владельца ({waiting}).", file=sys.stderr)
        return _agy_answer("allow", f"Autopilot ждёт владельца ({waiting}).")
    record: dict = {}
    ok, report = run_gate(project, allow_no_tests=True, record=record, hook=True)
    if ok:
        if state_path(project).exists():
            _write_state(project, 0, conversation)
        log_run(project, "hook", "agy", _passed(record), record)
        print(report, file=sys.stderr)
        return _agy_answer("allow", report)
    failures = _read_state(project, conversation) + 1
    if failures >= LOOP_LIMIT:
        _write_state(project, 0, conversation)
        log_run(project, "hook", "agy", "loop-release", record)
        message = ("ГЕЙТ НЕ ПРОЙДЕН: повторный провал, остановка разрешена, чтобы не зациклиться.\n"
                   + LOOP_HINT + "\n" + report)
        print(message, file=sys.stderr)
        return _agy_answer("allow", message)
    _write_state(project, failures, conversation)
    log_run(project, "hook", "agy", "block", record)
    print(report, file=sys.stderr)
    return _agy_answer("continue", "Гейт качества не пройден. Исправь причину и повтори, не объявляй задачу готовой.\n" + report)


def _event_dir(event: dict) -> Path:
    """Папка, от которой ищется корень проекта: cwd события (Claude, Codex) или первая рабочая папка (Antigravity)."""
    paths = event.get("workspacePaths")
    first = paths[0] if isinstance(paths, list) and paths else None
    return Path(event.get("cwd") or first or os.getcwd())


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # подменённый поток (тесты) — оставляем как есть
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    parser = argparse.ArgumentParser(prog="gate", description="Гейт качества проекта")
    parser.add_argument("--hook", choices=["claude-stop", "codex-stop", "agy-stop"])
    parser.add_argument(
        "--allow-no-tests", action="store_true",
        help="pytest-код 5 (не собрано ни одного теста) не считать провалом — для документных прогонов (T21.1, как в хуке по D14)",
    )
    parser.add_argument(
        "--project", type=Path, default=None,
        help="каталог проекта (по умолчанию ближайший вверх от текущего, где есть .autopilot-kit/project.toml)",
    )
    args = parser.parse_args(argv)
    event = {}
    if args.hook:
        try:
            event = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            event = {}
    project = args.project or find_project_root(_event_dir(event))
    if args.hook:
        host = args.hook.split("-")[0]
        if host == "claude" and (pinned_drive(project) or drive_of()) == GATE_HOST:
            host = GATE_HOST  # D48, T19.8: тот же хук, но привод «Claude Desktop Gate» (фиксация владельца сильнее окружения)
    else:
        # T21.2: ручной прогон пишет привод тем же определением — на общем диске двух машин
        # report --metrics различает статистику по host, а не гадает по времени
        host = pinned_drive(project) or drive_of()
    record: dict = {}
    try:
        if args.hook in ("claude-stop", "codex-stop"):
            return hook_claude_stop(project, event, host)
        if args.hook == "agy-stop":
            return hook_agy_stop(project, event)
        ok, report = run_gate(project, allow_no_tests=args.allow_no_tests, record=record)
    except ValueError as error:  # битый project.toml: не блокируем хук, но и не говорим «пройден»
        log_run(project, "hook" if args.hook else "manual", host, "config-error", {"error": str(error)})
        print(f"Ошибка настройки гейта: {error}", file=sys.stderr)
        if args.hook == "agy-stop":
            return _agy_answer("allow", f"Ошибка настройки гейта: {error}")
        return 1
    log_run(project, "manual", host, _passed(record) if ok else "block", record)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
