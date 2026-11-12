"""Команды install / status / update."""
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kit import fsutil, profile, render, seams, upstream

PIN_FILE = Path(__file__).parent / "data" / "upstream.pin"
KIT_ROOT = Path(os.path.abspath(__file__)).parent.parent  # не resolve: сетевой диск P: превратился бы в UNC, а cmd.exe в нём не работает
OWN_SKILLS_DIR = KIT_ROOT / "skills"


def kit_path_file() -> Path:
    """Файл с путём к репозиторию kit: по нему навык /autopilot-init находит `python -m kit` из любого чата."""
    return upstream.kit_home() / ".autopilot-kit" / "kit_path"


def read_pin(pin_file: Path = PIN_FILE) -> str:
    return pin_file.read_text(encoding="utf-8").strip()


def _remove_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: Path) -> None:
    """rmtree, который удаляет и read-only файлы .git на Windows."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, ignore_errors=False, onexc=_remove_readonly)
    else:
        shutil.rmtree(path, ignore_errors=False, onerror=_remove_readonly)


def _cleanup(src: Path) -> None:
    _rmtree(Path(src).parents[1])


def remote_head(url: str) -> str | None:
    """Коммит HEAD на удалённой стороне или None, если сеть/репозиторий недоступны."""
    result = subprocess.run(
        ["git", "ls-remote", url, "HEAD"], capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def _print_local_changes(report: dict) -> None:
    for target, item in report.items():
        if item["status"] == upstream.LOCAL_CHANGES:
            print(f"{upstream.LOCAL_CHANGES}: {target}")
            for name in item["files"]:
                print(f"  изменён: {name}")
    print("Файлы не перезаписаны. Верните изменения или удалите папку цели и повторите.")


def install_own_skills(skills_dir: Path = OWN_SKILLS_DIR) -> list[str]:
    """Копирует наши навыки (skills/*) рядом с autopilot; изменённые существующие — в .bak-<UTC>."""
    if not skills_dir.is_dir():
        return []
    messages = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for skill in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        for base in (t.parent for t in upstream.default_targets()):
            target = base / skill.name
            if target.exists():
                if upstream.hash_tree(target) == upstream.hash_tree(skill):
                    continue
                # копия не рядом: папка с SKILL.md внутри skills/ считалась бы ещё одним навыком
                backups = upstream.kit_home() / ".autopilot-kit" / "backups"
                backups.mkdir(parents=True, exist_ok=True)
                owner = target.parent.parent.name.lstrip(".")
                shutil.move(str(target), str(backups / f"{owner}-{target.name}.bak-{stamp}"))
            shutil.copytree(skill, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            messages.append(f"навык {skill.name} → {target}")
    return messages


def _apply_agents() -> None:
    """Агенты Claude (~/.claude/agents/autopilot-*.md) из текущего профиля."""
    models = profile.load_models()
    current = profile.load()
    render.write_models_copy()
    for script in ("gate.py", "program.py", "program_page.html", "program_plan.md"):
        fsutil.write_with_backup(
            upstream.kit_home() / ".autopilot-kit" / "bin" / script,
            (Path(__file__).parent / script).read_text(encoding="utf-8"),
        )
    render.write_resolved(current, models)
    fsutil.write_with_backup(kit_path_file(), KIT_ROOT.as_posix() + "\n")
    for name in render.write_claude_agents(profile.resolve(current, "claude", models)):
        print(f"агент {name}")


def cmd_install(url: str = upstream.REPO_URL, pin_file: Path = PIN_FILE) -> int:
    pin = read_pin(pin_file)
    vend = None
    if url == upstream.REPO_URL:  # D56: копия оригинала лежит в репозитории kit — сеть не нужна
        try:
            vend = upstream.vendored(pin)
        except upstream.VendorError as error:
            print(f"Ошибка: {error}")
            return 1
    src = vend[0] if vend else upstream.fetch(pin, url=url)
    try:
        commit = vend[1] if vend else upstream.resolved_commit(src)
        hashes = upstream.hash_tree(src)
        report = upstream.install(src, upstream.default_targets(), upstream.read_lock())
        if any(i["status"] == upstream.LOCAL_CHANGES for i in report.values()):
            _print_local_changes(report)
            return 1
        lock = upstream.read_lock()
        if not lock or lock["commit"] != commit or lock["files"] != hashes:
            upstream.write_lock(commit, hashes, source=url)
        stage_message = upstream.install_stage_copy(src)
    finally:
        if not vend:  # копию в vendor не удаляем
            _cleanup(src)
    for target, item in report.items():
        print(f"{'без изменений' if item['status'] == 'unchanged' else 'установлено'}: {target}")
    print(f"Autopilot {commit[:12]}")
    print(stage_message)
    for message in install_own_skills():
        print(message)
    _apply_agents()
    return 0


def cmd_vendor(url: str = upstream.REPO_URL, pin_file: Path = PIN_FILE) -> int:
    """Положить в vendor/ копию оригинала закреплённого коммита (для репозитория kit; установка идёт уже из неё)."""
    pin = read_pin(pin_file)
    src = upstream.fetch(pin, url=url)
    try:
        commit = upstream.resolved_commit(src)
        print(f"Копия оригинала {commit[:12]}: {upstream.vendor_write(src, commit, url)}")
    finally:
        _cleanup(src)
    return 0


def cmd_status(url: str = upstream.REPO_URL) -> int:
    lock = upstream.read_lock()
    if not lock:
        print("Autopilot не установлен (нет upstream.lock.json). Запустите: python -m kit install")
        return 1
    ok = True
    print(f"Установлен коммит: {lock['commit']}")
    for target in upstream.default_targets():
        if not target.exists():
            print(f"ОТСУТСТВУЕТ: {target}")
            ok = False
        elif upstream.hash_tree(target) != lock["files"]:
            print(f"ИЗМЕНЁН: {target}")
            ok = False
        else:
            print(f"OK: {target}")
    head = remote_head(url)
    if head is None:
        print("GitHub: не удалось получить HEAD (нет сети?)")
    elif head == lock["commit"]:
        print(f"GitHub HEAD: {head[:12]} — обновлений нет")
    else:
        print(f"GitHub HEAD: {head[:12]} — есть обновление (python -m kit update)")
    return 0 if ok else 1


def _changes(src: Path, lock: dict, head: str) -> tuple[str, list[str]]:
    """Коммиты автора по skills/autopilot с установленной версии и изменённые файлы относительно lock."""
    log = subprocess.run(
        ["git", "log", "--oneline", f"{lock['commit']}..{head}", "--", upstream.SKILL_SUBPATH.as_posix()],
        cwd=Path(src).parents[1], capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
    new_hashes = upstream.hash_tree(src)
    changed = sorted(k for k in new_hashes.keys() | lock["files"].keys() if new_hashes.get(k) != lock["files"].get(k))
    return log, changed


def _print_changes(lock: dict, head: str, log: str, changed: list[str]) -> None:
    print(f"{lock['commit'][:12]} → {head[:12]}")
    print(log or "(нет коммитов, затрагивающих skills/autopilot)")
    print("Изменённые файлы:")
    for name in changed:
        print(f"  {name}")


def cmd_check_update(url: str = upstream.REPO_URL) -> int:
    """0 — Autopilot не менялся, 10 — есть новая версия, 1 — ошибка (нет lock или сети)."""
    lock = upstream.read_lock()
    if not lock:
        print("Autopilot не установлен (нет upstream.lock.json). Запустите: python -m kit install")
        return 1
    head = remote_head(url)
    if head is None:
        print("Не удалось получить HEAD с GitHub.")
        return 1
    if head == lock["commit"]:
        print(f"Обновлений нет: установлен {head[:12]}, он же HEAD.")
        return 0
    src = upstream.fetch(head, url=url)
    try:
        log, changed = _changes(src, lock, head)
    finally:
        _cleanup(src)
    if not changed:
        print(f"Обновлений Autopilot нет: HEAD {head[:12]} сдвинулся, но skills/autopilot не изменился.")
        return 0
    print("Есть новая версия Autopilot.")
    _print_changes(lock, head, log, changed)
    print("Проверить в dev, не трогая прод: python -m kit trial")
    return 10


def trial_root() -> Path:
    return upstream.kit_home() / ".autopilot-kit" / "trial"


def cmd_trial(url: str = upstream.REPO_URL, commit: str | None = None) -> int:
    """Dev-установка версии-кандидата в ~/.autopilot-kit/trial/home и проверка швов; прод не меняется."""
    prod_home = upstream.kit_home()
    lock = upstream.read_lock()
    head = commit or remote_head(url)
    if head is None:
        print("Не удалось получить HEAD с GitHub.")
        return 1
    root = trial_root()
    if root.exists():
        _rmtree(root)
    dev_home = root / "home"
    profile_file = prod_home / ".autopilot-kit" / "profile.toml"
    if profile_file.exists():  # клон прода: тот же профиль ролей
        (dev_home / ".autopilot-kit").mkdir(parents=True)
        shutil.copy2(profile_file, dev_home / ".autopilot-kit" / "profile.toml")
    src = upstream.fetch(head, url=url)
    saved = os.environ.get("AUTOPILOT_KIT_HOME")
    try:
        commit_full = upstream.resolved_commit(src)
        log, changed = _changes(src, lock, commit_full) if lock else ("", [])
        os.environ["AUTOPILOT_KIT_HOME"] = str(dev_home)
        upstream.install(src, upstream.default_targets(), None)
        upstream.write_lock(commit_full, upstream.hash_tree(src), source=url)
        stage = upstream.install_stage_copy(src)
        install_own_skills()
        _apply_agents()
        found = seams.check(upstream.default_targets()[0])
    finally:
        if saved is None:
            os.environ.pop("AUTOPILOT_KIT_HOME", None)
        else:
            os.environ["AUTOPILOT_KIT_HOME"] = saved
        _cleanup(src)
    ok = all(s["ok"] for s in found)
    lines = [
        "# Проверка версии Autopilot в dev", "",
        f"Прод: {lock['commit'][:12] if lock else 'не установлен'} · кандидат: {commit_full[:12]} · dev: `{dev_home}`", "",
        "## Коммиты автора по skills/autopilot", "", log or "—", "",
        "## Изменённые файлы", "", "\n".join(f"- {name}" for name in changed) or "—", "",
        "## Швы", "", "```", seams.render(found), "```", "",
        stage[:1].upper() + stage[1:], "",
        "**Итог:** " + ("есть красные швы — в прод не ставить, сначала подстроить надстройки" if not ok
                        else "кандидат совпадает с продом — ставить нечего" if lock and lock["commit"] == commit_full
                        else "швы зелёные — можно ставить в прод: `python -m kit update`"),
    ]
    report = "\n".join(lines) + "\n"
    (root / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Отчёт: {root / 'report.md'}")
    return 0 if ok else 1


def cmd_update(url: str = upstream.REPO_URL, pin_file: Path = PIN_FILE, assume_yes: bool = False) -> int:
    lock = upstream.read_lock()
    if not lock:
        print("Autopilot не установлен. Сначала: python -m kit install")
        return 1
    head = remote_head(url)
    if head is None:
        print("Не удалось получить HEAD с GitHub.")
        return 1
    if head == lock["commit"]:
        print("Уже актуально.")
        return 0
    src = upstream.fetch(head, url=url)
    try:
        log, changed = _changes(src, lock, head)
        new_hashes = upstream.hash_tree(src)
        _print_changes(lock, head, log, changed)
        found = seams.check(src)
        if not all(s["ok"] for s in found):  # D20: версию, на которой сломаются надстройки, в прод не ставим
            print("Швы не пройдены — прод не меняется:")
            print(seams.render([s for s in found if not s["ok"]]))
            return 1
        print("Швы зелёные.")
        if not assume_yes and input("Обновить? [y/N] ").strip().lower() != "y":
            print("Отменено.")
            return 1
        report = upstream.install(src, upstream.default_targets(), lock)
        if any(i["status"] == upstream.LOCAL_CHANGES for i in report.values()):
            _print_local_changes(report)
            return 1
        upstream.write_lock(head, new_hashes, source=url)
        pin_file.write_text(head + "\n", encoding="utf-8")
        if url == upstream.REPO_URL:  # D56: репозиторий kit хранит ту версию оригинала, на которой проверены швы
            print(f"Копия оригинала обновлена: {upstream.vendor_write(src, head, url)}")
        print(upstream.install_stage_copy(src))
    finally:
        _cleanup(src)
    print("Обновлено.")
    _apply_agents()
    return 0
