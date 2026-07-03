# PyPI Packaging (#30) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pipx install harness-sync` works; running from a checkout keeps
current behavior.

**Architecture:** One new pure function `default_home()` used by `main()`;
`pyproject.toml` (setuptools, py-modules) + LICENSE + docs. No other code
paths change.

**Tech Stack:** stdlib; setuptools backend; both interpreter suites.

## Global Constraints

- Core stays zero-dependency; textual only via `[tui]` extra.
- `requires-python >= 3.9`; mcp's lazy 3.11 gate untouched.
- English code/comments/commits; TDD.

---

### Task 1: `default_home()` + `main()` switch

**Files:** modify `harness_sync.py` (new function near `resolve_paths`;
`main()` lines using `Path(__file__)`), test `test_harness_sync.py`

**Interfaces:**
- Produces: `default_home(script_dir: Path | None = None) -> Path`.

- [ ] **Step 1: Failing test**

```python
def test_default_home_resolution_modes():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        # 1. env override wins always (and expands ~)
        os.environ["HARNESS_SYNC_HOME"] = str(t / "store")
        try:
            assert hs.default_home(t / "anywhere") == t / "store"
        finally:
            del os.environ["HARNESS_SYNC_HOME"]
        # 2. checkout mode: any store/dev marker makes script_dir the home
        co = t / "checkout"
        co.mkdir()
        (co / "harnesses.json").write_text("{}")
        assert hs.default_home(co) == co
        # 3. installed mode: bare dir (site-packages) -> ~/.harness-sync
        sp = t / "site-packages"
        sp.mkdir()
        assert hs.default_home(sp) == Path.home() / ".harness-sync"
```

- [ ] **Step 2: RED** (`AttributeError: default_home`)
- [ ] **Step 3: Implementation** (after `resolve_paths`)

```python
def default_home(script_dir: Path | None = None) -> Path:
    env = os.environ.get("HARNESS_SYNC_HOME")
    if env:
        return Path(env).expanduser()
    if script_dir is None:
        script_dir = Path(__file__).resolve().parent
    markers = ("manifest.json", "harnesses.json", "skills", ".git")
    if any((script_dir / m).exists() for m in markers):
        return script_dir  # running from a checkout that is the store
    return Path.home() / ".harness-sync"
```

In `main()`: replace both `Path(__file__).resolve().parent` computations with
one `home = default_home()` before the try, `home.mkdir(parents=True,
exist_ok=True)`, then `resolve_paths(home)` / `tui_run(home)`.

- [ ] **Step 4: GREEN both interpreters**
- [ ] **Step 5: Commit** — `feat: resolve data dir via default_home (env/checkout/installed)`

### Task 2: pyproject + LICENSE + docs

**Files:** create `pyproject.toml`, `LICENSE`; modify `README.md` (Install
section after the intro), `CLAUDE.md` (data-dir + packaging notes)

**Interfaces:**
- Produces: console script `harness-sync = harness_sync:main`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "harness-sync"
version = "1.0.0"
description = "Selective sync of skills, agents, commands, MCP servers, plugins and settings between AI coding harnesses (Claude Code, Codex)"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.9"
authors = [{name = "Nacho Lances"}]
keywords = ["claude-code", "codex", "skills", "sync", "dotfiles", "mcp"]
classifiers = [
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "Topic :: Utilities",
]

[project.urls]
Homepage = "https://github.com/NachoL24/harness-sincronizer"
Issues = "https://github.com/NachoL24/harness-sincronizer/issues"

[project.scripts]
harness-sync = "harness_sync:main"

[project.optional-dependencies]
tui = ["textual"]

[tool.setuptools]
py-modules = ["harness_sync", "harness_tui"]
```

- [ ] **Step 2: LICENSE** — standard MIT text, `Copyright (c) 2026 Nacho Lances`.
- [ ] **Step 3: Docs** — README Install section (pipx/uvx/pip/[tui] +
  data-dir resolution rules + release command); CLAUDE.md notes.
- [ ] **Step 4: Commit** — `feat: pyproject, MIT license and install docs`

### Task 3: End-to-end install verification

**Files:** none (scratch venv under the session scratchpad)

- [ ] **Step 1: Build/install into scratch venv**

```bash
python3.12 -m venv "$SCRATCH/venv"
"$SCRATCH/venv/bin/pip" install --quiet .
```

(If build isolation cannot fetch setuptools offline, retry with
`--no-build-isolation`.)

- [ ] **Step 2: Run from unrelated cwd with scratch store**

```bash
cd / && HARNESS_SYNC_HOME="$SCRATCH/store" "$SCRATCH/venv/bin/harness-sync" status
cd / && HARNESS_SYNC_HOME="$SCRATCH/store" "$SCRATCH/venv/bin/harness-sync" sync --dry-run
```

Expected: status table over default claude/codex harness columns (env
override for store only, real config read-only); sync prints
"everything in sync" (empty manifest), exit 0. Confirm
`$SCRATCH/store` was created.

- [ ] **Step 3: Suites green on both interpreters; commit any fixes**

## Self-Review

- Spec coverage: home resolution + mkdir ✔ (T1), packaging/license/docs ✔
  (T2), end-to-end proof incl. console-script exit codes ✔ (T3).
- No placeholder steps; `default_home` signature consistent across tasks.
