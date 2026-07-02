# Asset-Kind Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the engine to asset kinds and ship agents + slash commands syncing between Claude-type harnesses through the existing `status/adopt/apply/untrack/refresh` flows and the TUI.

**Architecture:** A `KINDS` table (skills=dir, agents/commands=file, claude_only). Primitives (`skill_hash`, `copy_skill`, `backup_skill`) become polymorphic on the filesystem; `scan_kind`/`harness_kind_dir` handle per-kind discovery; every flow gains `kind="skills"` (existing 48 tests stay green by default). Assets are addressed `kind:name` (skills unprefixed) everywhere.

**Tech Stack:** Python stdlib; textual in the TUI layer only. Suites on `python3` (3.9) and `python3.12`.

## Global Constraints

- `KINDS = {"skills": dir/all, "agents": file/claude_only, "commands": file/claude_only}`; kind name == subdir in repo and harness base.
- File asset name = full filename (`sdd-apply.md`); prefix syntax `kind:name`, skills unprefixed.
- claude_only kinds: codex-type harnesses scan empty; as apply targets → stderr warn + skip.
- Manifest sections additive (`"agents"`, `"commands"`); `"skills"`/`"mcp"` schemas untouched.
- All existing tests must pass unchanged; safety rules (backups, unmanaged untouched, opt-in prune) hold per kind.
- English code/comments/commits; Co-Authored-By trailer.

---

### Task 0: Branch

- [ ] `git checkout main && git checkout -b feature/asset-kinds`, commit spec+plan (`docs: add asset-kinds spec and plan`).

---

### Task 1: Kind table + polymorphic primitives

**Interfaces produced:** `KINDS: dict[str, dict]`; `parse_asset_name(s) -> tuple[str, str]`; `format_asset_name(kind, name) -> str`; `scan_kind(root: Path, kind: str) -> dict[str, str]`; `harness_kind_dir(paths, h, kind) -> Path | None`; file support in `skill_hash`/`copy_skill`/`backup_skill`.

- [ ] **Step 1: Failing tests**

```python
def test_parse_and_format_asset_name():
    assert hs.parse_asset_name("branch-pr") == ("skills", "branch-pr")
    assert hs.parse_asset_name("agents:sdd-apply.md") == ("agents", "sdd-apply.md")
    assert hs.format_asset_name("skills", "x") == "x"
    assert hs.format_asset_name("agents", "y.md") == "agents:y.md"


def test_scan_kind_files_and_hash_copy_file():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "agents"
        root.mkdir()
        (root / "one.md").write_text("A")
        (root / "two.md").write_text("B")
        (root / "notes.txt").write_text("ignored")
        result = hs.scan_kind(root, "agents")
        assert set(result) == {"one.md", "two.md"}
        # file hash: content-sensitive
        assert hs.skill_hash(root / "one.md") != hs.skill_hash(root / "two.md")
        # file copy
        dst = Path(t) / "out" / "one.md"
        hs.copy_skill(root / "one.md", dst)
        assert dst.read_text() == "A"
        # dir kind delegates to the existing scan
        assert hs.scan_kind(Path(t) / "missing", "skills") == {}


def test_harness_kind_dir_claude_only():
    with tempfile.TemporaryDirectory() as tmp:
        p = _paths_in(Path(tmp))  # claude:claude, codex:codex
        assert hs.harness_kind_dir(p, "claude", "agents") is not None
        assert hs.harness_kind_dir(p, "codex", "agents") is None      # claude_only
        assert hs.harness_kind_dir(p, "codex", "skills") is not None  # skills everywhere
```

- [ ] **Step 2: RED** (`AttributeError: parse_asset_name`), **Step 3: implement**

```python
KINDS = {
    "skills": {"asset": "dir", "claude_only": False},
    "agents": {"asset": "file", "claude_only": True},
    "commands": {"asset": "file", "claude_only": True},
}


def parse_asset_name(s: str) -> tuple[str, str]:
    if ":" in s:
        kind, _, name = s.partition(":")
        if kind in KINDS:
            return kind, name
    return "skills", s


def format_asset_name(kind: str, name: str) -> str:
    return name if kind == "skills" else f"{kind}:{name}"


def scan_kind(root: Path, kind: str) -> dict[str, str]:
    if KINDS[kind]["asset"] == "dir":
        return scan(root)
    if not root.is_dir():
        return {}
    return {f.name: skill_hash(f) for f in sorted(root.glob("*.md")) if f.is_file()}


def harness_kind_dir(paths: Paths, harness: str, kind: str) -> Path | None:
    if KINDS[kind]["claude_only"] and paths.harness_types[harness] == "codex":
        return None
    return paths.harness_skills[harness].parent / kind
```

