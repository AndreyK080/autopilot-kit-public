"""kit uninstall: удаляет только то, что поставил kit; прежние файлы пользователя возвращает из .bak."""
import shutil
from pathlib import Path

from kit import commands, profile, render, upstream

KIT_FILES = ("upstream.lock.json", "resolved.json", "models.json", "kit_path")


def _prune_empty(path: Path) -> None:
    for folder in sorted((p for p in path.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    if path.exists() and not any(path.iterdir()):
        path.rmdir()


def _remove_autopilot(report: list[str]) -> None:
    lock = upstream.read_lock()
    if not lock:
        report.append("Autopilot: нет upstream.lock.json — не трогаю")
        return
    for target in upstream.default_targets():
        if not target.exists():
            continue
        current = upstream.hash_tree(target)
        kept = []
        for rel, digest in current.items():
            if lock["files"].get(rel) == digest:
                (target / rel).unlink()
            else:
                kept.append(rel)
        _prune_empty(target)
        report.append(f"Autopilot удалён: {target}" + (f" (оставлены изменённые: {', '.join(kept)})" if kept else ""))


def _remove_own_skills(report: list[str]) -> None:
    if not commands.OWN_SKILLS_DIR.is_dir():
        return
    for skill in sorted(p for p in commands.OWN_SKILLS_DIR.iterdir() if p.is_dir()):
        for base in (t.parent for t in upstream.default_targets()):
            target = base / skill.name
            if not target.exists():
                continue
            if upstream.hash_tree(target) == upstream.hash_tree(skill):
                shutil.rmtree(target)
                report.append(f"навык удалён: {target}")
            else:
                report.append(f"навык изменён, оставлен: {target}")


def _is_kit_file(path: Path) -> bool:
    return render.AGENT_MARKER in path.read_text(encoding="utf-8", errors="replace")


def _remove_agents(report: list[str]) -> None:
    agents = render.claude_agents_dir()
    for role in profile.ROLES:
        path = agents / f"autopilot-{role}.md"
        backups = sorted(agents.glob(f"{path.name}.bak-*"))
        if path.exists() and _is_kit_file(path):
            path.unlink()
            report.append(f"агент удалён: {path}")
        elif path.exists():
            report.append(f"агент изменён, оставлен: {path}")
            continue
        for backup in [b for b in backups if _is_kit_file(b)]:
            backup.unlink()  # копии прежних версий самого kit
        own = [b for b in backups if b.exists()]
        if own and not path.exists():
            shutil.move(str(own[0]), str(path))  # самая старая копия — то, что было до kit
            report.append(f"восстановлено из копии: {path}")


def _remove_kit_home(report: list[str]) -> None:
    root = upstream.kit_home() / ".autopilot-kit"
    for name in KIT_FILES:
        if (root / name).exists():
            (root / name).unlink()
            report.append(f"удалён: {root / name}")
    for folder in ("bin", "backups", "trial"):
        if (root / folder).exists():
            shutil.rmtree(root / folder)
            report.append(f"удалена папка: {root / folder}")
    if root.exists() and not any(root.iterdir()):
        root.rmdir()
    elif root.exists():
        report.append(f"оставлено (ваши настройки): {', '.join(p.name for p in root.iterdir())} в {root}")


def uninstall() -> list[str]:
    report: list[str] = []
    _remove_autopilot(report)
    stage = upstream.remove_stage_copy()
    if stage:
        report.append(stage)
    _remove_own_skills(report)
    _remove_agents(report)
    _remove_kit_home(report)
    return report


def cmd_uninstall(assume_yes: bool = False) -> int:
    if not assume_yes:
        answer = input("Удалить Autopilot, навыки kit, агентов autopilot-* и служебные файлы kit? [y/N] ")
        if answer.strip().lower() != "y":
            print("Отменено.")
            return 1
    print("\n".join(uninstall()) or "Нечего удалять.")
    return 0
