# PyPI Packaging & Data-Dir Decoupling (#30)

**Date:** 2026-07-02
**Issue:** #30

## Goal

```bash
pipx install harness-sync    # or: uvx harness-sync, pip install harness-sync
harness-sync status
```

Name `harness-sync` verified free on PyPI. Channel decision: PyPI only (an
npm wrapper would still spawn python3, so it removes no dependency).

## The real change: home (data dir) resolution

Today `main()` resolves the store from `Path(__file__).resolve().parent` —
under site-packages that would put `manifest.json` inside the installed
package. New resolution order, implemented in `default_home(script_dir=None)`:

1. `$HARNESS_SYNC_HOME` (expanduser'd) — explicit override, wins always.
2. **Checkout mode**: if the directory containing `harness_sync.py` has any
   store/dev marker (`manifest.json`, `harnesses.json`, `skills/`, `.git`),
   it IS the home — existing clone-based workflows keep working unchanged.
3. `~/.harness-sync` — the installed default. `main()` creates it
   (`mkdir -p`) after resolution so first-run `adopt` can write the manifest.

`script_dir` is parameterized for tests only; default is the module's own
directory. `resolve_paths(root)` keeps its signature — only `main()` (CLI and
TUI launch) switches from `Path(__file__).parent` to `default_home()`.

## Packaging (`pyproject.toml`)

- Backend: setuptools (`py-modules = ["harness_sync", "harness_tui"]` — the
  repo stays two flat modules, no src/ churn).
- `[project]`: name `harness-sync`, version `1.0.0` (backlog complete = honest
  v1), `requires-python = ">=3.9"` (core; the `mcp` subcommand keeps its lazy
  3.11+ gate at runtime), license MIT + classifier.
- `[project.scripts] harness-sync = "harness_sync:main"` — the generated
  wrapper does `sys.exit(main())`, and `main()` already returns exit codes.
- `[project.optional-dependencies] tui = ["textual"]` — core stays
  zero-dependency; `pip install "harness-sync[tui]"` enables the dashboard.
- `requirements.txt` stays as dev convenience.

## LICENSE

MIT, copyright Nacho Lances — required for publishing; flagged to the
maintainer for veto since it changes the repo's legal terms.

## Publishing

The PR makes the project buildable/installable and documents the release
step. The actual upload needs maintainer credentials and is run by the
maintainer (or a later trusted-publishing workflow):

```bash
python3.12 -m build
python3.12 -m twine upload dist/*
```

## Verification

- Unit tests for the three `default_home` modes (env override, checkout
  markers, installed fallback).
- End-to-end: `pip install .` into a scratch venv, then run `harness-sync
  status` from an unrelated cwd with `HARNESS_SYNC_HOME` pointing at a scratch
  store — proves entry point, exit codes and data-dir decoupling together.
- Both interpreter suites stay green.

## Docs

README gets an Install section (pipx/uvx/pip, `[tui]` extra, data-dir rules);
CLAUDE.md documents `default_home` and the packaging layout.
