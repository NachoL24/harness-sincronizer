# N Configurable Harnesses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `HARNESSES = ("claude", "codex")` model with a configurable `harnesses.json` registry so multiple Claude accounts and Codex can be sync targets at once.

**Architecture:** A registry file maps each harness name to a base config dir; the skills path is derived as `<base>/skills`. All pure functions (`compute_states`, `apply_skill`, `apply_all`) and the CLI iterate the registry instead of a fixed tuple. Absent registry falls back to today's env-based `claude`/`codex` defaults. New `harness add/remove/list` commands manage the registry.

**Tech Stack:** Python 3.11+ standard library only. Tests via `python3 test_harness_sync.py`.

## Global Constraints

- Python **3.11+**, **standard library only**. No dependencies.
- Registry file: `<repo>/harnesses.json`, shape `{"harnesses": {"<name>": {"base": "<dir>"}}}`. `~` expanded. No `type` field yet.
- **Registry absent** → defaults `claude` → `$CLAUDE_CONFIG_DIR` or `~/.claude`, `codex` → `$CODEX_HOME` or `~/.codex`.
- **Registry present** → it fully defines harnesses; env vars are NOT consulted.
- Manifest schema unchanged; `targets` reference registered harness names. Unknown target → warn on stderr + skip, never crash.
- Invalid `harnesses.json` → clear error, no silent fallback.
- `harness add` with no registry file → seed file with current effective defaults + the new entry.
- All code, comments, commit messages in English. Commit messages end with the Co-Authored-By trailer.
- Existing tests must stay green after every task.

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch from main**

```bash
cd /Users/nacho/Documents/harness-sincronizer
git checkout main
git checkout -b feature/n-harnesses
```

- [ ] **Step 2: Commit the approved spec**

```bash
git add docs/superpowers/specs/2026-06-30-n-harnesses-design.md docs/superpowers/plans/2026-06-30-n-harnesses.md
git commit -m "docs: add N-harnesses spec and plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: Registry loading + `resolve_paths` refactor

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Produces:
  - `default_harnesses() -> dict[str, Path]` — `{"claude": <dir>, "codex": <dir>}` from env/defaults
  - `registry_path(repo_root: Path) -> Path` — `repo_root/"harnesses.json"`
  - `load_harnesses(repo_root: Path) -> dict[str, Path]` — name → expanded base dir; defaults if registry absent; raises `json.JSONDecodeError` on invalid JSON
  - `Paths` gains a `registry: Path` field
  - `resolve_paths` builds `harness_skills` from the registry

- [ ] **Step 1: Write the failing tests**

Append before the `if __name__` runner in `test_harness_sync.py`:

```python
def test_load_harnesses_absent_uses_env_defaults():
    with tempfile.TemporaryDirectory() as t:
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(t) / "cc")
        os.environ["CODEX_HOME"] = str(Path(t) / "cx")
        try:
            h = hs.load_harnesses(Path(t) / "repo")
            assert h == {"claude": Path(t) / "cc", "codex": Path(t) / "cx"}
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
            del os.environ["CODEX_HOME"]


def test_load_harnesses_present_parses_and_expands():
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t) / "repo"
        repo.mkdir()
        (repo / "harnesses.json").write_text(
            '{"harnesses": {"work": {"base": "~/wk"}, "codex": {"base": "/abs/cx"}}}'
        )
        h = hs.load_harnesses(repo)
        assert h["work"] == Path.home() / "wk"
        assert h["codex"] == Path("/abs/cx")
        assert list(h) == ["work", "codex"]  # insertion order preserved


def test_load_harnesses_invalid_json_raises():
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t) / "repo"
        repo.mkdir()
        (repo / "harnesses.json").write_text("{not valid")
        raised = False
        try:
            hs.load_harnesses(repo)
        except json.JSONDecodeError:
            raised = True
        assert raised
```

Add `import json` at the top of the test file (needed for the exception type):

```python
import json
import os
import tempfile
```

- [ ] **Step 2: Update the `_paths_in` test helper for the new `registry` field**

Change `_paths_in` to include `registry`:

```python
def _paths_in(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={"claude": t / "cc" / "skills", "codex": t / "cx" / "skills"},
    )
```

- [ ] **Step 3: Run tests to verify the new ones fail**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'load_harnesses'`

- [ ] **Step 4: Implement**

In `harness_sync.py`, add `import sys` to the imports (used later; add now). Replace the `HARNESSES`/`harness_skill_dir` block. Keep the `HARNESSES` constant for now (still used by `compute_states`/`apply`/CLI until later tasks) but delete `harness_skill_dir`:

```python
HARNESSES = ("claude", "codex")


def default_harnesses() -> dict[str, Path]:
    return {
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")),
        "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    }


def registry_path(repo_root: Path) -> Path:
    return repo_root / "harnesses.json"


def load_harnesses(repo_root: Path) -> dict[str, Path]:
    path = registry_path(repo_root)
    if not path.exists():
        return default_harnesses()
    data = json.loads(path.read_text())
    return {name: Path(cfg["base"]).expanduser() for name, cfg in data["harnesses"].items()}
```

Add the `registry` field to `Paths`:

```python
@dataclass(frozen=True)
class Paths:
    repo_skills: Path
    manifest: Path
    backups: Path
    registry: Path
    harness_skills: dict[str, Path]
```

Replace `resolve_paths`:

```python
def resolve_paths(repo_root: Path) -> Paths:
    bases = load_harnesses(repo_root)
    return Paths(
        repo_skills=repo_root / "skills",
        manifest=repo_root / "manifest.json",
        backups=repo_root / ".harness-sync-backups",
        registry=registry_path(repo_root),
        harness_skills={name: base / "skills" for name, base in bases.items()},
    )
```

- [ ] **Step 5: Run tests to verify all pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS` (existing tests unchanged behavior + 3 new).

- [ ] **Step 6: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add harness registry loading with env fallback

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Generalize `compute_states` to N harnesses

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `scan`, `Paths.harness_skills`.
- Produces: `compute_states(paths)` iterates `list(paths.harness_skills)`; each row has one key per registered harness name.

- [ ] **Step 1: Write the failing test (3 harnesses)**

Append:

```python
def _paths_in_3(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={
            "claude": t / "cc" / "skills",
            "claude-perso": t / "cp" / "skills",
            "codex": t / "cx" / "skills",
        },
    )


def test_compute_states_three_harnesses():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in_3(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})       # synced
        _make_skill(p.harness_skills["claude-perso"], "alpha", {"SKILL.md": "OLD"})  # drift
        # codex: absent for alpha
        rows = {r["name"]: r for r in hs.compute_states(p)}
        assert rows["alpha"]["claude"] == "synced"
        assert rows["alpha"]["claude-perso"] == "drift"
        assert rows["alpha"]["codex"] == "absent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `KeyError: 'claude-perso'` (current `compute_states` iterates the fixed `HARNESSES`, so the row lacks that key).

- [ ] **Step 3: Implement**

Replace `compute_states`:

```python
def compute_states(paths: Paths) -> list[dict]:
    repo = scan(paths.repo_skills)
    names = list(paths.harness_skills)
    harness = {h: scan(paths.harness_skills[h]) for h in names}
    all_names = set(repo) | {n for m in harness.values() for n in m}
    rows = []
    for name in sorted(all_names):
        r = repo.get(name)
        row = {"name": name, "repo": r is not None}
        for h in names:
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

- [ ] **Step 4: Run tests to verify all pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS` (existing 2-harness tests + new 3-harness).

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: generalize compute_states to N harnesses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Generalize `apply` + unknown-target warning

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `Paths.harness_skills`, `skill_hash`, `copy_skill`, `load_manifest`.
- Produces:
  - `apply_skill(paths, name, targets, dry_run=False) -> list[str]` — iterates `targets`, skips any name not in `harness_skills`.
  - `apply_all(paths, dry_run=False) -> list[str]` — warns on stderr for unknown targets, still applies known ones.

- [ ] **Step 1: Write the failing test**

Append (`io`/`contextlib` are stdlib):

```python
import contextlib
import io


def test_apply_all_warns_and_skips_unknown_target():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in_3(t)
        _make_skill(p.repo_skills, "beta", {"SKILL.md": "b"})
        hs.save_manifest(p.manifest, {"skills": {
            "beta": {"targets": ["claude-perso", "ghost"]},
        }})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = hs.apply_all(p)
        assert changes == ["beta -> claude-perso"]           # known target applied
        assert (p.harness_skills["claude-perso"] / "beta").exists()
        assert "ghost" in err.getvalue()                     # unknown target warned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 test_harness_sync.py`
Expected: FAIL — current `apply_skill` iterates `HARNESSES`, so `claude-perso` is never applied (`changes` is `[]`).

- [ ] **Step 3: Implement**

Replace `apply_skill` and `apply_all` (drop the `HARNESSES` iteration):

