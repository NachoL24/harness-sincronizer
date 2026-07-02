# Whole-Plugin Sync (#14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync whole Claude plugin installs between Claude accounts by syncing
the declarative settings layer (`enabledPlugins` + `extraKnownMarketplaces`).

**Architecture:** Mirror the `mcp` manifest-section pattern: top-level
`"plugins"` manifest section, states/adopt/apply pure functions, thin CLI
under the existing `plugins` argparse group (`sync-list` / `sync-adopt` /
`sync-apply`). Surgical JSON writes touch only the two managed keys of
`settings.json`; machine-managed layers (`installed_plugins.json`, cache,
marketplace clones) are never written.

**Tech Stack:** Python stdlib only (json, pathlib). Runs on 3.9+ (no tomllib).

## Global Constraints

- Core stays stdlib-only; no textual import outside `harness_tui.py`.
- All code/comments/commits in English.
- Tests: `python3 test_harness_sync.py` AND `python3.12 test_harness_sync.py`
  must pass (assert-based runner, hermetic tmp dirs).
- Claude-type harnesses only; codex targets warned and skipped.
- Backup before any overwrite: `.harness-sync-backups/<ts>/<harness>/_plugins/settings.json`.

---

### Task 1: State computation (`plugin_sync_states`)

**Files:**
- Modify: `harness_sync.py` (new helpers after the mcp block, ~line 556)
- Test: `test_harness_sync.py`

**Interfaces:**
- Produces: `read_settings(path: Path) -> dict`,
  `plugin_sync_states(paths: Paths) -> list[dict]` — rows
  `{"name", "repo": bool, "installed": {h: bool}, <h>: state}` for each
  claude-type harness `h`; states `synced|drift|untracked|absent`.

- [ ] **Step 1: Write the failing tests**

```python
def _plugin_paths(t: Path) -> "hs.Paths":
    p = hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={"cc": t / "cc" / "skills", "cp": t / "cp" / "skills",
                        "cx": t / "cx" / "skills"},
        harness_types={"cc": "claude", "cp": "claude", "cx": "codex"},
    )
    for h in ("cc", "cp", "cx"):
        (t / h).mkdir(parents=True, exist_ok=True)
    (t / "cc" / "settings.json").write_text(json.dumps({
        "theme": "dark",
        "enabledPlugins": {"pony@mkt": True, "edith@nn": True, "off@mkt": False},
        "extraKnownMarketplaces": {"mkt": {"source": {"source": "github", "repo": "o/mkt"}}},
    }))
    (t / "cc" / "plugins").mkdir(parents=True, exist_ok=True)
    (t / "cc" / "plugins" / "known_marketplaces.json").write_text(json.dumps({
        "mkt": {"source": {"source": "github", "repo": "o/mkt"}},
        "nn": {"source": {"source": "github", "repo": "o/nn"}},
    }))
    (t / "cc" / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "version": 1,
        "plugins": {"pony@mkt": [{"installPath": str(t / "cc"), "version": "1.0.0"}]},
    }))
    (t / "cp" / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"pony@mkt": False},
    }))
    hs.save_manifest(p.manifest, {"skills": {}, "plugins": {
        "pony@mkt": {"targets": ["cc", "cp"],
                     "marketplace": {"source": "github", "repo": "o/mkt"}},
    }})
    return p


def test_plugin_sync_states_vocab_and_claude_only():
    with tempfile.TemporaryDirectory() as tmp:
        p = _plugin_paths(Path(tmp))
        rows = {r["name"]: r for r in hs.plugin_sync_states(p)}
        pony = rows["pony@mkt"]
        assert pony["repo"] is True
        assert pony["cc"] == "synced"
        assert pony["cp"] == "drift"          # explicit false
        assert "cx" not in pony               # codex excluded
        assert pony["installed"] == {"cc": True, "cp": False}
        edith = rows["edith@nn"]
        assert edith["repo"] is False
        assert edith["cc"] == "untracked"
        assert edith["cp"] == "absent"
        assert "off@mkt" not in rows          # disabled + untracked -> not a row
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 test_harness_sync.py`
Expected: FAIL — `AttributeError: module 'harness_sync' has no attribute 'plugin_sync_states'`

