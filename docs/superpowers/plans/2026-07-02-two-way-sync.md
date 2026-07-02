# Two-Way Sync (#5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in two-way sync for file-based asset kinds: pull harness-only
changes into the repo, push repo-only changes, detect true conflicts via a
last-synced hash per asset×harness, resolve conflicts only explicitly.

**Architecture:** `.sync-state.json` at repo root records last-synced hashes.
`apply_skill`/`refresh_skill`/`adopt_skill` record baselines as a side effect.
`two_way_sync()` runs a pull phase then a push/conflict phase; `resolve()`
reuses `refresh_skill` + `apply_skill`. Thin `sync` / `resolve` CLI.

**Tech Stack:** stdlib only; both `python3` (3.9) and `python3.12` suites.

## Global Constraints

- Deletions never propagate automatically (warn instead).
- Conflicts touch nothing; `--dry-run` writes nothing (state file included).
- Config domains (mcp/plugins/settings) stay one-way; scope is `KINDS` only.
- Backups before every overwrite (existing `backup_skill`).
- English code/comments/commits; TDD.

---

### Task 1: State I/O + baseline recording

**Files:** modify `harness_sync.py` (state helpers near manifest I/O;
recording inside `apply_skill`, `refresh_skill`, `adopt_skill`),
`.gitignore` (+`/.sync-state.json`), test `test_harness_sync.py`

**Interfaces:**
- Produces: `state_path(paths) -> Path`, `load_state(paths) -> dict`,
  `save_state(paths, state) -> None`,
  `record_synced(paths, kind, name, harness, hash_) -> None`.
  State shape: `{kind: {name: {harness: sha256}}}`.

- [ ] **Step 1: Failing test**

```python
def test_sync_state_recorded_by_apply_refresh_adopt():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "gamma", {"SKILL.md": "v1"})
        hs.adopt_skill(p, "gamma", "claude", ["claude", "codex"])
        st = hs.load_state(p)
        g = hs.skill_hash(p.repo_skills / "gamma")
        assert st["skills"]["gamma"]["claude"] == g          # adopt records source
        hs.apply_skill(p, "gamma", ["codex"])
        assert hs.load_state(p)["skills"]["gamma"]["codex"] == g   # apply records push
        _make_skill(p.harness_skills["claude"], "gamma", {"SKILL.md": "v2"})
        hs.refresh_skill(p, "gamma", "claude")
        g2 = hs.skill_hash(p.repo_skills / "gamma")
        assert g2 != g
        assert hs.load_state(p)["skills"]["gamma"]["claude"] == g2  # refresh records pull
        hs.apply_skill(p, "gamma", ["codex"], dry_run=True)
        assert hs.load_state(p)["skills"]["gamma"]["codex"] == g    # dry-run records nothing
```

- [ ] **Step 2: RED** (`AttributeError: load_state`)
- [ ] **Step 3: Implementation**

```python
def state_path(paths: Paths) -> Path:
    return paths.manifest.parent / ".sync-state.json"


def load_state(paths: Paths) -> dict:
    p = state_path(paths)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_state(paths: Paths, state: dict) -> None:
    state_path(paths).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def record_synced(paths: Paths, kind: str, name: str, harness: str, hash_: str) -> None:
    state = load_state(paths)
    state.setdefault(kind, {}).setdefault(name, {})[harness] = hash_
    save_state(paths, state)
```

Hooks: in `apply_skill`, record after `copy_skill(src, dst)` and in the
already-equal `continue` branch; in `refresh_skill`, record
`skill_hash(repo_asset)` for `source_harness` after the copy; in
`adopt_skill`, record for `source_harness` after `import_skill` using the
repo copy's hash.

- [ ] **Step 4: GREEN both** — [ ] **Step 5: Commit** `feat: last-synced state recording`

### Task 2: `two_way_sync` + `resolve_conflict`

**Files:** modify `harness_sync.py` (after `prune_all`), test `test_harness_sync.py`

**Interfaces:**
- Consumes: Task 1 helpers, `skill_hash`, `copy_skill`, `backup_skill`,
  `refresh_skill`, `apply_skill`, `harness_asset_path`, `repo_kind_dir`.
- Produces: `two_way_sync(paths, dry_run=False) -> dict` with keys
  `push`/`pull`/`conflict`/`warn` (lists of formatted lines);
  `resolve_conflict(paths, name, winner, kind="skills") -> list[str]`
  (raises `KeyError` if untracked, `ValueError` on unknown winner).

- [ ] **Step 1: Failing tests**

