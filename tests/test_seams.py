from kit import seams

# Маленький ap.py с тем же контрактом state.js, что у оригинала: команды прогона и «window.STATE = {...}».
FAKE_AP = '''
import json, os, sys
from datetime import datetime, timezone
A = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(A, "state.js")
def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
def load():
    raw = open(STATE, encoding="utf-8").read()
    return json.loads(raw.split("=", 1)[1])
def save(s):
    open(STATE, "w", encoding="utf-8").write("window.STATE =\\n" + json.dumps(s, ensure_ascii=False))
args = [a for a in sys.argv[1:] if a != "--no-serve"]
opt = {args[i][2:]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--")}
pos = [a for i, a in enumerate(args) if not a.startswith("--") and not (i and args[i - 1].startswith("--"))]
cmd = pos[0]
if cmd == "init":
    s = {"dir": opt["slug"] + "--wip", "startedAt": now(), "finishedAt": None, "waiting": None, "stages": [],
         "tickets": [], "gates": {}, "blind": None, "result": None}
else:
    s = load()
if cmd == "set":
    k, v = pos[1].split("=", 1)
    s[k] = v
elif cmd == "ask":
    s["waiting"] = WAITING
elif cmd == "answered":
    s["waiting"] = None
elif cmd == "stage":
    s["waiting"] = None
    s["stages"] = [{"id": pos[1], "status": "active", "note": opt.get("note")}]
elif cmd == "blind":
    s["blind"] = {"checked": 1, "matched": 1, "mismatches": []}
    s["gates"]["G4"] = {"ok": True}
elif cmd == "tests":
    p, f = pos[1].split("/")
    s["tests"] = {"passed": int(p), "failed": int(f)}
elif cmd == "finish":
    s["finishedAt"] = now()
    s["result"] = opt.get("result")
    for st in s["stages"]:
        st["status"] = "done"
save(s)
'''

SKILL = "---\nname: autopilot\ndescription: Builds things.\ndisable-model-invocation: true\n---\n\n# Autopilot\n"


def make_core(root, ap_waiting='{"kind": pos[1], "note": opt.get("note")}', skill=SKILL, final_text=None):
    files = {
        "SKILL.md": skill,
        "tools/ap.py": FAKE_AP.replace("WAITING", ap_waiting) + "\n# window.STATE =\n",
        "phases/dashboard-template.html": "<html></html>",
        "phases/0-instruments.md": "инструменты",
        "phases/0-modes.md": "full semi interview manual",
        "phases/5-subagents.md": "читай prompts/executor.md",
        "phases/6-review.md": "читай prompts/review.md",
        "phases/8-final.md": final_text if final_text is not None else "коммит «Autopilot: сборка сдана», PROGRESS.md",
        "prompts/executor.md": "исполнитель",
        "prompts/review.md": "ревью",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def by_name(found):
    return {s["seam"]: s for s in found}


def test_all_seams_green_on_intact_core(tmp_path):
    found = seams.check(make_core(tmp_path / "core"))
    assert all(s["ok"] for s in found), seams.render(found)
    names = by_name(found)
    assert "флаг disable-model-invocation есть" in names["копия autopilot-stage"]["detail"]
    assert {"ap.py → program.py: ожидание владельца", "ap.py → gate.py: ожидание владельца",
            "ap.py → program.py: прогон идёт", "ap.py → program.py: сдача прогона"} <= names.keys()


def test_lost_anchor_and_missing_file(tmp_path):
    core = make_core(tmp_path / "core", final_text="отчёт без коммита")
    (core / "prompts" / "review.md").unlink()
    names = by_name(seams.check(core))
    assert not names["тексты-якоря"]["ok"] and "Autopilot: сборка сдана" in names["тексты-якоря"]["detail"]
    assert not names["файлы ядра"]["ok"] and "prompts/review.md" in names["файлы ядра"]["detail"]


def test_frontmatter_change_breaks_stage_copy(tmp_path):
    names = by_name(seams.check(make_core(tmp_path / "core", skill="# Autopilot без frontmatter\n")))
    assert not names["копия autopilot-stage"]["ok"]


def test_renamed_waiting_field_is_caught(tmp_path):
    # автор переименовал поле ожидания: program.py и gate.py перестали бы видеть вопросы владельцу
    core = make_core(tmp_path / "core", ap_waiting="None")
    names = by_name(seams.check(core))
    assert not names["ap.py → program.py: ожидание владельца"]["ok"]
    assert not names["ap.py → gate.py: ожидание владельца"]["ok"]
    assert names["ap.py → program.py: сдача прогона"]["ok"]


def test_render_marks_ok_and_fail():
    text = seams.render([{"seam": "а", "ok": True, "detail": "1"}, {"seam": "б", "ok": False, "detail": "2"}])
    assert text.splitlines() == ["OK    а: 1", "FAIL  б: 2"]