- [ ] **Step 3: Minimal implementation** (in `harness_sync.py`, after `mcp_apply_all`)

```python
def read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _claude_harnesses(paths: Paths) -> list[str]:
    return [h for h in paths.harness_skills if paths.harness_types[h] == "claude"]


def _harness_base(paths: Paths, harness: str) -> Path:
    return paths.harness_skills[harness].parent


def _known_marketplaces(paths: Paths, harness: str) -> set[str]:
    base = _harness_base(paths, harness)
    known = set(read_settings(base / "settings.json").get("extraKnownMarketplaces", {}))
    f = base / "plugins" / "known_marketplaces.json"
    if f.exists():
        known |= set(json.loads(f.read_text()))
    return known


def plugin_sync_states(paths: Paths) -> list[dict]:
    man = load_manifest(paths.manifest).get("plugins", {})
    names = _claude_harnesses(paths)
    enabled = {h: read_settings(_harness_base(paths, h) / "settings.json")
               .get("enabledPlugins", {}) for h in names}
    installed = {h: {k for k, _ in read_installed_plugins(_harness_base(paths, h) / "plugins")}
                 for h in names}
    keys = set(man) | {k for e in enabled.values() for k, v in e.items() if v}
    rows = []
    for key in sorted(keys):
        tracked = key in man
        row = {"name": key, "repo": tracked,
               "installed": {h: key in installed[h] for h in names}}
        for h in names:
            v = enabled[h].get(key)
            if v is None:
                row[h] = "absent"
            elif not tracked:
                row[h] = "untracked"
            else:
                row[h] = "synced" if v else "drift"
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run tests, expect PASS (both interpreters)**

Run: `python3 test_harness_sync.py && python3.12 test_harness_sync.py`

- [ ] **Step 5: Commit** — `feat: plugin-sync state computation`

### Task 2: Adopt (`plugin_sync_adopt`)

**Files:** modify `harness_sync.py`, test `test_harness_sync.py`

**Interfaces:**
- Consumes: `_harness_base`, `load_manifest`/`save_manifest`.
- Produces: `plugin_sync_adopt(paths, key, source_harness, targets) -> None`;
  manifest entry `{"targets": [...], "marketplace": <source dict or None>}`.

- [ ] **Step 1: Failing test**

```python
def test_plugin_sync_adopt_records_marketplace_source():
    with tempfile.TemporaryDirectory() as tmp:
        p = _plugin_paths(Path(tmp))
        hs.plugin_sync_adopt(p, "edith@nn", "cc", ["cc", "cp"])
        man = hs.load_manifest(p.manifest)["plugins"]
        assert man["edith@nn"] == {
            "targets": ["cc", "cp"],
            "marketplace": {"source": "github", "repo": "o/nn"},
        }
        # unknown marketplace -> None recorded
        hs.plugin_sync_adopt(p, "ghost@nowhere", "cc", ["cp"])
        assert hs.load_manifest(p.manifest)["plugins"]["ghost@nowhere"]["marketplace"] is None
```

- [ ] **Step 2: Verify failure** (`AttributeError: plugin_sync_adopt`)

- [ ] **Step 3: Implementation**

```python
def plugin_sync_adopt(paths: Paths, key: str, source_harness: str,
                      targets: list[str]) -> None:
    base = _harness_base(paths, source_harness)
    mname = key.split("@", 1)[1] if "@" in key else key
    src = None
    f = base / "plugins" / "known_marketplaces.json"
    if f.exists():
        src = json.loads(f.read_text()).get(mname, {}).get("source")
    if src is None:
        src = (read_settings(base / "settings.json")
               .get("extraKnownMarketplaces", {}).get(mname, {}).get("source"))
    man = load_manifest(paths.manifest)
    man.setdefault("plugins", {})[key] = {"targets": list(targets), "marketplace": src}
    save_manifest(paths.manifest, man)
