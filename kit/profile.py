"""Профиль «роль → уровень модели + усилие»: загрузка, слияние, разрешение в имена моделей."""
import json
import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from kit import fsutil, upstream

ROLES = ("executor", "reviewer-spec", "reviewer-craft", "final-reviewer")
TIERS = ("strong", "balanced", "fast")
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max", "ultra")
DRIVES = ("claude", "claude-gate", "codex")  # явная фиксация привода (T19.8, D48)
MODELS_FILE = Path(__file__).parent / "data" / "models.json"

PRESETS: dict[str, dict[str, tuple[str, str]]] = {
    "quality": {
        "executor": ("balanced", "medium"),
        "reviewer-spec": ("strong", "high"),
        "reviewer-craft": ("strong", "high"),
        "final-reviewer": ("strong", "max"),
    },
    "economy": {
        "executor": ("balanced", "medium"),
        "reviewer-spec": ("balanced", "high"),
        "reviewer-craft": ("balanced", "high"),
        "final-reviewer": ("strong", "high"),
    },
    # привод «Claude Desktop Gate» (D48): у гейтвея нет средней модели — sonnet-псевдоним даёт flash-модель
    # (qwen3.8-flash), поэтому исполнитель, как и ревьюеры, работает на сильной (opus → qwen3.8-max)
    "desktop-gate": {
        "executor": ("strong", "medium"),
        "reviewer-spec": ("strong", "high"),
        "reviewer-craft": ("strong", "high"),
        "final-reviewer": ("strong", "max"),
    },
}


@dataclass
class Profile:
    preset: str = "quality"
    roles: dict[str, tuple[str, str]] = field(default_factory=dict)  # роль -> (уровень, усилие)
    drive: str | None = None  # явная фиксация привода (T19.8): переопределяет определение по окружению


def _check_drive(drive: str) -> str:
    if drive not in DRIVES:
        raise ValueError(f"неизвестный привод: {drive!r} (допустимы: {', '.join(DRIVES)})")
    return drive


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"неизвестная роль: {role!r} (допустимы: {', '.join(ROLES)})")


def _check_setting(role: str, tier: str, effort: str) -> tuple[str, str]:
    _check_role(role)
    if tier not in TIERS:
        raise ValueError(f"роль {role}: неизвестный уровень {tier!r} (допустимы: {', '.join(TIERS)})")
    if effort not in EFFORT_ORDER:
        raise ValueError(f"роль {role}: неизвестное усилие {effort!r} (допустимы: {', '.join(EFFORT_ORDER)})")
    return tier, effort


def preset_profile(name: str) -> Profile:
    if name not in PRESETS:
        raise ValueError(f"неизвестный пресет: {name!r} (допустимы: {', '.join(PRESETS)})")
    return Profile(preset=name, roles=dict(PRESETS[name]))


def global_profile_path() -> Path:
    return upstream.kit_home() / ".autopilot-kit" / "profile.toml"


def project_profile_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".autopilot-kit" / "profile.toml"


def _apply_file(base: Profile, path: Path) -> Profile:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    profile = preset_profile(data["preset"]) if "preset" in data else Profile(base.preset, dict(base.roles))
    for role, setting in data.get("roles", {}).items():
        profile.roles[role] = _check_setting(role, setting.get("tier", ""), setting.get("effort", ""))
    drive = data.get("drive", base.drive)
    profile.drive = _check_drive(drive) if drive else None
    return profile


def load(project_dir: Path | None = None) -> Profile:
    """Глобальный профиль поверх пресета quality, поверх него проектный (по ролям)."""
    profile = preset_profile("quality")
    paths = [global_profile_path()]
    if project_dir is not None:
        paths.append(project_profile_path(project_dir))
    for path in paths:
        if path.exists():
            profile = _apply_file(profile, path)
    return profile


def load_models(path: Path = MODELS_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clamp_effort(effort: str, allowed: list[str], role: str, vendor: str) -> str:
    if effort in allowed:
        return effort
    ranked = sorted(allowed, key=EFFORT_ORDER.index)
    lower = [e for e in ranked if EFFORT_ORDER.index(e) < EFFORT_ORDER.index(effort)]
    chosen = lower[-1] if lower else ranked[0]
    warnings.warn(
        f"роль {role}: усилие {effort!r} недоступно для {vendor}, используется {chosen!r}", stacklevel=3
    )
    return chosen


def resolve(profile: Profile, vendor: str, models: dict) -> dict[str, tuple[str, str]]:
    """Роль -> (имя модели, усилие) для вендора; недопустимое усилие понижается с предупреждением."""
    if vendor not in models:
        raise ValueError(f"неизвестный вендор: {vendor!r}")
    table = models[vendor]
    if not table.get("tiers"):
        raise ValueError(f"в таблице моделей для {vendor} нет уровней (unverified)")
    resolved = {}
    for role, (tier, effort) in profile.roles.items():
        _check_setting(role, tier, effort)
        resolved[role] = (table["tiers"][tier], _clamp_effort(effort, table["efforts"], role, vendor))
    return resolved


def serialize(profile: Profile) -> str:
    lines = [f'preset = "{profile.preset}"']
    if profile.drive:
        lines.append(f'drive = "{profile.drive}"')  # явная фиксация привода (T19.8)
    for role in ROLES:
        if role in profile.roles:
            tier, effort = profile.roles[role]
            lines += ["", f"[roles.{role}]", f'tier = "{tier}"', f'effort = "{effort}"']
    return "\n".join(lines) + "\n"


def write(profile: Profile, path: Path) -> None:
    """Пишет profile.toml; существующий другой файл сначала копируется в .bak-<UTC>."""
    fsutil.write_with_backup(Path(path), serialize(profile))
