# Settings & Hooks Sync (#10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync chosen top-level `settings.json` keys (hooks, permissions, env,
statusLine, ...) between Claude accounts, with account-neutral path
canonicalization and referenced-script file sync.

**Architecture:** Mirror the plugin-sync (#14) pattern: manifest top-level
`"settings"` section, pure states/adopt/apply functions, `settings` CLI group.
Values are stored canonicalized (`${HARNESS_BASE}` token); referenced files
live under repo `settings-files/` (gitignored). Whole-key replace on apply;
the shared surgical-settings write from #14 is extracted and reused.

**Tech Stack:** Python stdlib (json, re, pathlib). Runs on 3.9+.

## Global Constraints

- Core stdlib-only; both `python3` (3.9) and `python3.12` suites must pass.
- Claude-type harnesses only; codex/unknown targets warned and skipped.
- Excluded keys: `enabledPlugins`, `extraKnownMarketplaces` (plugin domain).
- Backups before overwrite under `.harness-sync-backups/<ts>/<harness>/_settings/`.
- English code/comments/commits.

---

### Task 1: Canonicalization helpers

**Files:** modify `harness_sync.py` (add `import re`; helpers after
`plugin_sync_apply_all`), test `test_harness_sync.py`

**Interfaces:**
- Produces: `SETTINGS_EXCLUDED: set[str]`, `BASE_TOKEN = "${HARNESS_BASE}"`,
  `canonicalize_value(value, base: Path)`, `resolve_value(value, base: Path)`,
  `referenced_paths(value) -> set[str]` (relative paths).

- [ ] **Step 1: Failing tests**

```python
def test_settings_canonicalize_resolve_and_refs():
    base = Path("/home/u/.claude")
    raw = {"type": "command",
           "command": "bash /home/u/.claude/hooks/n.sh && echo ~/.claude/x.py",
           "other": ["/home/u/.claude-other/keep.sh", 3, True]}
    # NOTE: '~' form only canonicalized when base is under the real $HOME;
    # use a base derived from Path.home() for that assertion.
    home_base = Path.home() / ".claude"
    v = hs.canonicalize_value(
        {"cmd": f"bash {home_base}/a.sh; run ~/.claude/b.py"}, home_base)
    assert v == {"cmd": "bash ${HARNESS_BASE}/a.sh; run ${HARNESS_BASE}/b.py"}
    c = hs.canonicalize_value(raw, base)
    assert c["command"].startswith("bash ${HARNESS_BASE}/hooks/n.sh")
    assert c["other"][0] == "/home/u/.claude-other/keep.sh"  # foreign base kept
    r = hs.resolve_value(c, Path("/mnt/.claude-perso"))
    assert r["command"].startswith("bash /mnt/.claude-perso/hooks/n.sh")
    assert hs.referenced_paths(c) == {"hooks/n.sh"}
```

- [ ] **Step 2: RED** — `AttributeError: canonicalize_value`
- [ ] **Step 3: Implementation**

```python
SETTINGS_EXCLUDED = {"enabledPlugins", "extraKnownMarketplaces"}
BASE_TOKEN = "${HARNESS_BASE}"
_REF_RE = re.compile(r"\$\{HARNESS_BASE\}/((?:[\w@%+=:,.^-]+/)*[\w@%+=:,.^-]+)")


def _walk_strings(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk_strings(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _walk_strings(v, fn) for k, v in value.items()}
    return value


def canonicalize_value(value, base: Path):
    subs = [str(base)]
    home = str(Path.home())
    if str(base).startswith(home + os.sep):
        subs.append("~" + str(base)[len(home):])
    def sub(s: str) -> str:
        for token in subs:
            s = s.replace(token, BASE_TOKEN)
        return s
    return _walk_strings(value, sub)


def resolve_value(value, base: Path):
    return _walk_strings(value, lambda s: s.replace(BASE_TOKEN, str(base)))


def referenced_paths(value) -> set[str]:
    found: set[str] = set()
    _walk_strings(value, lambda s: (found.update(_REF_RE.findall(s)), s)[1])
    return found
```

Note trailing-`.` in regex char class: rel paths like `hooks/n.sh` match; a
sentence-final period after a path is acceptable noise (dangling refs are
tolerated everywhere).

- [ ] **Step 4: GREEN both interpreters**
- [ ] **Step 5: Commit** — `feat: settings value canonicalization helpers`

### Task 2: States

**Files:** modify `harness_sync.py`, test `test_harness_sync.py`

**Interfaces:**
- Consumes: Task 1 helpers, `read_settings`, `_claude_harnesses`,
  `_harness_base`, `skill_hash` (file-aware).
- Produces: `_settings_files_dir(paths) -> Path` (repo `settings-files/`),
  `settings_states(paths) -> list[dict]` rows
  `{"name", "repo": bool, <h>: synced|drift|untracked|absent}`.

- [ ] **Step 1: Failing test** (fixture creates cc/cp claude + cx codex,
  a hook referencing `${HARNESS_BASE}/hooks/n.sh`, matching file in cc and
  repo, stale file in cp)

```python
def _settings_paths(t: Path) -> "hs.Paths":
    p = hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={"cc": t / "cc" / "skills", "cp": t / "cp" / "skills",
                        "cx": t / "cx" / "skills"},
        harness_types={"cc": "claude", "cp": "claude", "cx": "codex"},
    )
    for d in ("cc", "cp", "cx", "repo"):
        (t / d).mkdir(parents=True, exist_ok=True)
    hook_val = {"UserPromptSubmit": [{"hooks": [
        {"type": "command", "command": f"bash {t}/cc/hooks/n.sh"}]}]}
    (t / "cc" / "settings.json").write_text(json.dumps({
        "theme": "dark", "hooks": hook_val, "model": "opus",
        "enabledPlugins": {"x@y": True},
    }))
    (t / "cc" / "hooks").mkdir(parents=True, exist_ok=True)
    (t / "cc" / "hooks" / "n.sh").write_text("echo v1")
    (t / "cp" / "settings.json").write_text(json.dumps({"model": "sonnet"}))
    hs.save_manifest(p.manifest, {"skills": {}})
    return p


def test_settings_states_vocab_and_exclusions():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _settings_paths(t)
        hs.settings_adopt(p, "hooks", "cc", ["cc", "cp"])
        rows = {r["name"]: r for r in hs.settings_states(p)}
        assert rows["hooks"]["repo"] is True
        assert rows["hooks"]["cc"] == "synced"
        assert rows["hooks"]["cp"] == "absent"
        assert "cx" not in rows["hooks"]
        assert rows["model"]["repo"] is False
        assert rows["model"]["cc"] == "untracked"
        assert rows["model"]["cp"] == "untracked"
        assert "enabledPlugins" not in rows        # excluded (plugin domain)
        assert "theme" in rows                     # any other key is fair game
        # referenced-file drift: change the file on cc
        (t / "cc" / "hooks" / "n.sh").write_text("echo v2")
        rows = {r["name"]: r for r in hs.settings_states(p)}
        assert rows["hooks"]["cc"] == "drift"
```

(Depends on `settings_adopt` from Task 3 — implement Tasks 2+3 in one
RED-GREEN cycle: write both tests, then both implementations.)

- [ ] **Step 2: RED**
- [ ] **Step 3: Implementation**

```python
def _settings_files_dir(paths: Paths) -> Path:
    return paths.repo_skills.parent / "settings-files"


def settings_states(paths: Paths) -> list[dict]:
    man = load_manifest(paths.manifest).get("settings", {})
    names = _claude_harnesses(paths)
    raw = {h: read_settings(_harness_base(paths, h) / "settings.json")
           for h in names}
    keys = (set(man) | {k for d in raw.values() for k in d}) - SETTINGS_EXCLUDED
    rows = []
    for key in sorted(keys):
        tracked = man.get(key)
        row = {"name": key, "repo": tracked is not None}
        for h in names:
            if key not in raw[h]:
                row[h] = "absent"
            elif tracked is None:
                row[h] = "untracked"
            else:
                base = _harness_base(paths, h)
                same = canonicalize_value(raw[h][key], base) == tracked["value"]
                if same:
                    for rel in referenced_paths(tracked["value"]):
                        repo_f = _settings_files_dir(paths) / rel
                        tgt = base / rel
                        if repo_f.is_file() and (not tgt.is_file()
                                                 or skill_hash(tgt) != skill_hash(repo_f)):
                            same = False
                            break
                row[h] = "synced" if same else "drift"
        rows.append(row)
    return rows
```

- [ ] **Step 4: GREEN both** — [ ] **Step 5: Commit** `feat: settings-sync states`

### Task 3: Adopt

**Files:** modify `harness_sync.py`, test `test_harness_sync.py`

**Interfaces:**
- Produces: `settings_adopt(paths, key, source_harness, targets) -> None`;
  manifest `settings.<key> = {"targets", "value"}` (canonical); referenced
  files copied to `settings-files/<rel>`; dangling refs warned on stderr.

- [ ] **Step 1: Failing test**

```python
def test_settings_adopt_canonicalizes_and_copies_refs():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _settings_paths(t)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            hs.settings_adopt(p, "hooks", "cc", ["cc", "cp"])
        man = hs.load_manifest(p.manifest)["settings"]["hooks"]
        assert man["targets"] == ["cc", "cp"]
        cmd = man["value"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        assert cmd == "bash ${HARNESS_BASE}/hooks/n.sh"
        assert (t / "repo" / "settings-files" / "hooks" / "n.sh").read_text() == "echo v1"
        # dangling ref: value mentions a base path with no file behind it
        cc = json.loads((t / "cc" / "settings.json").read_text())
        cc["statusLine"] = {"command": f"bash {t}/cc/missing.sh"}
        (t / "cc" / "settings.json").write_text(json.dumps(cc))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            hs.settings_adopt(p, "statusLine", "cc", ["cc"])
        assert "missing.sh" in err.getvalue()
```

- [ ] **Step 2: RED**
- [ ] **Step 3: Implementation**

```python
def settings_adopt(paths: Paths, key: str, source_harness: str,
                   targets: list[str]) -> None:
    base = _harness_base(paths, source_harness)
    value = canonicalize_value(
        read_settings(base / "settings.json")[key], base)
    for rel in sorted(referenced_paths(value)):
        src = base / rel
        if src.is_file():
            dst = _settings_files_dir(paths) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            print(f"warning: settings '{key}' references '{rel}' but "
                  f"{src} does not exist — string synced, file skipped",
                  file=sys.stderr)
    man = load_manifest(paths.manifest)
    man.setdefault("settings", {})[key] = {"targets": list(targets), "value": value}
    save_manifest(paths.manifest, man)
```

- [ ] **Step 4: GREEN both** — [ ] **Step 5: Commit** `feat: settings-sync adopt`

### Task 4: Apply (+ shared settings-write helper)

**Files:** modify `harness_sync.py` (extract `_flush_settings` used by both
`plugin_sync_apply_all` and `settings_apply_all`), test `test_harness_sync.py`

**Interfaces:**
- Produces: `settings_apply_all(paths, dry_run=False) -> list[str]`
  (lines `settings:<key> -> <harness>`);
  `_flush_settings(paths, pending: dict[str, dict], label: str) -> None`.

- [ ] **Step 1: Failing tests**

```python
def test_settings_apply_replaces_key_and_materializes_files():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _settings_paths(t)
        hs.settings_adopt(p, "hooks", "cc", ["cc", "cp"])
        changes = hs.settings_apply_all(p)
        assert changes == ["settings:hooks -> cp"]   # cc already synced
        cp = json.loads((t / "cp" / "settings.json").read_text())
        cmd = cp["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        assert cmd == f"bash {t}/cp/hooks/n.sh"       # target base resolved
        assert cp["model"] == "sonnet"                # unrelated key preserved
        assert (t / "cp" / "hooks" / "n.sh").read_text() == "echo v1"
        assert hs.settings_apply_all(p) == []         # idempotent


def test_settings_apply_dry_run_backup_and_skips():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _settings_paths(t)
        hs.settings_adopt(p, "hooks", "cc", ["cc", "cp", "cx", "nope"])
        before = (t / "cp" / "settings.json").read_text()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert hs.settings_apply_all(p, dry_run=True) == ["settings:hooks -> cp"]
        assert (t / "cp" / "settings.json").read_text() == before
        assert "cx" in err.getvalue() and "nope" in err.getvalue()
        with contextlib.redirect_stderr(io.StringIO()):
            hs.settings_apply_all(p)
        assert any(b.name == "settings.json" for b in p.backups.rglob("*"))
```

- [ ] **Step 2: RED**
- [ ] **Step 3: Implementation** — extract from `plugin_sync_apply_all`:

```python
def _flush_settings(paths: Paths, pending: dict[str, dict], label: str) -> None:
    for h, settings in pending.items():
        path = _harness_base(paths, h) / "settings.json"
        if path.exists():
            backup = (paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S")
                      / h / label / path.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")
```

(`plugin_sync_apply_all` tail becomes `if not dry_run: _flush_settings(paths, pending, "_plugins")` —
guard stays outside since its `pending` is only filled when not dry-run.)

```python
def settings_apply_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest).get("settings", {})
    changes: list[str] = []
    pending: dict[str, dict] = {}
    for key, cfg in sorted(man.items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        for t in targets:
            if t not in paths.harness_skills or paths.harness_types[t] != "claude":
                print(f"warning: settings key '{key}' targets non-claude or "
                      f"unknown harness '{t}' — skipping", file=sys.stderr)
                continue
            base = _harness_base(paths, t)
            settings = pending.get(t)
            if settings is None:
                settings = read_settings(base / "settings.json")
            desired = resolve_value(cfg["value"], base)
            file_jobs = []
            for rel in sorted(referenced_paths(cfg["value"])):
                repo_f = _settings_files_dir(paths) / rel
                tgt = base / rel
                if repo_f.is_file() and (not tgt.is_file()
                                         or skill_hash(tgt) != skill_hash(repo_f)):
                    file_jobs.append((repo_f, tgt))
            if settings.get(key) == desired and not file_jobs:
                continue
            changes.append(f"settings:{key} -> {t}")
            if dry_run:
                continue
            for repo_f, tgt in file_jobs:
                if tgt.exists():
                    backup_skill(paths, t, tgt.name, tgt)
                tgt.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo_f, tgt)
            if settings.get(key) != desired:
                settings[key] = desired
                pending[t] = settings
    if not dry_run:
        _flush_settings(paths, pending, "_settings")
    return changes
```

(`backup_skill(paths, label, name, src)` is the existing file-aware backup —
verify its signature at implementation time and adjust the call.)

- [ ] **Step 4: GREEN both (incl. all existing plugin-sync tests — refactor safety)**
- [ ] **Step 5: Commit** — `feat: settings-sync apply with shared surgical writer`

### Task 5: CLI + docs + gitignore

**Files:** modify `harness_sync.py` (cmd trio + argparse `settings` group),
`.gitignore` (+`settings-files/`), `CLAUDE.md`, `README.md`,
test `test_harness_sync.py`

**Interfaces:**
- Produces: `cmd_settings_list(paths)`, `cmd_settings_adopt(paths)`,
  `cmd_settings_apply(paths, dry_run)`; CLI `settings list|adopt|apply [--dry-run]`.

- [ ] **Step 1: Failing test**

```python
def test_cli_settings_list_and_apply_dry_run():
    with tempfile.TemporaryDirectory() as tmp:
        p = _settings_paths(Path(tmp))
        hs.settings_adopt(p, "hooks", "cc", ["cc", "cp"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hs.cmd_settings_apply(p, dry_run=True)
        assert "[dry-run] settings:hooks -> cp" in out.getvalue()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hs.cmd_settings_list(p)
        text = out.getvalue()
        assert "hooks" in text and "model" in text
```

- [ ] **Step 2: RED** — [ ] **Step 3: cmd trio mirrors `cmd_plugin_sync_*`
  (list without the `*` marker logic; adopt iterates untracked/drift rows)**
- [ ] **Step 4: GREEN both; docs: CLAUDE.md Commands bullet + README section
  "Settings & hooks (Claude ↔ Claude)"; add `settings-files/` to .gitignore**
- [ ] **Step 5: Commit** — `feat: settings CLI + docs`

## Self-Review

- Spec coverage: canonicalize/resolve/refs ✔ (T1), states+exclusions+file
  drift ✔ (T2), adopt+repo copies+dangling warn ✔ (T3), whole-key replace,
  preserve unrelated keys, files materialized, backup, idempotent, dry-run,
  codex skip ✔ (T4), CLI/docs/gitignore ✔ (T5).
- Signatures consistent; `_flush_settings` refactor covered by existing
  plugin-sync tests.
