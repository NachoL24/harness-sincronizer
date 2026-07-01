# Plugin Skills → Codex Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover skills bundled inside Claude plugins and adopt them (whole-plugin at a time) into the repo so they sync to Codex like standalone skills.

**Architecture:** Discovery reads each harness's `<base>/plugins/installed_plugins.json` for active plugin install paths, then collects `<installPath>/skills/*/`. A new `plugins list/adopt` command group drives it; `adopt` imports every skill of a chosen plugin via a shared `import_skill` helper (also used by the existing `adopt`). Adopted skills become normal repo/manifest entries.

**Tech Stack:** Python 3.11+ standard library only. Tests via `python3 test_harness_sync.py`.

## Global Constraints

- Python **3.11+**, **standard library only**.
- Discovery source = `installed_plugins.json` (`version: 2`, `plugins: {"<key>": [{"installPath","version"}]}`), NOT an rglob over the cache.
- Plugins are per-harness: `<base>/plugins/`, where `<base>` is `paths.harness_skills[h].parent`.
- Only `<installPath>/skills/*/` (dirs containing `SKILL.md`) are discovered. Nested/non-canonical locations are out of scope.
- **Tolerant discovery:** missing/invalid `installed_plugins.json` or absent `installPath` → that harness yields no plugins, never crash.
- **Unit of adoption = whole plugin.** No skill-by-skill prompting within a plugin.
- **Collision:** a plugin skill whose name already exists in repo `skills/` is skipped with a warning; siblings still adopt. Never overwrite.
- Repo skill names stay flat (no plugin namespacing).
- Manifest schema unchanged; adopted plugin skills are normal `{"targets": [...]}` entries.
- All code, comments, commit messages in English. Commit messages end with the Co-Authored-By trailer.
- Existing tests must stay green after every task.

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch from main**

```bash
cd /Users/nacho/Documents/harness-sincronizer
git checkout main
git checkout -b feature/plugin-skills
```

- [ ] **Step 2: Commit the approved spec and plan**

```bash
git add docs/superpowers/specs/2026-07-01-plugin-skills-design.md docs/superpowers/plans/2026-07-01-plugin-skills.md
git commit -m "docs: add plugin-skills spec and plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: Discovery (`read_installed_plugins` + `discover_plugins`)

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Produces:
  - `read_installed_plugins(plugins_dir: Path) -> list[tuple[str, Path]]` — `(plugin_key, install_path)` for active plugins; `[]` if file missing/invalid.
  - `discover_plugins(paths: Paths) -> list[dict]` — one dict per plugin with skills: `{"plugin": str, "harness": str, "skills": list[tuple[str, Path]]}` (skills sorted by name; only dirs containing `SKILL.md`).

- [ ] **Step 1: Add a test helper for fake plugins**

In `test_harness_sync.py`, add near the other helpers:

```python
def _make_plugin(harness_base: Path, plugin_key: str, install_path: Path, skill_names: list[str]) -> None:
    for s in skill_names:
        d = install_path / "skills" / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {s}")
    pj = harness_base / "plugins" / "installed_plugins.json"
    pj.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "plugins": {}}
    if pj.exists():
        data = json.loads(pj.read_text())
    data["plugins"].setdefault(plugin_key, []).append(
        {"installPath": str(install_path), "version": "1.0.0"}
    )
    pj.write_text(json.dumps(data))
```

- [ ] **Step 2: Write the failing tests**

Append before the runner:

```python
def test_read_installed_plugins_tolerant():
    with tempfile.TemporaryDirectory() as t:
        assert hs.read_installed_plugins(Path(t) / "nope") == []
        pdir = Path(t) / "plugins"
        pdir.mkdir()
        (pdir / "installed_plugins.json").write_text("{bad")
        assert hs.read_installed_plugins(pdir) == []


def test_read_installed_plugins_parses_active():
    with tempfile.TemporaryDirectory() as t:
        pdir = Path(t) / "plugins"
        pdir.mkdir()
        (pdir / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
            "sp@mkt": [{"installPath": "/x/sp/1.0", "version": "1.0"}]}}))
        assert hs.read_installed_plugins(pdir) == [("sp@mkt", Path("/x/sp/1.0"))]