`skill_hash`: at the top add `if skill_dir.is_file(): h = hashlib.sha256(skill_dir.read_bytes()); return h.hexdigest()`. `copy_skill`: if `src.is_file()`: `dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)` (remove pre-existing dst dir/file first if present). `backup_skill`: `copytree` when `src.is_dir()` else `copy2`.

Note: `harness_kind_dir(paths, h, "skills")` equals `paths.harness_skills[h]` because the skills subdir convention matches — keep `harness_skills` as-is.

- [ ] **Step 4: both suites green**, **Step 5: commit** (`feat: asset-kind table and polymorphic primitives`).

---

### Task 2: Generalize flows (`kind=` params, apply/prune over all kinds)

**Interfaces:** `compute_states(paths, kind="skills")`, `import_skill(..., kind="skills")`, `adopt_skill(..., kind="skills")`, `apply_skill(..., kind="skills")`, `apply_all`/`prune_all` iterate `KINDS`, `untrack_skill(..., kind="skills")`, `refresh_skill(..., kind="skills")`. Change strings via `format_asset_name`.

- [ ] **Step 1: Failing tests**

```python
def _agent_paths(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={"claude": t / "cc" / "skills",
                        "claude-perso": t / "cp" / "skills",
                        "codex": t / "cx" / "skills"},
        harness_types={"claude": "claude", "claude-perso": "claude", "codex": "codex"},
    )


def test_agent_states_adopt_apply_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _agent_paths(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        agents = t / "cc" / "agents"
        agents.mkdir(parents=True)
        (agents / "bot.md").write_text("agent body")

        rows = {r["name"]: r for r in hs.compute_states(p, kind="agents")}
        assert rows["bot.md"]["claude"] == "untracked"
        assert rows["bot.md"]["codex"] == "absent"          # claude_only

        hs.adopt_skill(p, "bot.md", "claude", ["claude", "claude-perso"], kind="agents")
        assert (t / "repo" / "agents" / "bot.md").read_text() == "agent body"
        assert hs.load_manifest(p.manifest)["agents"]["bot.md"] == {
            "targets": ["claude", "claude-perso"]}

        changes = hs.apply_all(p)
        assert "agents:bot.md -> claude-perso" in changes
        assert (t / "cp" / "agents" / "bot.md").read_text() == "agent body"
        assert hs.apply_all(p) == []                        # idempotent


def test_agent_apply_skips_codex_target_with_warning():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _agent_paths(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        (t / "repo" / "agents").mkdir(parents=True)
        (t / "repo" / "agents" / "bot.md").write_text("x")
        hs.save_manifest(p.manifest, {"skills": {}, "agents": {
            "bot.md": {"targets": ["codex"]}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = hs.apply_all(p)
        assert changes == []
        assert "codex" in err.getvalue()
        assert not (t / "cx" / "agents").exists()


def test_agent_untrack_refresh_prune():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _agent_paths(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        agents_cc = t / "cc" / "agents"
        agents_cc.mkdir(parents=True)
        (agents_cc / "bot.md").write_text("v1")
        hs.adopt_skill(p, "bot.md", "claude", ["claude"], kind="agents")

        # refresh after harness edit
        (agents_cc / "bot.md").write_text("v2")
        hs.refresh_skill(p, "bot.md", "claude", kind="agents")
        assert (t / "repo" / "agents" / "bot.md").read_text() == "v2"

        # prune: de-target claude-perso copy
        agents_cp = t / "cp" / "agents"
        agents_cp.mkdir(parents=True)
        (agents_cp / "bot.md").write_text("stray")
        changes = hs.prune_all(p)
        assert changes == ["agents:bot.md -x claude-perso"]
        assert not (agents_cp / "bot.md").exists()

        # untrack: manifest+repo gone, harness intact
        hs.untrack_skill(p, "bot.md", kind="agents")
        assert "bot.md" not in hs.load_manifest(p.manifest).get("agents", {})
        assert not (t / "repo" / "agents" / "bot.md").exists()
        assert (agents_cc / "bot.md").exists()
```

