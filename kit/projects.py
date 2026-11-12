"""Проекты на машине (T17.6, D41): `kit doctor --projects` и `kit relocate` после переезда.

Проекты — программы из реестра ~/.autopilot-kit/programs.json и папки, переданные --project.
Переезд 25.10.2026 ломал проекты молча: хуки со старым домашним каталогом, заглушка `python` из WindowsApps,
служебные файлы гейта в коммитах, сессии оркестратора и резерва с другой машины в program.json.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from kit import doctor, fsutil, gate, program, project, upstream

OK, WARN, FAIL = "OK", "WARN", "FAIL"
HOOK_FILES = (".claude/settings.json", ".codex/hooks.json", project.AGY_HOOKS)
GATE_IN_COMMAND = re.compile(r"""[^"'\s]*[/\\]\.autopilot-kit[/\\]bin[/\\]gate\.py""")
# машинно-независимый путь хука (D48): оболочка хуков Claude на Windows — Git Bash (запасная PowerShell),
# обе раскрывают $HOME, а %USERPROFILE% — ни одна; проекты на общем диске двух машин не требуют relocate
PORTABLE_GATE = "$HOME/.autopilot-kit/bin/gate.py"
SERVICE_FILES = ("last_host", "gate_state.json", "gate_log.jsonl", "flaky.json")  # то, что kit пишет в .autopilot-kit
BACKUPS = "*.bak-20*"  # резервные копии kit (<файл>.bak-<UTC>) рядом с правленными файлами проекта
PYTHON_HINT = ("`python` — заглушка Microsoft Store: Параметры → Приложения → Дополнительные параметры приложений → "
               "Псевдонимы выполнения приложений → выключить python.exe и python3.exe")


def is_portable_gate(match: str) -> bool:
    return match.replace("\\", "/") == PORTABLE_GATE


def gate_path() -> str:
    return (upstream.kit_home() / ".autopilot-kit" / "bin" / "gate.py").as_posix()


def project_list(extra: list[Path] | None = None) -> list[Path]:
    """Программы из реестра и переданные папки — без повторов одной папки под разными именами (P: и UNC)."""
    roots = [Path(p["root"]) for p in _registry().get("programs") or [] if isinstance(p, dict) and p.get("root")]
    result: list[Path] = []
    for root in [*roots, *(extra or [])]:
        root = Path(os.path.abspath(root))
        if not any(_same(root, known) for known in result):
            result.append(root)
    return result