```python
def apply_skill(paths: Paths, name: str, targets: list[str], dry_run: bool = False) -> list[str]:
    src = paths.repo_skills / name
    src_hash = skill_hash(src)
    changes: list[str] = []
    for h in targets:
        if h not in paths.harness_skills:
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
        for t in targets:
            if t not in paths.harness_skills:
                print(f"warning: skill '{name}' targets unknown harness '{t}' — skipping", file=sys.stderr)
        changes += apply_skill(paths, name, targets, dry_run)
    return changes
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS` (existing apply tests use `claude`/`codex` targets that are in `harness_skills`, so behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: generalize apply to N harnesses with unknown-target warning

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Registry management functions

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Produces:
  - `load_registry(path) -> dict` — `{"harnesses": {}}` if absent
  - `save_registry(path, data)` — pretty JSON, insertion order preserved (no sort)
  - `harness_add(paths, name, base)` — seed with defaults if file absent, then add/update
  - `harness_remove(paths, name)` — remove entry

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_harness_add_seeds_defaults_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        p.registry.parent.mkdir(parents=True, exist_ok=True)
        assert not p.registry.exists()
        hs.harness_add(p, "claude-perso", "~/.claude-perso")
        data = hs.load_registry(p.registry)
        # defaults preserved + new entry present
        assert set(data["harnesses"]) == {"claude", "codex", "claude-perso"}
        assert data["harnesses"]["claude-perso"] == {"base": "~/.claude-perso"}


def test_harness_remove_deletes_entry():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        p.registry.parent.mkdir(parents=True, exist_ok=True)
        hs.save_registry(p.registry, {"harnesses": {
            "claude": {"base": "~/.claude"}, "codex": {"base": "~/.codex"},
        }})
        hs.harness_remove(p, "codex")
        data = hs.load_registry(p.registry)
        assert set(data["harnesses"]) == {"claude"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'harness_add'`

- [ ] **Step 3: Implement**

Append to `harness_sync.py`:

```python
def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"harnesses": {}}
    return json.loads(path.read_text())


def save_registry(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def harness_add(paths: Paths, name: str, base: str) -> None:
    if not paths.registry.exists():
        data = {"harnesses": {n: {"base": str(b)} for n, b in default_harnesses().items()}}
    else:
        data = load_registry(paths.registry)
    data["harnesses"][name] = {"base": base}
    save_registry(paths.registry, data)


def harness_remove(paths: Paths, name: str) -> None:
    data = load_registry(paths.registry)
    data["harnesses"].pop(name, None)
    save_registry(paths.registry, data)
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add harness registry add/remove/load/save

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: CLI — dynamic status, N-target adopt, `harness` commands

**Files:**
- Modify: `harness_sync.py`
- Test: manual smoke (interactive prompt loop has no unit test)

**Interfaces:**
- Consumes: everything above.
- Produces: dynamic `cmd_status`; `_prompt_targets`; N-target `cmd_adopt`; `cmd_harness_list`; `harness add/remove/list` wiring; `HARNESSES` constant removed.

- [ ] **Step 1: Replace the CLI section**

Replace `cmd_status`, `cmd_adopt`, and `main` (keep `_prompt` as-is), and **delete the `HARNESSES = ("claude", "codex")` constant** (no remaining consumers). New code:

```python
def cmd_status(paths: Paths) -> None:
    names = list(paths.harness_skills)
    rows = compute_states(paths)
    w = {h: max(len(h), 10) for h in names}
    print(f"{'SKILL':32} {'REPO':5} " + " ".join(f"{h:{w[h]}}" for h in names))
    for r in rows:
        cells = " ".join(f"{r[h]:{w[h]}}" for h in names)
        print(f"{r['name']:32} {'yes' if r['repo'] else 'no':5} " + cells)


def _prompt_targets(names: list[str]) -> list[str]:
    while True:
        raw = input(f"  targets (comma-separated from {names}, or 'all'/'ignore'): ").strip().lower()
        if raw == "ignore":
            return ["ignore"]
        if raw == "all":
            return list(names)
        chosen = [x.strip() for x in raw.split(",") if x.strip()]
        if chosen and all(c in names for c in chosen):
            return chosen


def cmd_adopt(paths: Paths) -> None:
    names = list(paths.harness_skills)
    for row in compute_states(paths):
        name = row["name"]
        available = [h for h in names if row[h] in ("untracked", "drift")]
        if not available:
            continue
        status = ", ".join(f"{h}:{row[h]}" for h in names)
        print(f"\nSkill: {name}  ({status})")
        if input("  adopt? [y/N]: ").strip().lower() != "y":
            continue
        source = available[0] if len(available) == 1 else _prompt("  source", available)
        targets = _prompt_targets(names)
        adopt_skill(paths, name, source, targets)
        print(f"  adopted {name} from {source} -> {targets}")


def cmd_harness_list(paths: Paths) -> None:
    for name, skills in paths.harness_skills.items():
        print(f"{name:16} base={skills.parent}  skills={skills}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-sync")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show skill states across harnesses")
    sub.add_parser("adopt", help="interactively import skills into the repo")
    ap = sub.add_parser("apply", help="push manifest skills to harnesses")
    ap.add_argument("--dry-run", action="store_true")
    hp = sub.add_parser("harness", help="manage the harness registry")
    hsub = hp.add_subparsers(dest="haction", required=True)
    hsub.add_parser("list", help="list registered harnesses")
    ha = hsub.add_parser("add", help="add/update a harness")
    ha.add_argument("name")
    ha.add_argument("base")
    hr = hsub.add_parser("remove", help="remove a harness")
    hr.add_argument("name")
    args = parser.parse_args(argv)

    try:
        paths = resolve_paths(Path(__file__).resolve().parent)
    except json.JSONDecodeError as e:
        print(f"error: invalid harnesses.json: {e}", file=sys.stderr)
        return 2

    if args.cmd == "status":
        cmd_status(paths)
    elif args.cmd == "adopt":
        cmd_adopt(paths)
    elif args.cmd == "apply":
        cmd_apply(paths, args.dry_run)
    elif args.cmd == "harness":
        if args.haction == "list":
            cmd_harness_list(paths)
        elif args.haction == "add":
            harness_add(paths, args.name, args.base)
            print(f"added harness '{args.name}' -> {args.base}")
        elif args.haction == "remove":
            harness_remove(paths, args.name)
            print(f"removed harness '{args.name}'")
    return 0
```

(`cmd_apply` is unchanged from v1 and stays as-is.)

- [ ] **Step 2: Verify the full unit suite still passes**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`, exit 0.

- [ ] **Step 3: Smoke-test the new CLI (no registry yet → defaults)**

Run: `python3 harness_sync.py harness list`
Expected: two lines, `claude` and `codex`, with their default base/skills paths.

Run: `python3 harness_sync.py status`
Expected: the usual two-column (CLAUDE/CODEX) table — unchanged behavior with no registry.

- [ ] **Step 4: Smoke-test the registry round-trip in a temp repo**

```bash
tmp=$(mktemp -d)
cp harness_sync.py "$tmp/"
cd "$tmp"
python3 harness_sync.py harness add claude-perso ~/.claude-perso
python3 harness_sync.py harness list      # expect claude, codex, claude-perso
python3 harness_sync.py status            # expect 3 columns
python3 harness_sync.py harness remove codex
python3 harness_sync.py harness list      # expect claude, claude-perso
cd - >/dev/null
rm -rf "$tmp"
```

Expected: 3 columns after add; `claude-perso` uses your real perso skills; removing `codex` drops its column.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py
git commit -m "feat: dynamic N-harness CLI and harness registry commands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Docs

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Update `README.md`**

- Add a **Harnesses** section documenting `harnesses.json`, the base-dir shape, the absent-registry env defaults, that a present registry ignores env vars, and the `harness list/add/remove` commands.
- Update the "Two Claude accounts" section: instead of the per-run `CLAUDE_CONFIG_DIR=...` trick, show:
  ```bash
  python3 harness_sync.py harness add claude-perso ~/.claude-perso
  python3 harness_sync.py status   # claude, claude-perso and codex as columns
  ```
- Note the env-var override still works when no `harnesses.json` exists.

- [ ] **Step 2: Update `CLAUDE.md`**

- In "Harness paths", document the registry: absent → env defaults; present → authoritative, env ignored.
- Add `harness list/add/remove` to the Commands section.
- Move "N configurable harnesses" out of Non-goals (now implemented).

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document harness registry and N-harness commands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Registry file + base-dir shape → Task 1 ✓
- Absent → env defaults; present → authoritative, env ignored → Task 1 (`load_harnesses`) ✓
- Invalid JSON → clear error → Task 1 (raises) + Task 5 (`main` catch) ✓
- `harness list/add/remove` + seeding rule → Task 4 (core) + Task 5 (CLI) ✓
- `compute_states` N harnesses → Task 2 ✓
- Dynamic status columns → Task 5 ✓
- `adopt` N-target multi-select, `both` removed → Task 5 ✓
- `apply` N harnesses + unknown-target warn/skip → Task 3 ✓
- Manifest schema unchanged, existing targets valid → covered (no schema change; existing tests green) ✓
- Base dir absent → graceful `absent` → inherited from `scan` (unchanged) ✓
- Testing: load present/absent/invalid, 3-harness states, add seeding, remove, unknown target → Tasks 1–4 ✓
- Docs → Task 6 ✓

**Placeholder scan:** No TBD/TODO; all code steps contain complete code. Task 6 doc steps are descriptive edits to prose files (acceptable — no code logic). ✓

**Type consistency:** `default_harnesses`, `registry_path`, `load_harnesses`, `load_registry`, `save_registry`, `harness_add`, `harness_remove`, `compute_states`, `apply_skill`, `apply_all`, `cmd_harness_list`, `_prompt_targets` names/signatures consistent across tasks and tests. `Paths` gains `registry` in Task 1 and both `_paths_in` helpers include it. ✓