- [ ] **Step 2: RED**, **Step 3: implement** — thread `kind` through:

```python
def repo_kind_dir(paths: Paths, kind: str) -> Path:
    return paths.repo_skills.parent / kind if kind != "skills" else paths.repo_skills
```

Wait — `paths.repo_skills.parent` is the repo root only when repo_skills is `<root>/skills`; true by construction. Use `paths.repo_skills.parent / kind` for all kinds (equals repo_skills for "skills").

- `compute_states(paths, kind="skills")`: scan via `scan_kind(repo_kind_dir(...), kind)` and per harness `harness_kind_dir(...)` (None → `{}`).
- `import_skill(paths, name, src_dir, targets, kind="skills")`: copy to `repo_kind_dir/name`, write `man.setdefault(kind, {})[name]`.
- `adopt_skill(paths, name, source_harness, targets, kind="skills")`: src = `harness_kind_dir(paths, source_harness, kind) / name`.
- `apply_skill(paths, name, targets, dry_run=False, kind="skills")`: src = `repo_kind_dir/name`; per target, `hd = harness_kind_dir(...)`; `hd is None` → stderr warn + continue; dst = `hd / name`; compare `skill_hash` (file-aware); backup label = harness; change string `format_asset_name(kind, name) + f" -> {h}"`.
- `apply_all` / `prune_all`: outer loop `for kind in KINDS:` over `man.get(kind, {})`; prune uses `harness_kind_dir` (None → skip) and `_remove` helper (`rmtree` dir / `unlink` file); prune change `f"{format_asset_name(kind, name)} -x {h}"`.
- `untrack_skill(paths, name, kind="skills")` / `refresh_skill(paths, name, source_harness, kind="skills")`: same logic on `man[kind]` + `repo_kind_dir`; deletion file-aware.

- [ ] **Step 4: both suites green** (existing 48 + 4 new), **Step 5: commit** (`feat: generalize sync flows to asset kinds`).

---

### Task 3: CLI over all kinds

- [ ] `cmd_status`: iterate `for kind in KINDS: for row in compute_states(paths, kind)`, print prefixed names (skills rows unchanged); `cmd_adopt`: same walk, prompts show prefixed name, targets offered only from claude-type harnesses for claude_only kinds; `untrack`/`refresh` dispatch: `kind, name = parse_asset_name(args.name)` threaded through (refresh source-inference uses `compute_states(paths, kind)`).
- [ ] Suites green + smoke: `python3 harness_sync.py status | rg 'agents:'` shows real agents (e.g. `agents:sdd-apply.md`) as untracked; `python3 harness_sync.py untrack agents:nope.md` → not tracked, exit 1.
- [ ] Commit (`feat: status/adopt/untrack/refresh cover all asset kinds`).

---

### Task 4: TUI

- [ ] Status table + `u` untrack: rows from all kinds with prefixed names (`action_untrack_cursor` parses the prefix). Adopt tab: adoptable rows from all kinds in the same SelectionList (values = prefixed name; handler parses kind; source select unchanged; claude_only target enforcement happens in core `apply`/`adopt` — adopt targets list stays global, log lines surface skips).
- [ ] Guarded test: temp repo with one claude agent → status table contains a row named `agents:bot.md`; selecting it in adopt + target claude-perso → manifest `agents` section written.
- [ ] Both suites green; commit (`feat: TUI covers agents and commands kinds`).

---

### Task 5: Docs

- [ ] README: "Agents & slash commands" section (claude-only, `kind:name` addressing, same flows); CLAUDE.md: kind model + naming + claude_only rule; move agents/commands out of the multi-account 'later' notes; `cp CLAUDE.md AGENTS.md`; suites; commit (`docs: document asset kinds`).

---

## Self-Review

**Spec coverage:** KINDS table/primitives → T1; flows+manifest sections+claude_only skip → T2; prefixed addressing in CLI → T3 (+`parse_asset_name` T1); TUI → T4; safety inherited via shared helpers (backup/copy file-aware) → T1/T2; docs → T5. **Placeholders:** none — T3/T4 steps name exact functions and behaviors, code follows established patterns from T1/T2 signatures. **Type consistency:** `kind` keyword last-with-default everywhere; `repo_kind_dir`/`harness_kind_dir` consumed consistently; change-string format via `format_asset_name` in both apply and prune. ✓
