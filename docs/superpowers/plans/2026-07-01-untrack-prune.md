# Untrack + Opt-in Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the tracking lifecycle: `untrack <skill>` removes a skill from repo+manifest (backed up), and `apply --prune` deletes de-targeted tracked skills from harnesses (opt-in, backed up), with matching TUI actions.

**Architecture:** Two new pure functions in `harness_sync.py` (`untrack_skill`, `prune_all`) plus a shared `backup_skill` helper extracted from `apply_skill`. CLI gains an `untrack` subcommand and an `--prune` flag on `apply`. The TUI gains a `u` binding on Status and a prune checkbox on Apply.

**Tech Stack:** Python 3.11+ stdlib core; textual only in `harness_tui.py`. Tests via `python3 test_harness_sync.py`.

## Global Constraints

- Untrack: remove manifest entry + back up repo copy to `.harness-sync-backups/<ts>/repo/<name>/` then delete `skills/<name>/`. **Never touches harnesses.** Unknown name → `KeyError` (CLI: message + exit 1).
- Prune: only manifest skills; `"ignore"` in targets → skipped entirely; harness `h` pruned only when `h not in targets` and the copy exists; backup before delete; foreign (unmanifested) skills never deleted.
- Prune change strings use `"<name> -x <harness>"` (distinct from push `"->"`).
- `--prune` is off by default; `--dry-run` respected by both operations.
- Core stays stdlib-only; all code/comments/commits in English; Co-Authored-By trailer.
- Existing tests stay green after every task.

---

### Task 0: Branch

- [ ] **Step 1: Branch from main and commit spec+plan**

```bash
cd /Users/nacho/Documents/harness-sincronizer
git checkout main
git checkout -b feature/untrack-prune
git add docs/superpowers/specs/2026-07-01-untrack-prune-design.md docs/superpowers/plans/2026-07-01-untrack-prune.md
git commit -m "docs: add untrack+prune spec and plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 1: `backup_skill` helper (refactor)

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py` (existing `test_apply_pushes_backs_up_and_is_idempotent` guards the refactor)

**Interfaces:**
- Produces: `backup_skill(paths: Paths, label: str, name: str, src: Path) -> None` — copies `src` to `backups/<ts>/<label>/<name>/`.

- [ ] **Step 1: Add the helper and refactor `apply_skill`**

Add after `copy_skill`:

```python
def backup_skill(paths: Paths, label: str, name: str, src: Path) -> None:
    backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / label / name
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, backup)
```

In `apply_skill`, replace the inline backup block:

```python
        if dst.exists():
            backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / h / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dst, backup)
```

with:

```python
        if dst.exists():
            backup_skill(paths, h, name, dst)
```

- [ ] **Step 2: Verify the suite still passes**

Run: `python3 test_harness_sync.py`
Expected: all `PASS` (backup behavior unchanged; existing apply test covers it).

- [ ] **Step 3: Commit**

```bash
git add harness_sync.py
git commit -m "refactor: extract backup_skill helper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `untrack_skill`

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `backup_skill`, `load_manifest`, `save_manifest`.
- Produces: `untrack_skill(paths: Paths, name: str) -> None`; raises `KeyError` when untracked.

- [ ] **Step 1: Write the failing tests**

Append before the runner:

```python
def test_untrack_removes_manifest_and_repo_with_backup():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["claude"]}}})

        hs.untrack_skill(p, "alpha")

        assert "alpha" not in hs.load_manifest(p.manifest)["skills"]
        assert not (p.repo_skills / "alpha").exists()                      # repo copy gone
        backups = list(p.backups.rglob("repo/alpha/SKILL.md"))
        assert backups and backups[0].read_text() == "v1"                  # backed up
        assert (p.harness_skills["claude"] / "alpha" / "SKILL.md").exists()  # harness untouched


