"""kit doctor: проверка окружения, таблица OK / WARN / FAIL."""
import json
import os
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

from kit import profile, render, upstream

OK, WARN, FAIL = "OK", "WARN", "FAIL"
OUR_SKILLS = ("autopilot-roles", "autopilot-setup", "autopilot-init")
API_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
ANTHROPIC_HOST = "anthropic.com"  # BASE_URL на этот домен — не гейтвей, а прямой API (D3: запрещён)
GATE_ENTRYPOINT = "claude-desktop-3p"  # признак привода «Claude Desktop Gate» (D48)


def _run(args: list[str]) -> tuple[int, str]:
    """Код возврата и объединённый вывод; (-1, '') если запуск не удался."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return result.returncode, (result.stdout + result.stderr).strip()


def check_python() -> tuple[str, str]:
    version = ".".join(map(str, sys.version_info[:3]))
    return (OK, f"Python {version}") if sys.version_info >= (3, 11) else (FAIL, f"Python {version}, нужен ≥ 3.11")


def check_git(run=_run) -> tuple[str, str]:
    code, out = run(["git", "--version"])
    return (OK, out) if code == 0 else (FAIL, "git не найден")


def check_autopilot() -> tuple[str, str]:
    lock = upstream.read_lock()
    if not lock:
        return FAIL, "Autopilot не установлен (python -m kit install)"
    problems = []
    for target in upstream.default_targets():
        if not target.exists():
            problems.append(f"нет {target}")
        elif upstream.hash_tree(target) != lock["files"]:
            problems.append(f"изменён {target}")
    if problems:
        return FAIL, "; ".join(problems)
    return OK, f"коммит {lock['commit'][:12]}, хеши совпадают в {len(upstream.default_targets())} местах"


def check_own_skills() -> tuple[str, str]:
    missing = [
        str(base / name / "SKILL.md")
        for base in (t.parent for t in upstream.default_targets())
        for name in OUR_SKILLS
        if not (base / name / "SKILL.md").exists()
    ]
    return (FAIL, "нет: " + ", ".join(missing)) if missing else (OK, ", ".join(OUR_SKILLS))


def check_resolved() -> tuple[str, str]:
    path = render.resolved_json_path()
    return (OK, str(path)) if path.exists() else (FAIL, f"нет {path} (python -m kit install)")


def check_agents() -> tuple[str, str]:
    names = [f"autopilot-{role}.md" for role in profile.ROLES]
    missing = [n for n in names if not (render.claude_agents_dir() / n).exists()]
    return (FAIL, "нет агентов: " + ", ".join(missing)) if missing else (OK, f"{len(names)} агента в {render.claude_agents_dir()}")


def claude_settings_env() -> dict:
    """`env` из ~/.claude/settings.json: провайдер привода «Claude Desktop Gate» задан там, а не в оболочке (D48).

    Значения не печатаются и в отчёт не попадают — doctor смотрит только наличие и хост BASE_URL.
    """
    try:
        data = json.loads((upstream.kit_home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    env = data.get("env") if isinstance(data, dict) else None
    if not isinstance(env, dict):
        return {}
    return {str(k): str(v) for k, v in env.items() if isinstance(v, (str, int, float))}


def _base_url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def check_api_keys(env=None) -> list[tuple[str, str, str]]:
    """API-ключи (D3) и провайдер окружения: гейтвей организации = привод Claude Desktop Gate (D48), а не API."""
    env = os.environ if env is None else env
    rows = []
    for name in API_KEYS:
        if env.get(name):
            rows.append((f"{name} не задан", FAIL, "задан — риск оплаты по API"))
        else:
            rows.append((f"{name} не задан", OK, "не задан"))
    token = bool(env.get("ANTHROPIC_AUTH_TOKEN"))
    host = _base_url_host(str(env.get("ANTHROPIC_BASE_URL") or ""))
    foreign = bool(host) and not (host == ANTHROPIC_HOST or host.endswith("." + ANTHROPIC_HOST))
    if token and foreign:
        note = f"привод Claude Desktop Gate: ANTHROPIC_AUTH_TOKEN + гейтвей {host} (подписка организации, D48) — не API"
        if env.get("CLAUDE_CODE_ENTRYPOINT") == GATE_ENTRYPOINT:
            note += f"; окружение {GATE_ENTRYPOINT}"
        rows.append(("Провайдер Anthropic", OK, note))
    elif token:
        rows.append(("Провайдер Anthropic", FAIL,
                     "ANTHROPIC_AUTH_TOKEN без адреса гейтвея (или с адресом Anthropic) — риск оплаты по API"))
    elif foreign:
        rows.append(("Провайдер Anthropic", WARN,
                     f"чужой ANTHROPIC_BASE_URL ({host}) без ANTHROPIC_AUTH_TOKEN — проверьте настройки привода"))
    else:
        rows.append(("Провайдер Anthropic", OK, "гейтвей не задан — приложение по подписке"))
    return rows


def misplaced_drive(data) -> list[str]:
    """Где в TOML-данных лежит `drive` внутри таблиц: ключ верхнеуровневый, записанный после `[gate]`/`[roles.…]`
    он попадает в таблицу и молча игнорируется (T19.9)."""
    found = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "drive" and path:
                found.append(".".join([*path, key]))
            elif isinstance(value, dict):
                walk(value, [*path, key])

    walk(data, [])
    return found


def check_drive_pin() -> tuple[str, str]:
    """Фиксация привода в profile.toml (D49): на месте и на верхнем уровне."""
    path = upstream.kit_home() / ".autopilot-kit" / "profile.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return OK, "profile.toml нет или не читается — фиксация не задана"
    misplaced = misplaced_drive(data)
    if misplaced:
        return WARN, f"`drive` внутри таблицы ({', '.join(misplaced)}) игнорируется — перенесите ключ на верхний уровень profile.toml"
    if data.get("drive"):
        return OK, f"drive = {data['drive']} (фиксация владельца)"
    return OK, "drive не зафиксирован — определяется по окружению и подтверждению (D49)"


def check_codex_login(run=_run, which=shutil.which) -> tuple[str, str] | None:
    exe = which("codex")
    if not exe:
        return None
    code, out = run([exe, "login", "status"])
    if "chatgpt" in out.lower():
        return OK, "вход по ChatGPT"
    if code == -1:
        return WARN, "не удалось выполнить codex login status"
    return FAIL, f"вход Codex не через ChatGPT: {out[:80]}"


def check_claude_login(run=_run, which=shutil.which) -> tuple[str, str]:
    exe = which("claude")
    if not exe:
        return WARN, "claude CLI не найден (для kit не обязателен)"
    _code, out = run([exe, "auth", "status"])
    try:
        logged_in = bool(json.loads(out).get("loggedIn"))
    except ValueError:
        return WARN, "не удалось определить вход claude CLI (не обязателен)"
    return (OK, "claude CLI авторизован") if logged_in else (WARN, "claude CLI не авторизован (не обязателен)")


def collect() -> list[tuple[str, str, str]]:
    from kit import projects  # projects импортирует gate и program — только когда doctor запущен
    rows = [
        ("Python ≥ 3.11", *check_python()),
        ("`python` из PATH (его зовут хуки)", *projects.python_works()),
        ("git", *check_git()),
        ("Autopilot установлен, хеши", *check_autopilot()),
        ("Навыки kit установлены", *check_own_skills()),
        ("resolved.json", *check_resolved()),
        ("Агенты autopilot-*", *check_agents()),
        # провайдер виден и из оболочки, и из настроек приложения; settings.json авторитетнее для показа: там
        # настоящий адрес гейтвея, а в окружении сессии может быть локальный прокси приложения (T19.8)
        *check_api_keys({**os.environ, **claude_settings_env()}),
        ("Фиксация привода (profile)", *check_drive_pin()),
    ]
    codex = check_codex_login()
    if codex:
        rows.append(("Вход Codex", *codex))
    rows.append(("Вход claude CLI", *check_claude_login()))
    return rows


def cmd_doctor(with_projects: bool = False, extra=None) -> int:
    rows = collect()
    if with_projects or extra:
        from kit import projects
        rows += projects.collect_projects(extra)
    width = max(len(name) for name, _, _ in rows)
    for name, status, message in rows:
        print(f"{status:<5} {name:<{width}}  {message}")
    failed = sum(1 for _, status, _ in rows if status == FAIL)
    print(f"\nИтого: FAIL {failed}, WARN {sum(1 for _, s, _ in rows if s == WARN)}")
    return 1 if failed else 0
