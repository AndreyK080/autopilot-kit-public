import subprocess
import sys

COMMANDS = ["install", "update", "status", "doctor", "dashboard", "uninstall", "project", "profile"]


def run(*args):
    return subprocess.run([sys.executable, "-m", "kit", *args], capture_output=True, text=True, encoding="utf-8")


def test_help_lists_all_commands():
    out = run("--help").stdout
    for name in COMMANDS:
        assert name in out


def test_subcommand_without_action_is_an_error():
    assert run("project").returncode == 2
    assert run("profile").returncode == 2