def test_discover_plugins_finds_skills_tagged():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)  # claude base = t/cc, codex base = t/cx
        install = t / "cc" / "plugins" / "cache" / "sp" / "1.0"
        _make_plugin(t / "cc", "sp@mkt", install, ["brainstorming", "tdd"])
        plugins = hs.discover_plugins(p)
        assert len(plugins) == 1
        assert plugins[0]["plugin"] == "sp@mkt"
        assert plugins[0]["harness"] == "claude"
        assert sorted(n for n, _ in plugins[0]["skills"]) == ["brainstorming", "tdd"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'read_installed_plugins'`

- [ ] **Step 4: Implement**

Add to `harness_sync.py` (after `scan`):

```python
def read_installed_plugins(plugins_dir: Path) -> list[tuple[str, Path]]:
    f = plugins_dir / "installed_plugins.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text())
    except json.JSONDecodeError:
        return []
    result: list[tuple[str, Path]] = []
    for key, entries in data.get("plugins", {}).items():
        for entry in entries:
            install_path = entry.get("installPath")
            if install_path:
                result.append((key, Path(install_path)))
    return result


def discover_plugins(paths: Paths) -> list[dict]:
    plugins: list[dict] = []
    for harness, skills_dir in paths.harness_skills.items():
        plugins_dir = skills_dir.parent / "plugins"
        for plugin_key, install_path in read_installed_plugins(plugins_dir):
            sdir = install_path / "skills"
            if not sdir.is_dir():
                continue
            skills = [
                (d.name, d)
                for d in sorted(sdir.iterdir())
                if d.is_dir() and (d / "SKILL.md").exists()
            ]
            if skills:
                plugins.append({"plugin": plugin_key, "harness": harness, "skills": skills})
    return plugins
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

- [ ] **Step 6: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: discover plugin-bundled skills via installed_plugins.json

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `import_skill` refactor + `adopt_plugin`

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Produces:
  - `import_skill(paths: Paths, name: str, src_dir: Path, targets: list[str]) -> None` — copy `src_dir` → repo `skills/<name>`, record manifest entry.
  - `adopt_plugin(paths: Paths, plugin: dict, targets: list[str]) -> tuple[list[str], list[str]]` — returns `(adopted, skipped)`; skips names already in repo.
- `adopt_skill` is refactored to delegate to `import_skill` (signature unchanged).

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_import_skill_copies_and_records():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        src = t / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("x")
        hs.import_skill(p, "foo", src, ["codex"])
        assert (p.repo_skills / "foo" / "SKILL.md").read_text() == "x"
        assert hs.load_manifest(p.manifest)["skills"]["foo"] == {"targets": ["codex"]}


def test_adopt_plugin_imports_all_and_skips_collision():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "dup", {"SKILL.md": "existing"})  # collision
        install = t / "cc" / "plugins" / "sp" / "1.0"
        _make_plugin(t / "cc", "sp@mkt", install, ["fresh", "dup"])
        plugin = hs.discover_plugins(p)[0]
        adopted, skipped = hs.adopt_plugin(p, plugin, ["codex"])
        assert adopted == ["fresh"]
        assert skipped == ["dup"]
        assert (p.repo_skills / "fresh" / "SKILL.md").exists()
        assert (p.repo_skills / "dup" / "SKILL.md").read_text() == "existing"  # untouched
        man = hs.load_manifest(p.manifest)
        assert man["skills"]["fresh"] == {"targets": ["codex"]}
        assert "dup" not in man["skills"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'import_skill'`

- [ ] **Step 3: Implement**

Replace the existing `adopt_skill` with the refactor and add the two new functions:

```python
def import_skill(paths: Paths, name: str, src_dir: Path, targets: list[str]) -> None:
    copy_skill(src_dir, paths.repo_skills / name)
    man = load_manifest(paths.manifest)
    man["skills"][name] = {"targets": list(targets)}
    save_manifest(paths.manifest, man)


def adopt_skill(paths: Paths, name: str, source_harness: str, targets: list[str]) -> None:
    import_skill(paths, name, paths.harness_skills[source_harness] / name, targets)


def adopt_plugin(paths: Paths, plugin: dict, targets: list[str]) -> tuple[list[str], list[str]]:
    adopted: list[str] = []
    skipped: list[str] = []
    for name, src in plugin["skills"]:
        if (paths.repo_skills / name).exists():
            skipped.append(name)
            continue
        import_skill(paths, name, src, targets)
        adopted.append(name)
    return adopted, skipped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS` (existing `test_adopt_skill_imports_and_records` still passes — `adopt_skill` behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add import_skill and whole-plugin adopt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: CLI — `plugins list` / `plugins adopt`

**Files:**
- Modify: `harness_sync.py`
- Test: manual smoke (interactive adopt loop has no unit test)

**Interfaces:**
- Consumes: `discover_plugins`, `scan`, `adopt_plugin`, `_prompt_targets`.
- Produces: `cmd_plugins_list(paths)`, `cmd_plugins_adopt(paths)`, and `plugins` CLI wiring.

- [ ] **Step 1: Add the command functions**

Add after `cmd_harness_list`:

```python
def cmd_plugins_list(paths: Paths) -> None:
    plugins = discover_plugins(paths)
    if not plugins:
        print("no plugins found")
        return
    repo = set(scan(paths.repo_skills))
    print(f"{'PLUGIN':40} {'HARNESS':14} {'SKILLS':7} {'IN-REPO':7}")
    for p in plugins:
        names = [n for n, _ in p["skills"]]
        in_repo = sum(1 for n in names if n in repo)
        print(f"{p['plugin']:40} {p['harness']:14} {len(names):<7} {in_repo:<7}")


def cmd_plugins_adopt(paths: Paths) -> None:
    registered = list(paths.harness_skills)
    for p in discover_plugins(paths):
        skills = [n for n, _ in p["skills"]]
        print(f"\nPlugin: {p['plugin']}  ({len(skills)} skills, from {p['harness']})")
        if input("  adopt whole plugin? [y/N]: ").strip().lower() != "y":
            continue
        targets = _prompt_targets(registered)
        adopted, skipped = adopt_plugin(paths, p, targets)
        msg = f"  adopted {len(adopted)} skills -> {targets}"
        if skipped:
            msg += f"; skipped (name already in repo): {skipped}"
        print(msg)
```

- [ ] **Step 2: Wire the `plugins` subcommand in `main`**

In `main`, after the `harness` subparser block and before `args = parser.parse_args(argv)`, add:

```python
    pp = sub.add_parser("plugins", help="discover and adopt plugin-bundled skills")
    psub = pp.add_subparsers(dest="paction", required=True)
    psub.add_parser("list", help="list discovered plugin skills")
    psub.add_parser("adopt", help="interactively adopt whole plugins into the repo")
```

And in the dispatch chain, after the `harness` branch, add:

```python
    elif args.cmd == "plugins":
        if args.paction == "list":
            cmd_plugins_list(paths)
        elif args.paction == "adopt":
            cmd_plugins_adopt(paths)
```

- [ ] **Step 3: Verify the unit suite still passes**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

- [ ] **Step 4: Smoke-test against real plugins**

Run: `python3 harness_sync.py plugins list`
Expected: a table of real plugins (e.g. `superpowers@claude-plugins-official`) with their skill counts, tagged by harness. `IN-REPO` reflects your repo `skills/`.

Run (then answer `n` to every prompt to avoid mutating anything):
`python3 harness_sync.py plugins adopt`
Expected: it walks plugins one by one asking `adopt whole plugin? [y/N]`.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py
git commit -m "feat: add plugins list/adopt CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Docs

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `AGENTS.md`

- [ ] **Step 1: Update `README.md`**

Add a **Plugin skills** subsection (near Usage) explaining:
- most skills live inside Claude plugins; `plugins list` discovers them per harness via `installed_plugins.json`.
- `plugins adopt` imports a whole plugin's skills into the repo (interactive, per plugin) and records manifest targets, so `apply` pushes them to Codex.
- collisions with existing repo skills are skipped with a warning.
- Example:
  ```bash
  python3 harness_sync.py plugins list
  python3 harness_sync.py plugins adopt
  python3 harness_sync.py apply
  ```

- [ ] **Step 2: Update `CLAUDE.md`**

- Add `python3 harness_sync.py plugins list|adopt` to the Commands section with a one-line description (whole-plugin unit; discovers via `installed_plugins.json`; skips repo-name collisions).

- [ ] **Step 3: Re-sync `AGENTS.md` and commit**

```bash
cd /Users/nacho/Documents/harness-sincronizer
cp CLAUDE.md AGENTS.md
git add README.md CLAUDE.md AGENTS.md
git commit -m "docs: document plugins list/adopt commands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Discovery via `installed_plugins.json`, per harness, `<installPath>/skills/` → Task 1 ✓
- Tolerant discovery (missing/invalid/absent) → Task 1 (`read_installed_plugins` guards, `discover_plugins` skips) ✓
- `plugins list` (PLUGIN/HARNESS/SKILLS/IN-REPO) → Task 3 ✓
- `plugins adopt` interactive, whole-plugin unit → Task 3 (+ `adopt_plugin` core in Task 2) ✓
- Shared `import_skill`, `adopt_skill` refactor, flat names → Task 2 ✓
- Collision skip-with-warning, no overwrite → Task 2 (`adopt_plugin`) + Task 3 (warning printed) ✓
- Manifest unchanged, normal entries → Task 2 ✓
- Reuse `apply` to push to Codex → inherited (no change to `apply`) ✓
- Testing (read tolerant/parse, discover tagged, import, adopt-all+collision) → Tasks 1–2 ✓
- Docs → Task 4 ✓

**Placeholder scan:** No TBD/TODO; code steps contain complete code. Task 4 doc steps are prose edits (acceptable). ✓

**Type consistency:** `read_installed_plugins`, `discover_plugins`, `import_skill`, `adopt_skill`, `adopt_plugin`, `cmd_plugins_list`, `cmd_plugins_adopt` names/signatures consistent across tasks and tests. `discover_plugins` returns dicts with keys `plugin`/`harness`/`skills`, used identically in `adopt_plugin` and the CLI. Test helper `_make_plugin` matches the `installed_plugins.json` shape the code reads. ✓
