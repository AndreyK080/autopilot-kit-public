"""kit project init: копирование шаблона проекта без потери существующих файлов."""
import copy
import json
from pathlib import Path

from kit import fsutil, upstream

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
HOME_PLACEHOLDER = "<~>"
AGY_HOOKS = ".agents/hooks.json"  # у Antigravity хуки лежат под именем хука верхнего уровня
MERGED = (".claude/settings.json", ".codex/hooks.json", AGY_HOOKS)  # JSON с хуками: сливаются, а не кладутся рядом
GITIGNORE = ".gitignore"  # у проекта обычно свой: недостающие строки шаблона дописываются в конец


def available_templates() -> list[str]:
    return sorted(p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir()) if TEMPLATES_DIR.is_dir() else []


def _union(first: list, second: list) -> list:
    return first + [item for item in second if item not in first]


def merge_settings(existing: dict, new: dict) -> dict:
    """permissions.allow/deny объединяются, хуки добавляются без дублей (по command), остальное не трогаем."""
    result = copy.deepcopy(existing)
    for key, value in new.items():
        if key == "permissions" and isinstance(value, dict):
            permissions = result.setdefault("permissions", {})
            for list_key, items in value.items():
                permissions[list_key] = _union(permissions.get(list_key, []), items)
        elif key == "hooks" and isinstance(value, dict):
            hooks = result.setdefault("hooks", {})
            for event, groups in value.items():
                current = hooks.setdefault(event, [])
                known = {h.get("command") for g in current for h in g.get("hooks", [])}
                for group in groups:
                    fresh = [h for h in group.get("hooks", []) if h.get("command") not in known]
                    if fresh:
                        current.append({**group, "hooks": fresh})
                        known.update(h.get("command") for h in fresh)
        else:
            result.setdefault(key, value)
    return result


def merge_agy_hooks(existing: dict, new: dict) -> dict:
    """Хуки Antigravity добавляются по имени; хук с тем же именем у владельца не трогаем."""
    result = copy.deepcopy(existing)
    for name, definition in new.items():
        result.setdefault(name, definition)
    return result


def _write_new_beside(target: Path, text: str) -> Path:
    beside = target.with_name(target.name + ".kit-new")
    fsutil.write_with_backup(beside, text)
    return beside


def init_project(template: str, path: Path) -> list[str]:
    """Возвращает построчный отчёт. Существующие файлы не перезаписываются (кроме слияния settings.json и hooks.json)."""
    source = TEMPLATES_DIR / template
    if not source.is_dir():
        raise ValueError(f"неизвестный шаблон {template!r} (доступны: {', '.join(available_templates())})")
    home = upstream.kit_home().as_posix()
    report = []
    for file in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = file.relative_to(source).as_posix()
        text = file.read_text(encoding="utf-8").replace(HOME_PLACEHOLDER, home)
        target = Path(path) / rel
        if not target.exists():
            fsutil.write_with_backup(target, text)
            report.append(f"создан: {rel}")
        elif target.read_text(encoding="utf-8") == text:
            report.append(f"без изменений: {rel}")
        elif rel in MERGED:
            report.append(_merge_settings_file(target, text, rel))
        elif rel == GITIGNORE:
            report.append(_merge_gitignore(target, text))
        else:
            beside = _write_new_beside(target, text)
            report.append(f"существует: {rel} — шаблон записан рядом: {beside.name}")
    return report


def _merge_gitignore(target: Path, text: str) -> str:
    current = target.read_text(encoding="utf-8")
    have = {line.strip() for line in current.splitlines()}
    missing = [line for line in text.splitlines() if line.strip() and not line.startswith("#") and line.strip() not in have]
    if not missing:
        return f"без изменений: {GITIGNORE}"
    comment = next((line for line in text.splitlines() if line.startswith("#")), None)
    tail = ("" if current.endswith("\n") or not current else "\n") + "\n" + "\n".join(filter(None, [comment, *missing])) + "\n"
    fsutil.write_with_backup(target, current + tail)
    return f"дописан: {GITIGNORE} ({', '.join(missing)})"


def _merge_settings_file(target: Path, text: str, rel: str) -> str:
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError("не объект")
    except ValueError:
        beside = _write_new_beside(target, text)
        return f"существует: {rel} — не удалось прочитать JSON, шаблон записан рядом: {beside.name}"
    merge = merge_agy_hooks if rel == AGY_HOOKS else merge_settings
    merged = merge(existing, json.loads(text))
    if merged == existing:
        return f"без изменений: {rel}"
    fsutil.write_with_backup(target, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return f"слит: {rel} (копия прежнего — {rel}.bak-*)"