```python
def test_two_way_sync_push_pull_and_stale_second_harness():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        hs.adopt_skill(p, "alpha", "claude", ["claude", "codex"])
        hs.apply_skill(p, "alpha", ["claude", "codex"])
        # harness-only change in claude -> pulled, then pushed to stale codex
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v2"})
        r = hs.two_way_sync(p)
        assert r["pull"] == ["pull alpha <- claude"]
        assert r["push"] == ["push alpha -> codex"]
        assert (p.repo_skills / "alpha" / "SKILL.md").read_text() == "v2"
        assert (p.harness_skills["codex"] / "alpha" / "SKILL.md").read_text() == "v2"
        # repo-only change -> push both
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v3"})
        r = hs.two_way_sync(p)
        assert r["pull"] == [] and sorted(r["push"]) == [
            "push alpha -> claude", "push alpha -> codex"]
        assert hs.two_way_sync(p) == {"push": [], "pull": [], "conflict": [], "warn": []}


def test_two_way_sync_conflicts_and_guards():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "beta", {"SKILL.md": "v1"})
        hs.adopt_skill(p, "beta", "claude", ["claude"])
        # both changed -> conflict, nothing written
        _make_skill(p.repo_skills, "beta", {"SKILL.md": "repo-edit"})
        _make_skill(p.harness_skills["claude"], "beta", {"SKILL.md": "claude-edit"})
        r = hs.two_way_sync(p)
        assert r["conflict"] == ["conflict beta : claude"]
        assert (p.repo_skills / "beta" / "SKILL.md").read_text() == "repo-edit"
        assert (p.harness_skills["claude"] / "beta" / "SKILL.md").read_text() == "claude-edit"
        # missing baseline + difference -> conflict (unattributable)
        _make_skill(p.repo_skills, "gamma", {"SKILL.md": "x"})
        _make_skill(p.harness_skills["claude"], "gamma", {"SKILL.md": "y"})
        man = hs.load_manifest(p.manifest)
        man["skills"]["gamma"] = {"targets": ["claude"]}
        hs.save_manifest(p.manifest, man)
        r = hs.two_way_sync(p)
        assert "conflict gamma : claude" in r["conflict"]
        # harness deletion -> warn, never pulled as deletion
        hs.resolve_conflict(p, "beta", "repo")
        shutil.rmtree(p.harness_skills["claude"] / "beta")
        r = hs.two_way_sync(p)
        assert any("deleted in 'claude'" in w for w in r["warn"])
        assert (p.repo_skills / "beta").exists()
        # repo copy missing -> warn
        shutil.rmtree(p.repo_skills / "gamma")
        r = hs.two_way_sync(p)
        assert any(w.startswith("gamma: repo copy missing") for w in r["warn"])


def test_two_way_sync_dry_run_and_resolve():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "delta", {"SKILL.md": "v1"})
        hs.adopt_skill(p, "delta", "claude", ["claude", "codex"])
        hs.apply_skill(p, "delta", ["claude", "codex"])
        _make_skill(p.harness_skills["claude"], "delta", {"SKILL.md": "v2"})
        state_before = hs.load_state(p)
        r = hs.two_way_sync(p, dry_run=True)
        assert r["pull"] == ["pull delta <- claude"]
        assert r["push"] == ["push delta -> codex"]      # simulated post-pull hash
        assert (p.repo_skills / "delta" / "SKILL.md").read_text() == "v1"
        assert hs.load_state(p) == state_before
        # conflict resolution: harness wins
        _make_skill(p.repo_skills, "delta", {"SKILL.md": "repo-edit"})
        assert hs.two_way_sync(p, dry_run=True)["conflict"] == ["conflict delta : claude"]
        hs.resolve_conflict(p, "delta", "claude")
        assert (p.repo_skills / "delta" / "SKILL.md").read_text() == "v2"
        assert (p.harness_skills["codex"] / "delta" / "SKILL.md").read_text() == "v2"
        assert hs.two_way_sync(p) == {"push": [], "pull": [], "conflict": [], "warn": []}
        try:
            hs.resolve_conflict(p, "delta", "nope")
            assert False, "expected ValueError"
        except ValueError:
            pass
```

- [ ] **Step 2: RED**
- [ ] **Step 3: Implementation**

