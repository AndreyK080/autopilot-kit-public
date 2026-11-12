"""Генерация файлов агентов по разрешённому профилю."""
import json
import warnings
from pathlib import Path

from kit import fsutil, profile, upstream

AGENT_MARKER = "Файл создан autopilot-kit"  # по нему uninstall узнаёт свои файлы
REVIEW_TOOLS ="Read, Grep, Glob, Bash"
READ_ONLY_ROLES = ("reviewer-spec", "reviewer-craft", "final-reviewer")


def claude_agents_dir() -> Path:
    return upstream.kit_home() / ".claude" / "agents"


def render_claude_agents(resolved: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Роль -> файл autopilot-<роль>.md с frontmatter (name, description, model, effort[, tools])."""
    files = {}
    for role, (model, effort) in resolved.items():
        lines = [
            "---",
            f"name: autopilot-{role}",
            f"description: Роль {role} в Autopilot. {AGENT_MARKER}, не редактировать.",
            f"model: {model}",
            f"effort: {effort}",
        ]
        if role in READ_ONLY_ROLES:
            lines.append(f"tools: {REVIEW_TOOLS}")
        lines += ["---", f"Ты роль {role} Autopilot. Следуй заданию оркестратора. Не меняй свою роль.", ""]
        files[f"autopilot-{role}.md"] = "\n".join(lines)
    return files


def render_codex(resolved: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Роль -> TOML агента Codex (формат из документации; на живом Codex не проверен, см. docs/SPIKES.md, S4)."""
    if not resolved:
        warnings.warn("для Codex нет разрешённых ролей (таблица моделей не заполнена)", stacklevel=2)
        return {}
    files = {}
    for role, (model, effort) in resolved.items():
        name = "autopilot_" + role.replace("-", "_")
        files[f"{name}.toml"] = "\n".join(
            [
                f'name = "{name}"',
                f'description = "Роль {role} в Autopilot. Файл создан autopilot-kit."',
                f'model = "{model}"',
                f'model_reasoning_effort = "{effort}"',
                f'developer_instructions = "Ты роль {role} Autopilot. Следуй заданию оркестратора. Не меняй свою роль."',
                "",
            ]
        )
    return files


def resolved_json_path() -> Path:
    return upstream.kit_home() / ".autopilot-kit" / "resolved.json"


def write_resolved(prof: profile.Profile, models: dict, path: Path | None = None) -> bool:
    """~/.autopilot-kit/resolved.json: вендор -> роль -> {model, effort}; вендоры без уровней пропускаются."""
    data = {}
    for vendor, table in models.items():
        if isinstance(table, dict) and table.get("tiers"):
            data[vendor] = {
                role: {"model": model, "effort": effort}
                for role, (model, effort) in profile.resolve(prof, vendor, models).items()
            }
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return fsutil.write_with_backup(Path(path) if path else resolved_json_path(), text)


def write_models_copy(models_file: Path = profile.MODELS_FILE, path: Path | None = None) -> bool:
    """~/.autopilot-kit/models.json — копия таблицы моделей для навыков."""
    target = Path(path) if path else upstream.kit_home() / ".autopilot-kit" / "models.json"
    return fsutil.write_with_backup(target, Path(models_file).read_text(encoding="utf-8"))


def write_claude_agents(resolved: dict[str, tuple[str, str]], agents_dir: Path | None = None) -> list[str]:
    """Пишет только autopilot-*.md (с бэкапом); возвращает имена изменённых файлов."""
    target = Path(agents_dir) if agents_dir else claude_agents_dir()
    changed = []
    for filename, text in render_claude_agents(resolved).items():
        if fsutil.write_with_backup(target / filename, text):
            changed.append(filename)
    return changed
