"""Оригинальный Autopilot: получение с GitHub, хеши, установка, lock."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_URL = "https://github.com/nick-vels/skills.git"
SKILL_SUBPATH = Path("skills") / "autopilot"
LOCAL_CHANGES = "LOCAL_CHANGES"


def kit_home() -> Path:
    """Домашний каталог пользователя; в тестах переопределяется AUTOPILOT_KIT_HOME."""
    override = os.environ.get("AUTOPILOT_KIT_HOME")
    return Path(override) if override else Path.home()


def lock_path() -> Path:
    return kit_home() / ".autopilot-kit" / "upstream.lock.json"


def default_targets() -> list[Path]:
    home = kit_home()
    return [home / ".claude" / "skills" / "autopilot", home / ".agents" / "skills" / "autopilot"]


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def fetch(commit: str | None = None, url: str = REPO_URL, dest: Path | None = None) -> Path:
    """Клонирует репозиторий без blob'ов, выкладывает commit (или HEAD), возвращает путь к skills/autopilot."""
    root = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="autopilot-kit-"))
    # autocrlf=false: хеши файлов не должны зависеть от настроек git на машине
    _git("clone", "-c", "core.autocrlf=false", "--filter=blob:none", "--no-checkout", url, str(root))
    _git("checkout", commit or "HEAD", cwd=root)
    return root / SKILL_SUBPATH


def resolved_commit(src: Path) -> str:
    """Полный хеш коммита, выложенного в клоне, из которого получен src."""
    return _git("rev-parse", "HEAD", cwd=Path(src).parents[1])


def hash_tree(path: Path) -> dict[str, str]:
    """Относительный путь (через /) -> SHA-256, по возрастанию пути, без __pycache__."""
    path = Path(path)
    hashes: dict[str, str] = {}
    for file in sorted(path.rglob("*")):
        rel = file.relative_to(path)
        if not file.is_file() or "__pycache__" in rel.parts:
            continue
        hashes[rel.as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return dict(sorted(hashes.items()))


def write_lock(commit: str, files: dict[str, str], source: str = REPO_URL, path: Path | None = None) -> None:
    target = Path(path) if path else lock_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "commit": commit,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
    }
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_lock(path: Path | None = None) -> dict | None:
    target = Path(path) if path else lock_path()
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _diff(current: dict[str, str], expected: dict[str, str]) -> list[str]:
    return sorted(k for k in current.keys() | expected.keys() if current.get(k) != expected.get(k))


def _copy_tree(src: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def install(src: Path, targets: list[Path], lock: dict | None = None) -> dict[Path, dict]:
    """Копирует src в каждую цель.

    Существующая цель, чьи файлы отличаются от lock (или, без lock, от src), не перезаписывается:
    для неё статус LOCAL_CHANGES со списком файлов, и тогда не меняется ни одна цель.
    Статусы: installed, unchanged, LOCAL_CHANGES.
    """
    new_hashes = hash_tree(src)
    locked = lock["files"] if lock else None
    report: dict[Path, dict] = {}
    for target in map(Path, targets):
        if not target.exists():
            report[target] = {"status": "installed", "files": []}
            continue
        current = hash_tree(target)
        if current == new_hashes:
            report[target] = {"status": "unchanged", "files": []}
        elif locked is not None and current == locked:
            report[target] = {"status": "installed", "files": []}
        else:
            baseline = locked if locked is not None else new_hashes
            report[target] = {"status": LOCAL_CHANGES, "files": _diff(current, baseline)}
    if any(item["status"] == LOCAL_CHANGES for item in report.values()):
        return report
    for target, item in report.items():
        if item["status"] == "installed":
            _copy_tree(src, target)
    return report


# ── копия для сессий этапов /autopilot-program (D19) ────────────────────────

STAGE_NAME = "autopilot-stage"
STAGE_MARKER = ".autopilot-kit-generated"
STAGE_DESCRIPTION = (
    "Copy of /autopilot made by autopilot-kit for stage sessions of /autopilot-program. Use ONLY when a stage "
    "brief from the /autopilot-program orchestrator tells you to invoke autopilot-stage; never on your own and "
    "never for an ordinary request — the user starts runs with /autopilot."
)


def stage_target() -> Path:
    return kit_home() / ".claude" / "skills" / STAGE_NAME


def stage_skill_text(text: str) -> str:
    """SKILL.md оригинала → копия: другое имя и описание, без disable-model-invocation; тело без изменений."""
    if not text.startswith("---"):
        raise ValueError("SKILL.md Autopilot без frontmatter — копию для этапов не делаю")
    head, sep, body = text[3:].partition("\n---")
    if not sep:
        raise ValueError("SKILL.md Autopilot: frontmatter не закрыт")
    lines = head.split("\n")
    if not any(line.startswith("name:") for line in lines) or not any(line.startswith("description:") for line in lines):
        raise ValueError("SKILL.md Autopilot: нет name или description во frontmatter")
    out = []
    for line in lines:
        if line.startswith("disable-model-invocation:"):
            continue
        if line.startswith("name:"):
            line = f"name: {STAGE_NAME}"
        elif line.startswith("description:"):
            line = "description: " + json.dumps(STAGE_DESCRIPTION, ensure_ascii=False)
        out.append(line)
    return "---" + "\n".join(out) + sep + body


def install_stage_copy(src: Path, target: Path | None = None) -> str:
    """Пересобирает копию для этапов из src. Папку без маркера kit не трогает."""
    target = Path(target) if target else stage_target()
    if target.exists() and not (target / STAGE_MARKER).exists():
        return f"оставлено (папка не от kit): {target}"
    try:
        text = stage_skill_text((Path(src) / "SKILL.md").read_text(encoding="utf-8"))
    except ValueError as error:  # формат оригинала поменялся: Autopilot ставится, копия — нет
        return f"копия для этапов не сделана: {error}"
    _copy_tree(src, target)
    (target / "SKILL.md").write_text(text, encoding="utf-8", newline="")
    (target / STAGE_MARKER).write_text("копия Autopilot для /autopilot-program; пересоздаётся kit install\n",
                                       encoding="utf-8")
    return f"копия для этапов: {target}"


def remove_stage_copy(target: Path | None = None) -> str | None:
    target = Path(target) if target else stage_target()
    if not target.exists():
        return None
    if not (target / STAGE_MARKER).exists():
        return f"оставлено (папка не от kit): {target}"
    shutil.rmtree(target)
    return f"копия для этапов удалена: {target}"