```python
def two_way_sync(paths: Paths, dry_run: bool = False) -> dict:
    man = load_manifest(paths.manifest)
    state = load_state(paths)
    result = {"push": [], "pull": [], "conflict": [], "warn": []}
    for kind in KINDS:
        for name, cfg in sorted(man.get(kind, {}).items()):
            targets = [t for t in cfg.get("targets", []) if t in paths.harness_skills]
            if "ignore" in cfg.get("targets", []):
                continue
            label = format_asset_name(kind, name)
            repo_asset = repo_kind_dir(paths, kind) / name
            if not repo_asset.exists():
                result["warn"].append(f"{label}: repo copy missing — untrack or re-adopt")
                continue
            repo_hash = skill_hash(repo_asset)
            entry = state.setdefault(kind, {}).setdefault(name, {})

            def hashes(h):
                dst = harness_asset_path(paths, h, kind, name)
                if dst is None:
                    return None, None  # codex-type target of a claude-only kind
                return dst, (skill_hash(dst) if dst.exists() else None)

            # phase 1: pull harness-only changes (repo unchanged since last sync)
            for h in targets:
                dst, h_hash = hashes(h)
                if dst is None or h_hash is None or h_hash == repo_hash:
                    continue
                if repo_hash == entry.get(h):
                    result["pull"].append(f"pull {label} <- {h}")
                    if not dry_run:
                        refresh_skill(paths, name, h, kind)
                    repo_hash = h_hash
                    entry[h] = h_hash

            # phase 2: push, record, or report
            for h in targets:
                dst, h_hash = hashes(h)
                if dst is None:
                    continue
                last = entry.get(h)
                if not dry_run and h in [x.rsplit(" ", 1)[1] for x in result["pull"]
                                         if x.startswith(f"pull {label} ")]:
                    h_hash = repo_hash  # just pulled from it
                if h_hash == repo_hash:
                    entry[h] = repo_hash
                    continue
                if h_hash is None and last is not None:
                    result["warn"].append(
                        f"{label}: deleted in '{h}' — untrack it, or resolve "
                        f"'{label}' repo to restore")
                    continue
                if h_hash == last or (h_hash is None and last is None):
                    result["push"].append(f"push {label} -> {h}")
                    if dry_run:
                        continue
                    if dst.exists():
                        backup_skill(paths, h, name, dst)
                    copy_skill(repo_asset, dst)
                    entry[h] = repo_hash
                else:
                    result["conflict"].append(f"conflict {label} : {h}")
    if not dry_run:
        save_state(paths, state)
    return result


def resolve_conflict(paths: Paths, name: str, winner: str,
                     kind: str = "skills") -> list[str]:
    man = load_manifest(paths.manifest)
    if name not in man.get(kind, {}):
        raise KeyError(name)
    if winner != "repo" and winner not in paths.harness_skills:
        raise ValueError(winner)
    if winner != "repo":
        refresh_skill(paths, name, winner, kind)
    targets = [t for t in man[kind][name].get("targets", []) if t != "ignore"]
    return apply_skill(paths, name, targets, False, kind)
```

Note the dry-run pull simulation: `repo_hash` is advanced without copying so
phase 2 plans the follow-up pushes accurately. The phase-2 "just pulled"
re-read exists because `hashes()` re-reads from disk; when not dry-run the
refresh already made them equal, so the branch is only a shortcut — verify
with the tests and simplify if the plain re-read already passes.

- [ ] **Step 4: GREEN both** — [ ] **Step 5: Commit** `feat: two-way sync engine and conflict resolution`

### Task 3: CLI + docs

**Files:** modify `harness_sync.py` (cmd + argparse + dispatch), `CLAUDE.md`,
`README.md` (new section + non-goals note), test `test_harness_sync.py`

**Interfaces:**
- Produces: `cmd_sync(paths, dry_run) -> int` (1 when conflicts/warns remain),
  CLI `sync [--dry-run]`, `resolve <kind:name> <repo|harness>`.

- [ ] **Step 1: Failing test**

```python
def test_cli_sync_output_and_exit_code():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "eps", {"SKILL.md": "v1"})
        hs.adopt_skill(p, "eps", "claude", ["claude"])
        _make_skill(p.repo_skills, "eps", {"SKILL.md": "r"})
        _make_skill(p.harness_skills["claude"], "eps", {"SKILL.md": "h"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = hs.cmd_sync(p, dry_run=True)
        assert code == 1
        assert "conflict eps : claude" in out.getvalue()
        assert "resolve" in out.getvalue()               # hint printed
        hs.resolve_conflict(p, "eps", "repo")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert hs.cmd_sync(p, dry_run=False) == 0
        assert "in sync" in out.getvalue()
```

- [ ] **Step 2: RED** — [ ] **Step 3: Implementation**

```python
def cmd_sync(paths: Paths, dry_run: bool) -> int:
    r = two_way_sync(paths, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    for line in r["pull"] + r["push"] + r["conflict"] + r["warn"]:
        print(f"{prefix}{line}")
    if r["conflict"]:
        print(f"{len(r['conflict'])} conflict(s) — resolve with: "
              f"harness_sync.py resolve <kind:name> <repo|harness>")
    if not any(r.values()):
        print("everything in sync")
    return 1 if r["conflict"] or r["warn"] else 0
```

argparse: `syp = sub.add_parser("sync", ...)` with `--dry-run`;
`rvp = sub.add_parser("resolve", ...)` with `name` and `winner` args;
dispatch parses `kind:name` via `parse_asset_name`, maps `KeyError` →
"not tracked" (exit 1), `ValueError` → "unknown winner" (exit 1).
Docs: CLAUDE.md Commands bullets + rewrite the Non-goals paragraph
(two-way shipped, opt-in); README section "Two-way sync (opt-in)".

- [ ] **Step 4: GREEN both** — [ ] **Step 5: Commit** `feat: sync/resolve CLI + docs`

## Self-Review

- Spec coverage: state recording ✔ (T1), three change scenarios + guards +
  dry-run + pull-then-push ✔ (T2), resolve repo/harness ✔ (T2), CLI exit
  code + hint ✔ (T3), gitignore ✔ (T1), docs incl. non-goals update ✔ (T3).
- Signatures consistent (`two_way_sync` dict keys used by `cmd_sync`).