```

- [ ] **Step 4: Both interpreters pass**
- [ ] **Step 5: Commit** — `feat: plugin-sync adopt`

### Task 3: Apply (`plugin_sync_apply_all`)

**Files:** modify `harness_sync.py`, test `test_harness_sync.py`

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces: `plugin_sync_apply_all(paths, dry_run=False) -> list[str]`
  (change lines `plugin:<key> -> <harness>`).

- [ ] **Step 1: Failing tests**

```python
def test_plugin_sync_apply_sets_flag_and_marketplace():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _plugin_paths(t)
        changes = hs.plugin_sync_apply_all(p)
        assert changes == ["plugin:pony@mkt -> cp"]      # cc already synced
        cp = json.loads((t / "cp" / "settings.json").read_text())
        assert cp["enabledPlugins"]["pony@mkt"] is True  # false overwritten
        assert cp["extraKnownMarketplaces"]["mkt"] == {
            "source": {"source": "github", "repo": "o/mkt"}}
        # idempotent
        assert hs.plugin_sync_apply_all(p) == []


def test_plugin_sync_apply_preserves_keys_backs_up_and_dry_run():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _plugin_paths(t)
        before = (t / "cp" / "settings.json").read_text()
        assert hs.plugin_sync_apply_all(p, dry_run=True) == ["plugin:pony@mkt -> cp"]
        assert (t / "cp" / "settings.json").read_text() == before  # untouched
        hs.plugin_sync_apply_all(p)
        backups = list(p.backups.rglob("settings.json"))
        assert len(backups) == 1 and json.loads(backups[0].read_text()) == json.loads(before)
        cc = json.loads((t / "cc" / "settings.json").read_text())
        assert cc["theme"] == "dark"  # unrelated keys preserved (cc untouched here)


def test_plugin_sync_apply_skips_codex_unknown_and_creates_settings():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _plugin_paths(t)
        man = hs.load_manifest(p.manifest)
        man["plugins"]["pony@mkt"]["targets"] = ["cx", "nope", "cp"]
        hs.save_manifest(p.manifest, man)
        (t / "cp" / "settings.json").unlink()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = hs.plugin_sync_apply_all(p)
        assert changes == ["plugin:pony@mkt -> cp"]
        assert "cx" in err.getvalue() and "nope" in err.getvalue()
        cp = json.loads((t / "cp" / "settings.json").read_text())
        assert cp["enabledPlugins"]["pony@mkt"] is True
