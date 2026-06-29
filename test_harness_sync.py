import os
import tempfile
from pathlib import Path

import harness_sync as hs


def _make_skill(base: Path, name: str, files: dict[str, str]) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in files.items():
        p = d / fn
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_skill_hash_is_order_and_path_sensitive():
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        a = _make_skill(base, "a", {"SKILL.md": "x", "extra.md": "y"})
        b = _make_skill(base, "b", {"extra.md": "y", "SKILL.md": "x"})
        c = _make_skill(base, "c", {"SKILL.md": "different", "extra.md": "y"})
        assert hs.skill_hash(a) == hs.skill_hash(b)   # order-independent
        assert hs.skill_hash(a) != hs.skill_hash(c)   # content-sensitive


def test_scan_missing_dir_is_empty():
    with tempfile.TemporaryDirectory() as t:
        assert hs.scan(Path(t) / "nope") == {}


def test_scan_lists_skill_dirs_only():
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        _make_skill(base, "one", {"SKILL.md": "1"})
        (base / "loose.txt").write_text("ignore me")
        result = hs.scan(base)
        assert set(result) == {"one"}


def test_resolve_paths_honors_env():
    with tempfile.TemporaryDirectory() as t:
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(t) / "cc")
        os.environ["CODEX_HOME"] = str(Path(t) / "cx")
        try:
            paths = hs.resolve_paths(Path(t) / "repo")
            assert paths.harness_skills["claude"] == Path(t) / "cc" / "skills"
            assert paths.harness_skills["codex"] == Path(t) / "cx" / "skills"
            assert paths.repo_skills == Path(t) / "repo" / "skills"
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
            del os.environ["CODEX_HOME"]


def test_load_manifest_absent_returns_empty():
    with tempfile.TemporaryDirectory() as t:
        assert hs.load_manifest(Path(t) / "manifest.json") == {"skills": {}}


def test_manifest_roundtrip():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "manifest.json"
        data = {"skills": {"branch-pr": {"targets": ["claude", "codex"]}}}
        hs.save_manifest(p, data)
        assert hs.load_manifest(p) == data
        assert p.read_text().endswith("\n")


def _paths_in(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        harness_skills={"claude": t / "cc" / "skills", "codex": t / "cx" / "skills"},
    )


def test_compute_states_covers_all_cases():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["codex"], "alpha", {"SKILL.md": "OLD"})
        _make_skill(p.harness_skills["codex"], "beta", {"SKILL.md": "x"})

        rows = {r["name"]: r for r in hs.compute_states(p)}

        assert rows["alpha"]["repo"] is True
        assert rows["alpha"]["claude"] == "synced"
        assert rows["alpha"]["codex"] == "drift"
        assert rows["beta"]["repo"] is False
        assert rows["beta"]["claude"] == "absent"
        assert rows["beta"]["codex"] == "untracked"


if __name__ == "__main__":
    import traceback
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
