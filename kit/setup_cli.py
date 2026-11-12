"""Команда profile set: запись профиля и пересчёт resolved.json и агентов."""
import warnings

from kit import commands, profile


def parse_role(spec: str) -> tuple[str, tuple[str, str]]:
    """'executor=balanced:medium' -> ('executor', ('balanced', 'medium'))."""
    try:
        role, rest = spec.split("=", 1)
        tier, effort = rest.split(":", 1)
    except ValueError:
        raise ValueError(f"ожидается роль=уровень:усилие, получено {spec!r}") from None
    profile._check_setting(role, tier, effort)
    return role, (tier, effort)


def render_table(prof: profile.Profile, models: dict) -> str:
    """Таблица «роль → модель → усилие» для вендоров с заполненными уровнями (claude, codex, claude-gate)."""
    rows = {}
    for vendor in ("claude", "codex", "claude-gate"):
        if models.get(vendor, {}).get("tiers"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rows[vendor] = profile.resolve(prof, vendor, models)
    lines = [f"Пресет: {prof.preset}" + (f" · привод зафиксирован: {prof.drive}" if prof.drive else "")]
    for role in profile.ROLES:
        tier, effort = prof.roles[role]
        cells = [f"{vendor}: {rows[vendor][role][0]} / {rows[vendor][role][1]}" for vendor in rows]
        lines.append(f"  {role:<15} {tier}:{effort:<7} | " + " | ".join(cells))
    return "\n".join(lines)


def cmd_profile_set(preset: str | None, role_specs: list[str], dry_run: bool = False, drive: str | None = None) -> int:
    models = profile.load_models()
    try:
        prof = profile.preset_profile(preset) if preset else profile.load()
        for spec in role_specs:
            role, setting = parse_role(spec)
            prof.roles[role] = setting
        if drive:
            prof.drive = profile._check_drive(drive)
    except ValueError as error:
        print(f"Ошибка: {error}")
        return 2
    print(render_table(prof, models))
    if drive:
        print(f"Привод зафиксирован: {drive} (T19.8 — переопределяет определение по окружению)")
    if dry_run:
        print("(dry-run: ничего не записано)")
        return 0
    profile.write(prof, profile.global_profile_path())
    commands._apply_agents()
    print(f"Профиль записан: {profile.global_profile_path()}")
    return 0