```

- [ ] **Step 2: Verify failure**

- [ ] **Step 3: Implementation**

```python
def plugin_sync_apply_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest).get("plugins", {})
    changes: list[str] = []
    pending: dict[str, dict] = {}
    for key, cfg in sorted(man.items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        mname = key.split("@", 1)[1] if "@" in key else key
        for t in targets:
            if t not in paths.harness_skills or paths.harness_types[t] != "claude":
                print(f"warning: plugin '{key}' targets non-claude or unknown "
                      f"harness '{t}' — skipping", file=sys.stderr)
                continue
            settings = pending.get(t)
            if settings is None:
                settings = read_settings(_harness_base(paths, t) / "settings.json")
            known = _known_marketplaces(paths, t)
            need_flag = settings.get("enabledPlugins", {}).get(key) is not True
            need_mkt = cfg.get("marketplace") is not None and mname not in known \
                and mname not in settings.get("extraKnownMarketplaces", {})
            if not need_flag and not need_mkt:
                continue
            changes.append(f"plugin:{key} -> {t}")
            if dry_run:
                continue
            if need_flag:
                settings.setdefault("enabledPlugins", {})[key] = True
            if need_mkt:
                settings.setdefault("extraKnownMarketplaces", {})[mname] = \
                    {"source": cfg["marketplace"]}
            pending[t] = settings
    for h, settings in pending.items():
        path = _harness_base(paths, h) / "settings.json"
        if path.exists():
            backup = (paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S")
                      / h / "_plugins" / path.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")
    return changes
```

- [ ] **Step 4: Both interpreters pass**
- [ ] **Step 5: Commit** — `feat: plugin-sync apply with surgical settings writes`

### Task 4: CLI wiring + docs

**Files:** modify `harness_sync.py` (argparse + cmd functions), `CLAUDE.md`,
`README.md` (commands section, if present), test `test_harness_sync.py`
(CLI smoke via `hs.main([...])`).

**Interfaces:**
- Consumes: Tasks 1–3 functions, `_prompt`, `_prompt_targets`.
- Produces: `plugins sync-list|sync-adopt|sync-apply [--dry-run]`.

- [ ] **Step 1: Failing CLI test**

```python
def test_cli_plugins_sync_apply_dry_run(monkey_free_tmp=None):
    with tempfile.TemporaryDirectory() as tmp:
        p = _plugin_paths(Path(tmp))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hs.cmd_plugin_sync_apply(p, dry_run=True)
        assert "[dry-run] plugin:pony@mkt -> cp" in out.getvalue()
```

- [ ] **Step 2: Verify failure**

- [ ] **Step 3: Implementation** — cmd trio mirroring `cmd_mcp_*`
  (list prints per-claude-harness columns with `*` suffix when
  enabled-but-not-installed plus footnote; adopt iterates rows with
  untracked/drift cells, prompts source + claude-type targets), and in
  `main()`'s `plugins` subparser: `sync-list`, `sync-adopt`,
  `sync-apply` with `--dry-run`, dispatched in the `plugins` branch.

```python
def cmd_plugin_sync_list(paths: Paths) -> None:
    names = _claude_harnesses(paths)
    rows = plugin_sync_states(paths)
    if not rows:
        print("no plugins found")
        return
    w = {h: max(len(h), 10) for h in names}
    print(f"{'PLUGIN':40} {'REPO':5} " + " ".join(f"{h:{w[h]}}" for h in names))
    starred = False
    for r in rows:
        cells = []
        for h in names:
            cell = r[h]
            if cell in ("synced", "untracked") and not r["installed"][h]:
                cell += "*"
                starred = True
            cells.append(f"{cell:{w[h]}}")
        print(f"{r['name']:40} {'yes' if r['repo'] else 'no':5} " + " ".join(cells))
    if starred:
        print("* enabled but not yet installed — launch that account to finish")


def cmd_plugin_sync_adopt(paths: Paths) -> None:
    names = _claude_harnesses(paths)
    for row in plugin_sync_states(paths):
        key = row["name"]
        available = [h for h in names if row[h] in ("untracked", "drift")]
        if not available:
            continue
        status = ", ".join(f"{h}:{row[h]}" for h in names)
        print(f"\nPlugin: {key}  ({status})")
        if input("  adopt? [y/N]: ").strip().lower() != "y":
            continue
        source = available[0] if len(available) == 1 else _prompt("  source", available)
        targets = _prompt_targets(names)
        plugin_sync_adopt(paths, key, source, targets)
        print(f"  adopted {key} from {source} -> {targets}")


def cmd_plugin_sync_apply(paths: Paths, dry_run: bool) -> None:
    changes = plugin_sync_apply_all(paths, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    if not changes:
        print("nothing to do")
        return
    for c in changes:
        print(f"{prefix}{c}")
```

- [ ] **Step 4: Both interpreters pass; update CLAUDE.md (Commands +
  Architecture blurbs) and README commands section**
- [ ] **Step 5: Commit** — `feat: plugins sync-* CLI + docs`

## Self-Review

- Spec coverage: states ✔ (T1), adopt+marketplace source ✔ (T2), surgical
  apply/backup/dry-run/codex-skip/create-missing ✔ (T3), CLI+docs ✔ (T4),
  installed marker ✔ (T1 data + T4 rendering). No prune (spec: none).
- No placeholders; signatures consistent across tasks.
