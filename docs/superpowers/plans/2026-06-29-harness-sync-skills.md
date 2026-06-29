# harness-sync (Skills) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stdlib-only Python CLI that selectively syncs skill directories between Claude Code and Codex, using a neutral repo as the source of truth.

**Architecture:** One module `harness_sync.py` with pure, path-injected functions (hashing, scanning, manifest I/O, adopt, apply) wrapped by an argparse CLI. State is derived by comparing content hashes across repo / Claude / Codex. A JSON manifest records per-skill target decisions. `apply` is declarative and idempotent; `adopt` is interactive but delegates to a non-interactive core.

**Tech Stack:** Python 3.11+ standard library only (`pathlib`, `shutil`, `hashlib`, `json`, `argparse`, `os`, `datetime`, `tempfile`). No third-party dependencies. No test framework — tests run via `python test_harness_sync.py`.

## Global Constraints

- Python **3.11+**, **standard library only**. No pip dependencies.
- Harness skill dirs resolve via env: `claude` → `$CLAUDE_CONFIG_DIR/skills` (default `~/.claude/skills`); `codex` → `$CODEX_HOME/skills` (default `~/.codex/skills`).
- `HARNESSES = ("claude", "codex")`. A skill "target" is one of `claude`, `codex`, `ignore`.
- **Safety:** `apply` never deletes from a harness; it only adds/updates skills listed in the manifest. It backs up any overwritten target dir to `.harness-sync-backups/<timestamp>/<harness>/<name>/` before replacing.
- Manifest path: `<repo>/manifest.json`. Canonical skills: `<repo>/skills/<name>/`.
- All code, comments, commit messages in English.
- Commit messages end with the Co-Authored-By trailer.

---

### Task 0: Project setup

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Init git on a feature branch**

```bash
cd /Users/nacho/Documents/harness-sincronizer
git init -q
git checkout -b feature/skills-sync
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.harness-sync-backups/
.atl/
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore docs/
git commit -m "chore: scaffold harness-sync repo

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: Path resolution + skill hashing

**Files:**
- Create: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Produces:
  - `HARNESSES = ("claude", "codex")`
  - `Paths` dataclass: `repo_skills: Path`, `manifest: Path`, `backups: Path`, `harness_skills: dict[str, Path]`
  - `harness_skill_dir(harness: str) -> Path`
  - `resolve_paths(repo_root: Path) -> Paths`
  - `skill_hash(skill_dir: Path) -> str` — sha256 over sorted `(relpath, bytes)`; order-independent
  - `scan(skills_dir: Path) -> dict[str, str]` — `{name: hash}`; `{}` if dir missing

- [ ] **Step 1: Write the failing tests**

In `test_harness_sync.py`:

```python
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


def test_resolve_paths_honors_env(monkeypatch=None):
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
```

Add a stdlib test runner at the bottom of the file:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_harness_sync.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_sync'`

- [ ] **Step 3: Write minimal implementation**

In `harness_sync.py`:

```python
#!/usr/bin/env python3
"""harness-sync: selective skill sync between Claude Code and Codex."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

HARNESSES = ("claude", "codex")


@dataclass(frozen=True)
class Paths:
    repo_skills: Path
    manifest: Path
    backups: Path
    harness_skills: dict[str, Path]


def harness_skill_dir(harness: str) -> Path:
    if harness == "claude":
        base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        return base / "skills"
    if harness == "codex":
        base = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return base / "skills"
    raise ValueError(f"unknown harness: {harness}")


def resolve_paths(repo_root: Path) -> Paths:
    return Paths(
        repo_skills=repo_root / "skills",
        manifest=repo_root / "manifest.json",
        backups=repo_root / ".harness-sync-backups",
        harness_skills={h: harness_skill_dir(h) for h in HARNESSES},
    )


def skill_hash(skill_dir: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        h.update(f.relative_to(skill_dir).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def scan(skills_dir: Path) -> dict[str, str]:
    if not skills_dir.is_dir():
        return {}
    return {d.name: skill_hash(d) for d in sorted(skills_dir.iterdir()) if d.is_dir()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_harness_sync.py`