def test_untrack_unknown_raises():
    with tempfile.TemporaryDirectory() as tmp:
        p = _paths_in(Path(tmp))
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        raised = False
        try:
            hs.untrack_skill(p, "ghost")
        except KeyError:
            raised = True
        assert raised
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'untrack_skill'`

- [ ] **Step 3: Implement**

Add after `adopt_plugin`:

```python
def untrack_skill(paths: Paths, name: str) -> None:
    man = load_manifest(paths.manifest)
    if name not in man["skills"]:
        raise KeyError(name)
    del man["skills"][name]
    save_manifest(paths.manifest, man)
    repo_dir = paths.repo_skills / name
    if repo_dir.is_dir():
        backup_skill(paths, "repo", name, repo_dir)
        shutil.rmtree(repo_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add untrack_skill (manifest+repo removal with backup)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `prune_all`

**Files:**
- Modify: `harness_sync.py`
- Test: `test_harness_sync.py`

**Interfaces:**
- Consumes: `load_manifest`, `backup_skill`, `Paths.harness_skills`.
- Produces: `prune_all(paths: Paths, dry_run: bool = False) -> list[str]` — `"<name> -x <harness>"` strings.

- [ ] **Step 1: Write the failing tests**

```python
def test_prune_removes_detargeted_with_backup():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "old"})
        _make_skill(p.harness_skills["codex"], "alpha", {"SKILL.md": "v1"})
        # alpha targeted only to codex -> claude copy is de-targeted
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["codex"]}}})

        changes = hs.prune_all(p)

        assert changes == ["alpha -x claude"]
        assert not (p.harness_skills["claude"] / "alpha").exists()
        assert (p.harness_skills["codex"] / "alpha").exists()              # targeted stays
        backups = list(p.backups.rglob("claude/alpha/SKILL.md"))
        assert backups and backups[0].read_text() == "old"


def test_prune_spares_ignore_and_foreign():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "kept", {"SKILL.md": "k"})
        _make_skill(p.harness_skills["claude"], "kept", {"SKILL.md": "k"})
        _make_skill(p.harness_skills["claude"], "foreign", {"SKILL.md": "f"})
        hs.save_manifest(p.manifest, {"skills": {"kept": {"targets": ["ignore"]}}})

        changes = hs.prune_all(p)

        assert changes == []
        assert (p.harness_skills["claude"] / "kept").exists()      # ignore -> untouched
        assert (p.harness_skills["claude"] / "foreign").exists()   # unmanifested -> untouched


def test_prune_dry_run_deletes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["codex"]}}})

        changes = hs.prune_all(p, dry_run=True)

        assert changes == ["alpha -x claude"]
        assert (p.harness_skills["claude"] / "alpha").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'prune_all'`

- [ ] **Step 3: Implement**

Add after `apply_all`:

```python
def prune_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest)
    changes: list[str] = []
    for name, cfg in sorted(man["skills"].items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        for h, skills_dir in paths.harness_skills.items():
            if h in targets:
                continue
            dst = skills_dir / name
            if not dst.is_dir():
                continue
            changes.append(f"{name} -x {h}")
            if dry_run:
                continue
            backup_skill(paths, h, name, dst)
            shutil.rmtree(dst)
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

- [ ] **Step 5: Commit**

```bash
git add harness_sync.py test_harness_sync.py
git commit -m "feat: add prune_all (opt-in removal of de-targeted skills)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: CLI — `untrack` + `apply --prune`

**Files:**
- Modify: `harness_sync.py` (`cmd_apply`, `main`)

**Interfaces:**
- Consumes: `untrack_skill`, `prune_all`.
- Produces: `cmd_apply(paths, dry_run, prune=False)`; `untrack` subcommand.

- [ ] **Step 1: Update `cmd_apply` and wire the CLI**

Replace `cmd_apply`:

```python
def cmd_apply(paths: Paths, dry_run: bool, prune: bool = False) -> None:
    changes = apply_all(paths, dry_run)
    if prune:
        changes += prune_all(paths, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    if not changes:
        print("nothing to do")
        return
    for c in changes:
        print(f"{prefix}{c}")
```

In `main`, extend the `apply` subparser:

```python
    ap.add_argument("--prune", action="store_true",
                    help="also delete de-targeted tracked skills from harnesses")
```

Add the `untrack` subparser (after the `tui` line):

```python
    up = sub.add_parser("untrack", help="stop managing a skill (repo copy backed up; harnesses untouched)")
    up.add_argument("name")
```

Update the dispatch: `cmd_apply(paths, args.dry_run, args.prune)` in the `apply` branch, and add:

```python
    elif args.cmd == "untrack":
        try:
            untrack_skill(paths, args.name)
        except KeyError:
            print(f"error: '{args.name}' is not tracked", file=sys.stderr)
            return 1
        print(f"untracked '{args.name}' (repo copy backed up; harnesses untouched)")
```

- [ ] **Step 2: Verify suite + CLI smoke**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

Run: `python3 harness_sync.py untrack no-such-skill; echo "exit=$?"`
Expected: `error: 'no-such-skill' is not tracked` and `exit=1`.

Run: `python3 harness_sync.py apply --dry-run --prune | tail -5`
Expected: pending pushes plus any `-x` prune lines (dry-run — nothing written).

- [ ] **Step 3: Commit**

```bash
git add harness_sync.py
git commit -m "feat: add untrack command and apply --prune flag

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: TUI — `u` untrack binding + prune checkbox

**Files:**
- Modify: `harness_tui.py`
- Test: `test_harness_sync.py` (guarded pilot test)

**Interfaces:**
- Consumes: `hs.untrack_skill`, `hs.prune_all`.
- Produces: `action_untrack_cursor`, prune `Checkbox` with id `#prune-check`.

- [ ] **Step 1: Write the failing guarded test**

```python
def test_tui_untrack_binding():
    try:
        import textual  # noqa: F401
    except ImportError:
        return
    import asyncio
    from harness_tui import HarnessSyncApp

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        (repo / "skills").mkdir(parents=True)
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": str(t / "cc")}, "codex": {"base": str(t / "cx")}}}))
        _make_skill(repo / "skills", "alpha", {"SKILL.md": "x"})
        _make_skill(t / "cc" / "skills", "alpha", {"SKILL.md": "x"})
        hs.save_manifest(repo / "manifest.json", {"skills": {"alpha": {"targets": ["claude"]}}})

        async def go():
            app = HarnessSyncApp(repo)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("u")
                await pilot.pause()
                assert "alpha" not in hs.load_manifest(repo / "manifest.json")["skills"]
                assert not (repo / "skills" / "alpha").exists()
                assert (t / "cc" / "skills" / "alpha").exists()  # harness untouched

        asyncio.run(go())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 test_harness_sync.py`
Expected: FAIL `test_tui_untrack_binding` (no `u` binding yet → manifest still has alpha).

- [ ] **Step 3: Implement in `harness_tui.py`**

Add `Checkbox` to the widgets import. Add the binding:

```python
        Binding("u", "untrack_cursor", "Untrack"),
```

In `compose`, add the checkbox above the Apply button:

```python
            with TabPane("Apply", id="tab-apply"):
                yield Log(id="apply-pending")
                yield Checkbox("also prune de-targeted skills", id="prune-check")
                yield Button("Apply now", id="apply-btn", variant="warning")
```

Update `_refresh_apply` to include prune lines when checked:

```python
    def _refresh_apply(self) -> None:
        pending = self.query_one("#apply-pending", Log)
        pending.clear()
        changes = hs.apply_all(self.paths, dry_run=True)
        if self.query_one("#prune-check", Checkbox).value:
            changes += hs.prune_all(self.paths, dry_run=True)
        if not changes:
            pending.write_line("nothing to do")
        for c in changes:
            pending.write_line(c)
```

Update `do_apply` to honor the checkbox, and add the toggle handler and the untrack action:

```python
    @on(Button.Pressed, "#apply-btn")
    def do_apply(self) -> None:
        changes = hs.apply_all(self.paths)
        if self.query_one("#prune-check", Checkbox).value:
            changes += hs.prune_all(self.paths)
        if not changes:
            self._log("apply: nothing to do")
        for c in changes:
            self._log(f"applied {c}")
        self.action_refresh()

    @on(Checkbox.Changed, "#prune-check")
    def prune_toggled(self) -> None:
        self._refresh_apply()

    def action_untrack_cursor(self) -> None:
        if self.query_one(TabbedContent).active != "tab-status":
            self._log("untrack: switch to the Status tab first")
            return
        table = self.query_one("#status-table", DataTable)
        if table.row_count == 0:
            return
        name = str(table.get_row_at(table.cursor_row)[0])
        try:
            hs.untrack_skill(self.paths, name)
        except KeyError:
            self._log(f"untrack: '{name}' is not tracked")
            return
        self._log(f"untracked {name} (repo copy backed up; harnesses untouched)")
        self.action_refresh()
```

Add CSS for the checkbox spacing: `#prune-check { margin-top: 1; }`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_harness_sync.py`
Expected: all `PASS`.

- [ ] **Step 5: Commit**

```bash
git add harness_tui.py test_harness_sync.py
git commit -m "feat: TUI untrack binding and prune checkbox

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Docs

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `AGENTS.md`

- [ ] **Step 1: Update docs**

- README: add `untrack <name>` and `apply [--prune]` to the command docs (untrack = backed-up repo removal, harnesses untouched; prune = opt-in, ignore/foreign always spared); mention the TUI `u` key and prune checkbox in the TUI section.
- CLAUDE.md Commands: add `untrack <name>` and the `--prune` flag with the safety rules; update the "never deletes" phrasing in Architecture to "never deletes unless explicitly asked via untrack/--prune (always backed up)".

- [ ] **Step 2: Re-sync AGENTS.md, verify, commit**

```bash
cd /Users/nacho/Documents/harness-sincronizer
cp CLAUDE.md AGENTS.md
python3 test_harness_sync.py
git add README.md CLAUDE.md AGENTS.md
git commit -m "docs: document untrack and apply --prune

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** untrack (manifest+repo+backup, harness untouched, KeyError) → Tasks 2/4 ✓; prune (opt-in, ignore skipped, foreign spared, backup, dry-run, `-x` strings) → Tasks 3/4 ✓; `backup_skill` refactor → Task 1 ✓; TUI `u` + prune checkbox with refreshed dry-run panel → Task 5 ✓; docs → Task 6 ✓; error handling (unknown untrack exit 1, TUI log lines) → Tasks 4/5 ✓.

**Placeholder scan:** none; all code steps complete. ✓

**Type consistency:** `backup_skill(paths, label, name, src)` used by `apply_skill` (label=h), `untrack_skill` (label="repo"), `prune_all` (label=h); `prune_all(paths, dry_run=False) -> list[str]`; `cmd_apply(paths, dry_run, prune=False)`; TUI ids `#prune-check` consistent. ✓
