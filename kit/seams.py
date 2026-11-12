"""Швы: всё, на что надстройки kit опираются в оригинальном Autopilot (D20).

check(skill_dir) проверяет версию Autopilot (папку skills/autopilot) до того, как она попадёт в прод:
файлы ядра, frontmatter для копии autopilot-stage, тексты-якоря и поведение настоящего ap.py во временном
git-проекте — его state.js читают наши program.py и gate.py так же, как в работе.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from kit import gate, program, upstream

# файлы ядра, на которые ссылаются autopilot-roles, autopilot-program и gate
REQUIRED_FILES = (
    "SKILL.md", "tools/ap.py", "phases/dashboard-template.html", "phases/0-instruments.md",
    "phases/0-modes.md", "phases/5-subagents.md", "phases/6-review.md", "phases/8-final.md",
    "prompts/executor.md", "prompts/review.md",
)

# тексты, на которых держатся правила надстроек: коммит сдачи (program.py), режимы (program.json mode),
# пути к контрактам субагентов (autopilot-roles §3), формат state.js (gate.py, program.py)
ANCHORS = {
    "phases/8-final.md": (program.LANDING_SUBJECT, "PROGRESS.md"),
    "phases/0-modes.md": ("full", "semi", "interview", "manual"),
    "phases/5-subagents.md": ("prompts/executor.md",),
    "phases/6-review.md": ("prompts/review.md",),
    "tools/ap.py": ("window.STATE =",),
}


def _seam(name: str, ok: bool, detail: str = "") -> dict:
    return {"seam": name, "ok": bool(ok), "detail": detail}


def check_files(skill_dir: Path) -> list[dict]:
    missing = [f for f in REQUIRED_FILES if not (skill_dir / f).is_file()]
    return [_seam("файлы ядра", not missing, "нет: " + ", ".join(missing) if missing else f"{len(REQUIRED_FILES)} на месте")]


def check_frontmatter(skill_dir: Path) -> list[dict]:
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        return [_seam("копия autopilot-stage", False, "нет SKILL.md")]
    text = path.read_text(encoding="utf-8")
    try:
        upstream.stage_skill_text(text)
    except ValueError as error:
        return [_seam("копия autopilot-stage", False, str(error))]
    head = text.split("\n---", 1)[0]
    flag = "disable-model-invocation" in head
    return [_seam("копия autopilot-stage", True,
                  "флаг disable-model-invocation есть — копия нужна" if flag
                  else "флага disable-model-invocation нет — копия уже не обязательна")]


def check_anchors(skill_dir: Path) -> list[dict]:
    lost = []
    for rel, phrases in ANCHORS.items():
        path = skill_dir / rel
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        lost += [f"{rel}: «{p}»" for p in phrases if p not in text]
    return [_seam("тексты-якоря", not lost, "нет: " + "; ".join(lost) if lost else "все на месте")]


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return out.returncode, (out.stdout + out.stderr).strip()


def check_ap(skill_dir: Path) -> list[dict]:
    """Настоящий ap.py во временном проекте: ожидание → продолжение → сдача, глазами program.py и gate.py."""
    ap_src = skill_dir / "tools" / "ap.py"
    page = skill_dir / "phases" / "dashboard-template.html"
    if not ap_src.is_file() or not page.is_file():
        return [_seam("ap.py: прогон", False, "нет tools/ap.py или dashboard-template.html")]
    work = Path(tempfile.mkdtemp(prefix="autopilot-kit-seams-"))
    seams: list[dict] = []
    try:
        _run(["git", "init", "-q"], work)
        commit = ["git", "-c", "user.name=kit", "-c", "user.email=kit@localhost", "commit", "-q", "--allow-empty", "-m"]
        _run([*commit, "init"], work)
        (work / ".autopilot").mkdir()
        shutil.copy2(ap_src, work / ".autopilot" / "ap.py")
        shutil.copy2(page, work / ".autopilot" / "dashboard.html")
        program.cmd_init(work, "швы", None, "semi")
        program.cmd_stage_add(work, "S1", "шов", "проверка швов", None, [])
        program.cmd_start(work, "S1", adopt=False)

        def ap(*args: str) -> tuple[int, str]:
            return _run([sys.executable, str(work / ".autopilot" / "ap.py"), *args, "--no-serve"], work)

        def verdict() -> dict:
            data = program.load(work)
            return program.evaluate(work, data, data["stages"][0], with_gate=False)

        steps = [
            ("init", ap("init", "--slug", "seams", "--title", "Проверка швов", "--mode", "semi", "--depth", "normal",
                        "--memory-file", "AGENTS.md", "--memory-owner", "autopilot", "--skill-dir", str(skill_dir))),
            ("set deliverable", ap("set", "deliverable=docs")),
            ("ask briefing", ap("ask", "briefing", "--note", "вопрос шва")),
        ]
        failed = [f"{name}: код {rc}: {out[-300:]}" for name, (rc, out) in steps if rc != 0]
        if failed:
            return [_seam("ap.py: команды", False, "; ".join(failed))]
        v = verdict()
        waiting_ok = v.get("verdict") == "waiting" and v.get("kind") == "briefing" and v.get("note") == "вопрос шва"
        seams.append(_seam("ap.py → program.py: ожидание владельца", waiting_ok, json.dumps(v, ensure_ascii=False)[:300]))
        seams.append(_seam("ap.py → gate.py: ожидание владельца", gate.autopilot_waiting(work) == "briefing",
                           f"gate видит: {gate.autopilot_waiting(work)}"))
        steps = [("answered", ap("answered")), ("stage --note", ap("stage", "build", "--note", "шов"))]
        v = verdict()
        seams.append(_seam("ap.py → program.py: прогон идёт", v.get("verdict") == "unfinished"
                           and all(rc == 0 for _, (rc, _) in steps), json.dumps(v, ensure_ascii=False)[:300]))
        # Autopilot 2.2.3: finish не сдаёт сборку без G1–G3 — манифест (G1), сверка спецификации (G2), трасса (G3)
        for run in (work / ".autopilot").glob("*seams*"):
            if run.is_dir():
                (run / "manifest.md").write_text("| ID | Цитата | Статус | Основание |\n|---|---|---|---|\n"
                                                 "| R1 | шов | covered | проверка швов |\n", encoding="utf-8")
        steps = [("coverage", ap("coverage", "found=0", "fixed=0", "deferred=0")), ("check-plan", ap("check-plan")),
                 ("blind", ap("blind", "checked=1", "matched=1")), ("tests", ap("tests", "1/0")),
                 ("finish", ap("finish", "--result", "итог шва"))]
        failed = [f"{name}: код {rc}: {out[-300:]}" for name, (rc, out) in steps if rc != 0]
        _run([*commit, program.LANDING_SUBJECT], work)
        v = verdict()
        warnings = [w for w in v.get("warnings") or [] if not w.startswith("гейт")]  # гейт здесь не запускается
        done_ok = (not failed and v.get("verdict") == "passed" and not v.get("reasons") and not warnings
                   and v.get("result") == "итог шва" and v.get("deliverable") == "docs"
                   and v.get("tests") == {"passed": 1, "failed": 0})
        seams.append(_seam("ap.py → program.py: сдача прогона", done_ok,
                           "; ".join(failed) or json.dumps({k: v.get(k) for k in ("verdict", "reasons", "warnings", "result",
                                                                                     "deliverable", "tests")},
                                                           ensure_ascii=False)[:400]))
    except (OSError, program.ProgramError, ValueError) as error:
        seams.append(_seam("ap.py: прогон", False, f"{type(error).__name__}: {error}"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return seams


def check(skill_dir: Path) -> list[dict]:
    skill_dir = Path(skill_dir)
    return check_files(skill_dir) + check_frontmatter(skill_dir) + check_anchors(skill_dir) + check_ap(skill_dir)


def render(seams: list[dict]) -> str:
    return "\n".join(f"{'OK  ' if s['ok'] else 'FAIL'}  {s['seam']}: {s['detail']}" for s in seams)