Expected: `PASS` for all four tests, exit 0.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add path resolution and skill hashing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Manifest load/save

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: nothing from Task 1 beyond imports.
- Produces:
  - `load_manifest(path: Path) -> dict` — returns `{"skills": {}}` if file absent
  - `save_manifest(path: Path, data: dict) -> None` — writes pretty, sorted JSON + trailing newline

- [ ] **Step 1: Write the failing tests**

Append to `test_harness_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'load_manifest'`

- [ ] **Step 3: Write minimal implementation**

Add `import json` to the imports, and append:

```python
def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"skills": {}}
    return json.loads(path.read_text())


def save_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_harness_sync.py`
Expected: all `PASS`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add JSON manifest load/save

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: State computation (status)

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `scan`, `Paths`, `HARNESSES`.
- Produces:
  - `compute_states(paths: Paths) -> list[dict]` — each row: `{"name": str, "repo": bool, "claude": str, "codex": str}` where the per-harness value is one of `absent`, `untracked`, `synced`, `drift`. Rows sorted by name.

State rules per harness, given repo hash `r` and harness hash `hh`:
- `hh is None` → `absent`
- `r is None` → `untracked`
- `hh == r` → `synced`
- else → `drift`

- [ ] **Step 1: Write the failing test**

Append to `test_harness_sync.py`:

```python
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
        # synced in claude, drift in codex
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["codex"], "alpha", {"SKILL.md": "OLD"})
        # untracked: only in codex, not in repo
        _make_skill(p.harness_skills["codex"], "beta", {"SKILL.md": "x"})

        rows = {r["name"]: r for r in hs.compute_states(p)}

        assert rows["alpha"]["repo"] is True
        assert rows["alpha"]["claude"] == "synced"
        assert rows["alpha"]["codex"] == "drift"
        assert rows["beta"]["repo"] is False
        assert rows["beta"]["claude"] == "absent"
        assert rows["beta"]["codex"] == "untracked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'compute_states'`

- [ ] **Step 3: Write minimal implementation**

Append:

```python
def compute_states(paths: Paths) -> list[dict]:
    repo = scan(paths.repo_skills)
    harness = {h: scan(paths.harness_skills[h]) for h in HARNESSES}
    names = set(repo) | {n for hs_map in harness.values() for n in hs_map}
    rows = []
    for name in sorted(names):
        r = repo.get(name)
        row = {"name": name, "repo": r is not None}
        for h in HARNESSES:
            hh = harness[h].get(name)
            if hh is None:
                row[h] = "absent"
            elif r is None:
                row[h] = "untracked"
            elif hh == r:
                row[h] = "synced"
            else:
                row[h] = "drift"
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_harness_sync.py`
Expected: all `PASS`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add skill state computation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Adopt core (non-interactive)

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `Paths`, `load_manifest`, `save_manifest`.
- Produces:
  - `copy_skill(src: Path, dst: Path) -> None` — replace `dst` with a copy of `src`
  - `adopt_skill(paths: Paths, name: str, source_harness: str, targets: list[str]) -> None` — copy `source_harness`'s skill into the repo and record `{"targets": targets}` in the manifest

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_adopt_skill_imports_and_records():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "gamma", {"SKILL.md": "body"})

        hs.adopt_skill(p, "gamma", "claude", ["claude", "codex"])

        assert (p.repo_skills / "gamma" / "SKILL.md").read_text() == "body"
        man = hs.load_manifest(p.manifest)
        assert man["skills"]["gamma"] == {"targets": ["claude", "codex"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_harness_sync.py`
Expected: FAIL — `AttributeError: ... has no attribute 'adopt_skill'`

- [ ] **Step 3: Write minimal implementation**

Add `import shutil` to imports, and append:

```python
def copy_skill(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def adopt_skill(paths: Paths, name: str, source_harness: str, targets: list[str]) -> None:
    copy_skill(paths.harness_skills[source_harness] / name, paths.repo_skills / name)
    man = load_manifest(paths.manifest)
    man["skills"][name] = {"targets": list(targets)}
    save_manifest(paths.manifest, man)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_harness_sync.py`
Expected: all `PASS`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add adopt core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Apply (backup, idempotent, dry-run)

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `Paths`, `skill_hash`, `copy_skill`, `load_manifest`, `HARNESSES`.
- Produces:
  - `apply_skill(paths: Paths, name: str, targets: list[str], dry_run: bool = False) -> list[str]` — for each harness in `targets` (ignoring non-harness values like `"ignore"`), push the repo skill if the target differs; back up the existing target dir first; return human-readable change strings `"<name> -> <harness>"`. Idempotent: returns `[]` when targets already match.
  - `apply_all(paths: Paths, dry_run: bool = False) -> list[str]` — iterate the manifest, skip skills whose targets contain `"ignore"`, aggregate changes.

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_apply_pushes_backs_up_and_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "delta", {"SKILL.md": "new"})
        # pre-existing different content in codex -> must be backed up
        _make_skill(p.harness_skills["codex"], "delta", {"SKILL.md": "old"})

        changes = hs.apply_skill(p, "delta", ["codex"])
        assert changes == ["delta -> codex"]
        assert (p.harness_skills["codex"] / "delta" / "SKILL.md").read_text() == "new"
        # backup of the overwritten dir exists somewhere under backups/
        backups = list(p.backups.rglob("delta/SKILL.md"))
        assert backups and backups[0].read_text() == "old"

        # second run is a no-op
        assert hs.apply_skill(p, "delta", ["codex"]) == []


def test_apply_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "eps", {"SKILL.md": "new"})
        changes = hs.apply_skill(p, "eps", ["claude"], dry_run=True)
        assert changes == ["eps -> claude"]
        assert not (p.harness_skills["claude"] / "eps").exists()


def test_apply_all_skips_ignored_and_leaves_untracked():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "keep", {"SKILL.md": "k"})
        _make_skill(p.repo_skills, "skip", {"SKILL.md": "s"})
        hs.save_manifest(p.manifest, {"skills": {
            "keep": {"targets": ["claude"]},
            "skip": {"targets": ["ignore"]},
        }})
        # an untracked skill already in claude must NOT be touched/deleted
        _make_skill(p.harness_skills["claude"], "foreign", {"SKILL.md": "f"})

        changes = hs.apply_all(p)
        assert changes == ["keep -> claude"]
        assert (p.harness_skills["claude"] / "keep").exists()
        assert not (p.harness_skills["claude"] / "skip").exists()
        assert (p.harness_skills["claude"] / "foreign" / "SKILL.md").read_text() == "f"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_harness_sync.py`
Expected: FAIL — `AttributeError: ... has no attribute 'apply_skill'`

- [ ] **Step 3: Write minimal implementation**

Add `from datetime import datetime` to imports, and append:

```python
def apply_skill(paths: Paths, name: str, targets: list[str], dry_run: bool = False) -> list[str]:
    src = paths.repo_skills / name
    src_hash = skill_hash(src)
    changes: list[str] = []
    for h in HARNESSES:
        if h not in targets:
            continue
        dst = paths.harness_skills[h] / name
        if dst.is_dir() and skill_hash(dst) == src_hash:
            continue
        changes.append(f"{name} -> {h}")
        if dry_run:
            continue
        if dst.exists():
            backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / h / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dst, backup)
        copy_skill(src, dst)
    return changes


def apply_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest)
    changes: list[str] = []
    for name, cfg in sorted(man["skills"].items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        changes += apply_skill(paths, name, targets, dry_run)
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_harness_sync.py`
Expected: all `PASS`, exit 0.

> Note: if two `apply_skill` calls land in the same second, backup timestamps
> collide. `copytree` into an existing dir raises — acceptable for v1 (one
> apply run per invocation). If it bites, switch the timestamp to
> `%Y%m%dT%H%M%S_%f`. Tracked as a known ceiling, not fixed now.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add apply with backup, idempotency and dry-run

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: CLI wiring (status / adopt / apply)

**Files:**
- Modify: `harness_sync.py`
- Test: manual smoke (no unit test for the interactive prompt loop)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `cmd_status(paths)`, `cmd_adopt(paths)`, `cmd_apply(paths, dry_run)`, `main(argv=None)`
  - `adopt_skill` is the testable core; `cmd_adopt` is the thin interactive wrapper.

- [ ] **Step 1: Write the implementation**

Append to `harness_sync.py`:

```python
import argparse


def cmd_status(paths: Paths) -> None:
    rows = compute_states(paths)
    print(f"{'SKILL':32} {'REPO':5} {'CLAUDE':10} {'CODEX':10}")
    for r in rows:
        print(f"{r['name']:32} {'yes' if r['repo'] else 'no':5} {r['claude']:10} {r['codex']:10}")


def _prompt(msg: str, choices: list[str]) -> str:
    joined = "/".join(choices)
    while True:
        ans = input(f"{msg} [{joined}]: ").strip().lower()
        if ans in choices:
            return ans


def cmd_adopt(paths: Paths) -> None:
    for row in compute_states(paths):
        name = row["name"]
        available = [h for h in HARNESSES if row[h] in ("untracked", "drift")]
        if not available:
            continue
        status = ", ".join(f"{h}:{row[h]}" for h in HARNESSES)
        print(f"\nSkill: {name}  ({status})")
        if input("  adopt? [y/N]: ").strip().lower() != "y":
            continue
        source = available[0] if len(available) == 1 else _prompt("  source", available)
        choice = _prompt("  targets", ["claude", "codex", "both", "ignore"])
        targets = list(HARNESSES) if choice == "both" else [choice]
        adopt_skill(paths, name, source, targets)
        print(f"  adopted {name} from {source} -> {targets}")


def cmd_apply(paths: Paths, dry_run: bool) -> None:
    changes = apply_all(paths, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    if not changes:
        print("nothing to do")
        return
    for c in changes:
        print(f"{prefix}{c}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-sync")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show skill states across harnesses")
    sub.add_parser("adopt", help="interactively import skills into the repo")
    ap = sub.add_parser("apply", help="push manifest skills to harnesses")
    ap.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    paths = resolve_paths(Path(__file__).resolve().parent)
    if args.cmd == "status":
        cmd_status(paths)
    elif args.cmd == "adopt":
        cmd_adopt(paths)
    elif args.cmd == "apply":
        cmd_apply(paths, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-test the CLI**

Run: `python harness_sync.py status`
Expected: a table listing real skills from `~/.claude/skills` and `~/.codex/skills`, most rows showing `repo=no`, `claude=untracked`, `codex=untracked` (repo `skills/` is still empty).

Run: `python harness_sync.py apply --dry-run`
Expected: `nothing to do` (empty manifest).

- [ ] **Step 3: Verify the full test suite still passes**

Run: `python test_harness_sync.py`
Expected: all `PASS`, exit 0.

- [ ] **Step 4: Commit**

```bash
git add harness_sync.py
git commit -m "feat: add status/adopt/apply CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Repo layout → Task 0 + files created across tasks ✓
- State model (`synced`/`drift`/`untracked`/`absent`) → Task 3 ✓
- `status` → Task 6 ✓
- `adopt` (interactive + non-interactive core) → Task 4 (core) + Task 6 (wrapper) ✓
- `apply` (idempotent, dry-run, backup, never deletes) → Task 5 ✓
- Manifest schema → Task 2 + Task 4 ✓
- Env-var path resolution (`CLAUDE_CONFIG_DIR`/`CODEX_HOME`) → Task 1 ✓
- Testing strategy (stdlib, tempdir, adopt→apply, idempotent, untracked untouched) → Tasks 1–5 ✓
- Non-goals (MCP, instructions, pruning, two-way) → not implemented, as intended ✓

**Placeholder scan:** No TBD/TODO; all code steps contain complete runnable code. ✓

**Type consistency:** `Paths`, `HARNESSES`, `skill_hash`, `scan`, `compute_states`, `copy_skill`, `adopt_skill`, `apply_skill`, `apply_all` names/signatures are consistent across tasks and tests. The `_paths_in` test helper matches the `Paths` dataclass fields. ✓
