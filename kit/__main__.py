"""Точка входа: python -m kit <команда>."""
import argparse
import sys
from pathlib import Path

from kit import commands, dashboard, doctor, profile, project, projects, setup_cli, uninstall

try:
    from kit import publish
except ImportError:  # публичная копия без механизма публикации (D55)
    publish = None

COMMANDS = {
    "install": "установить Autopilot и навыки kit",
    "update": "обновить Autopilot (после проверки швов)",
    "check-update": "есть ли новая версия Autopilot на GitHub",
    "vendor": "положить в vendor/ копию оригинала закреплённого коммита (D56)",
    "trial": "поставить новую версию в dev-песочницу и проверить швы",
    "status": "показать состояние установки",
    "doctor": "проверить окружение (--projects — и проекты)",
    "relocate": "починить проекты после переезда: хуки, kit_path, .gitignore, сессии",
    "dashboard": "пульт всех программ: страница с состоянием и тем, что требует внимания",
    "uninstall": "удалить установленное kit",
    "project": "работа с проектом (init)",
    "profile": "профиль ролей (set)",
}
if publish is not None:
    COMMANDS["publish"] = "собрать чистую публичную копию из приватного репозитория (D55; по умолчанию — проверка)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit", description="Autopilot Kit")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        if name in ("update", "uninstall"):
            command.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
        if name in ("doctor", "relocate"):
            if name == "doctor":
                command.add_argument("--projects", action="store_true", help="проверить проекты из реестра программ")
            else:
                command.add_argument("--dry-run", action="store_true", help="только показать, что будет изменено")
            command.add_argument("--project", action="append", default=[], type=Path, metavar="ПАПКА")
        if name == "dashboard":
            command.add_argument("--project", action="append", default=[], type=Path, metavar="ПАПКА")
            command.add_argument("--port", type=int, default=dashboard.PORT)
            command.add_argument("--no-open", action="store_true", help="не открывать браузер")
            command.add_argument("--foreground", action="store_true", help="держать сервер в этом окне")
        if name == "publish":
            command.add_argument("--to", type=Path, metavar="ПАПКА", help="клон публичного репозитория (создаётся, если нет)")
            command.add_argument("--apply", action="store_true", help="записать снимок в клон и сделать коммит (без этого — только проверка)")
            command.add_argument("--tag", help="тег версии публичной копии")
            command.add_argument("--ref", default="HEAD", help="коммит источника (по умолчанию HEAD)")
            command.add_argument("--no-tests", action="store_true", help="не гонять тесты на снимке")
            command.add_argument("--push", action="store_true", help="после коммита отправить в origin клона (только с --apply)")
            command.add_argument("--keep", action="store_true", help="оставить временный снимок и показать путь")
        if name == "trial":
            command.add_argument("--commit", help="коммит автора (по умолчанию HEAD)")
        if name == "project":
            actions = command.add_subparsers(dest="action", required=True)
            init_cmd = actions.add_parser("init", help="скопировать шаблон проекта")
            init_cmd.add_argument("--template", required=True)
            init_cmd.add_argument("--path", default=".")
        if name == "profile":
            actions = command.add_subparsers(dest="action", required=True)
            set_cmd = actions.add_parser("set", help="записать профиль и пересоздать агентов")
            set_cmd.add_argument("--preset", choices=sorted(profile.PRESETS))
            set_cmd.add_argument("--role", action="append", default=[], metavar="РОЛЬ=УРОВЕНЬ:УСИЛИЕ")
            set_cmd.add_argument("--drive", choices=profile.DRIVES,
                                 help="явно зафиксировать привод (T19.8): переопределяет определение по окружению")
            set_cmd.add_argument("--dry-run", action="store_true", help="только показать таблицу")
    return parser


def _utf8_output() -> None:
    """Сообщения со стрелками и кириллицей не должны ронять команду в консоли cp1251."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # подменённый поток (тесты) — оставляем как есть
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = build_parser().parse_args(argv)
    if args.command == "install":
        return commands.cmd_install()
    if args.command == "status":
        return commands.cmd_status()
    if args.command == "update":
        return commands.cmd_update(assume_yes=args.yes)
    if args.command == "vendor":
        return commands.cmd_vendor()
    if args.command == "check-update":
        return commands.cmd_check_update()
    if args.command == "trial":
        return commands.cmd_trial(commit=args.commit)
    if args.command == "uninstall":
        return uninstall.cmd_uninstall(args.yes)
    if args.command == "doctor":
        return doctor.cmd_doctor(args.projects, args.project)
    if args.command == "relocate":
        print("\n".join(projects.relocate(args.project, args.dry_run)))
        return 0
    if args.command == "dashboard":
        return dashboard.cmd_dashboard(args.project, args.port, args.foreground, not args.no_open)
    if args.command == "project":
        try:
            lines = project.init_project(args.template, Path(args.path))
        except ValueError as error:
            print(f"Ошибка: {error}")
            return 2
        print("\n".join(lines))
        return 0
    if args.command == "publish":
        return publish.cmd_publish(args.ref, args.to, args.apply, args.tag, not args.no_tests, args.push, args.keep)
    if args.command == "profile":
        return setup_cli.cmd_profile_set(args.preset, args.role, args.dry_run, args.drive)
    print("NOT_IMPLEMENTED")
    return 3


if __name__ == "__main__":
    sys.exit(main())
