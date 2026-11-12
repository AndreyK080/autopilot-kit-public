from kit import upstream


def test_fetch_pinned_and_head(remote, tmp_path):
    old = upstream.fetch(remote["first"], url=remote["url"], dest=tmp_path / "c1")
    assert (old / "SKILL.md").read_text(encoding="utf-8") == "v1"
    assert upstream.resolved_commit(old) == remote["first"]
    new = upstream.fetch(None, url=remote["url"], dest=tmp_path / "c2")
    assert (new / "SKILL.md").read_text(encoding="utf-8") == "v2"
    assert upstream.resolved_commit(new) == remote["second"]


def test_hash_tree_sorted_posix_no_pycache(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x.md").write_text("x")
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.pyc").write_text("c")
    assert list(upstream.hash_tree(tmp_path)) == ["a.md", "b/x.md"]


def test_lock_roundtrip(tmp_path):
    path = tmp_path / "lock.json"
    assert upstream.read_lock(path) is None
    upstream.write_lock("abc", {"a": "1"}, source="u", path=path)
    lock = upstream.read_lock(path)
    assert lock["commit"] == "abc" and lock["files"] == {"a": "1"} and lock["source"] == "u"
    assert lock["installed_at"].endswith("Z")


def test_install_lock_idempotent_and_local_changes(remote, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "home"))
    targets = upstream.default_targets()
    assert all(str(tmp_path / "home") in str(t) for t in targets)

    src1 = upstream.fetch(remote["first"], url=remote["url"], dest=tmp_path / "c1")
    report = upstream.install(src1, targets, upstream.read_lock())
    assert {r["status"] for r in report.values()} == {"installed"}
    upstream.write_lock(remote["first"], upstream.hash_tree(src1))

    again = upstream.install(src1, targets, upstream.read_lock())
    assert {r["status"] for r in again.values()} == {"unchanged"}

    (targets[0] / "SKILL.md").write_text("hand edit", encoding="utf-8")
    src2 = upstream.fetch(remote["second"], url=remote["url"], dest=tmp_path / "c2")
    blocked = upstream.install(src2, targets, upstream.read_lock())
    assert blocked[targets[0]] == {"status": upstream.LOCAL_CHANGES, "files": ["SKILL.md"]}
    assert (targets[0] / "SKILL.md").read_text(encoding="utf-8") == "hand edit"
    # вторая цель не тронута: всё или ничего
    assert (targets[1] / "SKILL.md").read_text(encoding="utf-8") == "v1"


def test_install_update_replaces_clean_targets(remote, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_KIT_HOME", str(tmp_path / "home"))
    targets = upstream.default_targets()
    src1 = upstream.fetch(remote["first"], url=remote["url"], dest=tmp_path / "c1")
    upstream.install(src1, targets)
    upstream.write_lock(remote["first"], upstream.hash_tree(src1))
    src2 = upstream.fetch(remote["second"], url=remote["url"], dest=tmp_path / "c2")
    report = upstream.install(src2, targets, upstream.read_lock())
    assert {r["status"] for r in report.values()} == {"installed"}
    assert all((t / "SKILL.md").read_text(encoding="utf-8") == "v2" for t in targets)


def test_install_existing_without_lock_differs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("new")
    target = tmp_path / "t"
    target.mkdir()
    (target / "SKILL.md").write_text("other")
    report = upstream.install(src, [target], None)
    assert report[target]["status"] == upstream.LOCAL_CHANGES


UPSTREAM_SKILL = (
    "---\nname: autopilot\ndescription: Builds an app. Starts only on /autopilot.\n"
    "disable-model-invocation: true\nargument-hint: \"[full|semi] что строить\"\n---\n\n# Autopilot\n\nТело.\n"
)


def test_stage_skill_text_renames_and_drops_flag():
    text = upstream.stage_skill_text(UPSTREAM_SKILL)
    head, body = text.split("\n---\n", 1)
    assert "name: autopilot-stage" in head
    assert "disable-model-invocation" not in head
    assert "/autopilot-program" in head and 'argument-hint: "[full|semi] что строить"' in head
    assert body == "\n# Autopilot\n\nТело.\n"


def test_stage_copy_install_reinstall_remove(tmp_path):
    src = tmp_path / "src"
    (src / "phases").mkdir(parents=True)
    (src / "SKILL.md").write_text(UPSTREAM_SKILL, encoding="utf-8")
    (src / "phases" / "one.md").write_text("фаза", encoding="utf-8")
    target = tmp_path / "skills" / "autopilot-stage"
    assert "копия для этапов" in upstream.install_stage_copy(src, target)
    assert (target / "phases" / "one.md").read_text(encoding="utf-8") == "фаза"
    assert "name: autopilot-stage" in (target / "SKILL.md").read_text(encoding="utf-8")
    (src / "phases" / "one.md").write_text("фаза 2", encoding="utf-8")
    upstream.install_stage_copy(src, target)
    assert (target / "phases" / "one.md").read_text(encoding="utf-8") == "фаза 2"
    assert "удалена" in upstream.remove_stage_copy(target)
    assert not target.exists()


def test_stage_copy_leaves_foreign_folder_and_odd_frontmatter(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("v1", encoding="utf-8")
    target = tmp_path / "autopilot-stage"
    assert "не сделана" in upstream.install_stage_copy(src, target)
    assert not target.exists()
    target.mkdir()
    (target / "SKILL.md").write_text("моё", encoding="utf-8")
    assert "не от kit" in upstream.install_stage_copy(src, target)
    assert "не от kit" in upstream.remove_stage_copy(target)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "моё"