def _same(first: Path, second: Path) -> bool:
    if os.path.normcase(str(first)) == os.path.normcase(str(second)):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _registry() -> dict:
    try:
        data = json.loads(program.registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _hook_commands(data: dict) -> list[str]:
    """Все строки command в разделе hooks (формат Claude/Codex и Antigravity)."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "command" and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data.get("hooks") if "hooks" in data else data)
    return found


def gate_hooks(root: Path) -> list[tuple[str, str]]:
    """(файл, команда) для каждого хука, который вызывает gate.py."""
    hooks = []
    for rel in HOOK_FILES:
        data = _read_json(root / rel)
        hooks += [(rel, command) for command in _hook_commands(data or {}) if GATE_IN_COMMAND.search(command)]
    return hooks


def _first_word(command: str) -> str:
    try:
        words = shlex.split(command, posix=False)
    except ValueError:
        words = command.split()
    return words[0].strip("\"'") if words else ""


def python_works(exe: str = "python", which=shutil.which, run=None) -> tuple[str, str]:
    """Настоящий ли интерпретатор зовут хуки: заглушка WindowsApps без аргументов открывает Магазин, с аргументами — падает."""
    path = which(exe)
    if not path:
        return FAIL, f"`{exe}` не найден в PATH — хуки гейта не запустятся"
    run = run or (lambda args: subprocess.run(args, capture_output=True, text=True, timeout=30))
    try:
        result = run([path, "-c", "print('kit-ok')"])
        works = result.returncode == 0 and "kit-ok" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        works = False
    if works:
        return OK, path
    if "windowsapps" in path.lower():
        return FAIL, PYTHON_HINT
    return FAIL, f"{path} не запускается"


def _gitignored(root: Path) -> list[str]:
    """Служебные файлы kit, которых нет в .gitignore проекта ([] — всё на месте или проект не в git)."""
    if not (root / ".git").exists():
        return []
    try:
        lines = {line.strip().lstrip("/").rstrip("/") for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines()}
    except OSError:
        lines = set()
    folder = bool(lines & {".autopilot-kit", ".autopilot-kit/*", ".autopilot-kit/**"})
    needed = [] if folder else [f".autopilot-kit/{name}" for name in SERVICE_FILES]
    # T21.11: конфигурация панели машинно-зависима (абсолютный путь program.py) — в git не попадает;
    # ignore всей папки .claude тоже годится
    claude_folder = bool(lines & {".claude", ".claude/*", ".claude/**"})
    if not claude_folder:
        needed.append(".claude/launch.json")
    return [entry for entry in [*needed, BACKUPS] if entry not in lines]


def launch_tracked(root: Path) -> bool:
    """.claude/launch.json уже отслеживается git (старые проекты, force-add): kit его не переписывает — WARN, решение владельца."""
    if not (root / ".git").exists():
        return False
    try:
        out = subprocess.run(["git", "ls-files", "--", ".claude/launch.json"], cwd=root,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and out.stdout.strip() != ""


def _tool_found(root: Path, command: str, which) -> bool:
    word = _first_word(command)
    if not word:
        return True
    if "/" in word or "\\" in word:
        path = Path(word) if os.path.isabs(word) else root / word
        return path.exists() or Path(str(path) + ".exe").exists()
    return bool(which(word))


def misplaced_project_drive(root: Path) -> list[str]:
    """`drive` внутри таблиц project.toml — записанный после `[gate]` ключ молча игнорируется (T19.9)."""
    try:
        data = tomllib.loads((root / ".autopilot-kit" / "project.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return doctor.misplaced_drive(data)


def _gate_hook_timeouts(root: Path) -> list[int]:
    """Предел времени (с) у каждого хука, который вызывает gate.py: ключ `timeout` рядом с `command`."""
    found: list[int] = []

    def walk(node):
        if isinstance(node, dict):
            command = node.get("command")
            if isinstance(command, str) and GATE_IN_COMMAND.search(command) and isinstance(node.get("timeout"), (int, float)):
                found.append(int(node["timeout"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for rel in HOOK_FILES:
        walk((_read_json(root / rel) or {}).get("hooks") or {})
    return found


def slow_gate_runs(root: Path, now: datetime | None = None) -> tuple[int, int]:
    """(запусков хука гейта за сутки не короче предела, самый долгий в секундах) по `gate_log.jsonl` (D51)."""
    now = now or datetime.now(timezone.utc)
    count, longest = 0, 0
    try:
        lines = gate.log_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, 0
    for line in lines[-2000:]:
        try:
            row = json.loads(line)
            at = datetime.fromisoformat(row["at"])
        except (ValueError, KeyError, TypeError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if row.get("mode") != "hook" or (now - at).total_seconds() > 86400:
            continue
        seconds = sum(c.get("seconds") or 0 for c in row.get("commands") or [] if isinstance(c, dict))
        if seconds >= gate.HOOK_SLOW_SECONDS:
            count, longest = count + 1, max(longest, int(seconds))
    return count, longest


def gate_time_rows(root: Path, config: dict | None, now: datetime | None = None) -> list[tuple[str, str, str]]:
    """Время гейта в хуке (D51): приложение обрывает ход без вывода ~1000 с («Try again»), а хук — по своему `timeout`."""
    name, rows = root.name, []
    limits = _gate_hook_timeouts(root)
    effective = (config.get("hook_timeout") if config.get("hook_commands") else config["timeout"]) if config else None
    if effective and limits and effective > min(limits):
        key = "hook_timeout_seconds" if config.get("hook_commands") else "timeout_seconds"
        rows.append((f"{name}: время гейта", WARN,
                     f"`{key}` гейта {effective} с больше предела хука {min(limits)} с: хук оборвёт долгий набор "
                     "раньше, чем сработает защита гейта — ускорьте набор проверок или поднимите предел хука"))
    count, longest = slow_gate_runs(root, now)
    if count:
        rows.append((f"{name}: время гейта", WARN,
                     f"{count} запусков хука за сутки дольше {gate.HOOK_SLOW_SECONDS} с (макс. {longest} с): приложение обрывает ход "
                     "без вывода ~1000 с — владельцу «Try again». Ускорьте набор (параллельный запуск, быстрый набор для хука)"))
    return rows


def check_project(root: Path, which=shutil.which, run=None) -> list[tuple[str, str, str]]:
    name = root.name
    if not root.is_dir():
        return [(f"{name}: папка", FAIL, f"нет {root}")]
    rows = []
    hooks = gate_hooks(root)
    expected = gate_path()
    matches = {match for _, command in hooks for match in GATE_IN_COMMAND.findall(command)}
    portable = {match for match in matches if is_portable_gate(match)}
    stale = sorted(match for match in matches - portable
                   if os.path.normcase(match.replace("\\", "/")) != os.path.normcase(expected))
    if not hooks:
        rows.append((f"{name}: хук гейта", WARN, "хука Stop с gate.py нет (проект без /autopilot-init?)"))
    elif stale:
        rows.append((f"{name}: хук гейта", FAIL,
                     f"указывает на {', '.join(stale)} — `python -m kit relocate`; для проекта, общего нескольким "
                     f"машинам, замените путь на `{PORTABLE_GATE}` (D48) — relocate сломает другие машины"))
    elif not Path(expected).is_file():
        rows.append((f"{name}: хук гейта", FAIL, f"нет {expected} — `python -m kit install`"))
    else:
        target = f"{PORTABLE_GATE} (машинно-независимый путь)" if portable else expected
        rows.append((f"{name}: хук гейта", OK, f"{len(hooks)} хук(а) → {target}"))
    for exe in sorted({_first_word(command) for _, command in hooks} - {""}):
        if "/" not in exe and "\\" not in exe:
            rows.append((f"{name}: `{exe}` хуков", *python_works(exe, which, run)))
    try:
        config = gate.load_config(root)  # тот же разбор project.toml, что у гейта
    except (ValueError, OSError) as error:
        rows.append((f"{name}: команды гейта", FAIL, f"project.toml не разбирается: {error}"))
        config = None
    if config is not None:
        missing = [c for c in [*config["commands"], *(config.get("hook_commands") or [])] if not _tool_found(root, c, which)]
        rows.append((f"{name}: команды гейта", FAIL if missing else OK,
                     ("не найдена программа: " + "; ".join(missing)) if missing else f"{len(config['commands'])} команд(ы)"))
    rows += gate_time_rows(root, config)
    absent = _gitignored(root)
    rows.append((f"{name}: .gitignore", FAIL if absent else OK,
                 f"нет {', '.join(absent)} — `python -m kit relocate`" if absent else "служебные файлы kit не попадут в git"))
    if launch_tracked(root):  # T21.11: не FAIL и не правка — файл мог быть добавлен осознанно, решает владелец
        rows.append((f"{name}: .claude/launch.json", WARN,
                     "служебный файл отслеживается git, хотя машинно-зависим (абсолютный путь program.py) — "
                     "решение владельца; kit его не переписывает"))
    misplaced = misplaced_project_drive(root)
    if misplaced:
        rows.append((f"{name}: фиксация привода", WARN,
                     f"`drive` внутри таблицы ({', '.join(misplaced)}) игнорируется — ключ должен быть верхнеуровневым "
                     f"в `.autopilot-kit/project.toml` (D49)"))
    return rows


def collect_projects(extra: list[Path] | None = None, which=shutil.which, run=None) -> list[tuple[str, str, str]]:
    roots = project_list(extra)
    if not roots:
        return [("Проекты", WARN, "в реестре программ нет проектов — передайте --project")]
    return [row for root in roots for row in check_project(root, which, run)]


# ── kit relocate ────────────────────────────────────────────────────────────

def _fix_hooks(root: Path, dry_run: bool) -> list[str]:
    expected = gate_path()
    report = []
    for rel in HOOK_FILES:
        path = root / rel
        data = _read_json(path)
        if data is None:
            continue
        changed = []

        def fix(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if (key == "command" and isinstance(value, str) and GATE_IN_COMMAND.search(value)
                            and not any(is_portable_gate(m) for m in GATE_IN_COMMAND.findall(value))):
                        # $HOME-форму не переписываем: она машинно-независима (D48) и общая для всех машин проекта
                        new = GATE_IN_COMMAND.sub(lambda _m: expected, value)
                        if new != value:
                            node[key] = new
                            changed.append(value)
                    else:
                        fix(value)
            elif isinstance(node, list):
                for item in node:
                    fix(item)

        fix(data)
        if changed:
            if not dry_run:
                fsutil.write_with_backup(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            report.append(f"{rel}: путь гейта → {expected} ({len(changed)} хук(а))")
    return report


def _fix_gitignore(root: Path, dry_run: bool) -> list[str]:
    absent = _gitignored(root)
    if not absent:
        return []
    if not dry_run:
        path = root / ".gitignore"
        template = "# служебные файлы autopilot-kit и его резервные копии (.bak-<UTC>)\n" + "\n".join(absent) + "\n"
        if path.exists():
            project._merge_gitignore(path, template)
        else:
            fsutil.write_with_backup(path, template)
    return [f".gitignore: дописаны {', '.join(absent)}"]


def _move_sessions(root: Path, moved_home: bool, dry_run: bool) -> list[str]:
    """Сессии оркестратора и резерва с другой машины → previous: приложение их здесь не знает (D41)."""
    path = program.program_path(root)
    data = _read_json(path)
    if data is None or not (data.get("orchestrator") or data.get("pool")):
        return []
    recorded = data.get("orchestratorMachine")
    if not ((recorded and not program.machines_compatible(recorded, program.machine_id(root))) or (not recorded and moved_home)):
        return []  # записи до D48 (без привода) совместимы с любым приводом той же машины — не сдвигать их
    if not dry_run:
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        data.setdefault("previous", []).append({"at": stamp, "machine": recorded, "orchestrator": data.get("orchestrator"),
                                                "pool": data.get("pool") or []})
        data.update(orchestrator=None, orchestratorMachine=None, pool=[])
        fsutil.write_with_backup(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return ["program.json: оркестратор и резерв с другой машины → previous; откройте новый чат и напишите /autopilot-program"]


def _fix_registry(dry_run: bool) -> list[str]:
    """Реестр программ: пути через abspath (не UNC), без повторов одной папки."""
    reg = _registry()
    entries = [p for p in reg.get("programs") or [] if isinstance(p, dict) and p.get("root")]
    kept: list[dict] = []
    for entry in entries:
        root = os.path.abspath(entry["root"])
        twin = next((k for k in kept if _same(Path(k["root"]), Path(root))), None)
        if twin is None:
            kept.append({**entry, "root": root})
        elif twin["root"].startswith("\\\\") and not root.startswith("\\\\"):
            twin["root"] = root  # одна папка под буквой диска и под UNC — оставляем букву
    if kept == entries:
        return []
    if not dry_run:
        fsutil.write_with_backup(program.registry_path(), json.dumps({**reg, "programs": kept}, ensure_ascii=False, indent=2) + "\n")
    return [f"реестр программ: {len(entries)} → {len(kept)} записей, пути без UNC"]


def relocate(extra: list[Path] | None = None, dry_run: bool = False) -> list[str]:
    """Чинит то, что ломает переезд: kit_path, хуки, .gitignore, сессии с другой машины, реестр. Правки — с .bak-<UTC>."""
    from kit import commands  # commands импортирует этот модуль не раньше, чем он загружен
    lines = []
    kit_root = os.path.abspath(commands.KIT_ROOT)
    path = commands.kit_path_file()
    current = path.read_text(encoding="utf-8").strip() if path.exists() else None
    if current != Path(kit_root).as_posix():
        if not dry_run:
            fsutil.write_with_backup(path, Path(kit_root).as_posix() + "\n")
        lines.append(f"kit_path: {current or '—'} → {Path(kit_root).as_posix()}")
    lines += _fix_registry(dry_run)
    for root in project_list(extra):
        if not root.is_dir():
            lines.append(f"{root}: папки нет — пропущено")
            continue
        hooks = _fix_hooks(root, dry_run)
        changes = hooks + _fix_gitignore(root, dry_run) + _move_sessions(root, bool(hooks), dry_run)
        lines += [f"{root}: {change}" for change in changes] or [f"{root}: без изменений"]
    if dry_run:
        lines.append("(--dry-run: ничего не изменено)")
    return lines
