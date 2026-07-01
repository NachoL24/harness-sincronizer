# TUI Dashboard (textual) — Design (Issue #12)

Date: 2026-07-01
Status: Approved

## Goal

A full-screen terminal dashboard (textual) over the existing CLI: view skill
states, adopt standalone skills and whole plugins with checkbox multi-select,
review and apply pending changes, and manage the harness registry — without
touching the core sync logic.

## Decisions (made during brainstorming)

- **Library: `textual`** (full-screen app), not rich-only or rich+questionary.
- **Scope: all 5 views**, including harness registry management.
- **Batch targets:** select multiple items with checkboxes, then choose targets
  ONCE for the whole batch — no per-item prompting.
- Launch via a new `tui` subcommand with lazy import and a clear fallback
  message when `textual` is not installed.

## Architecture (core stays intact)

- **New file `harness_tui.py`** — the textual app. It imports `textual` and
  calls the core's pure functions only: `compute_states`, `discover_plugins`,
  `adopt_plugin`, `import_skill`, `apply_all`, `harness_add`, `harness_remove`,
  `resolve_paths`. **No business logic lives in the TUI.**
- **`harness_sync.py`** gains only the `tui` subcommand. It lazy-imports
  `harness_tui` inside the command handler; on `ImportError` it prints
  `error: the TUI requires textual — pip install textual` to stderr and returns
  exit code 2. The core module keeps zero third-party imports.
- The existing CLI (`status/adopt/apply/harness/plugins`) is untouched and
  remains the scriptable fallback.
- After any registry mutation (add/remove) the app re-runs `resolve_paths` so
  all views reflect the new harness set.

## Views (tabs)

1. **Status** — read-only N-harness table. State colors: `synced` green,
   `drift` yellow, `untracked` cyan, `absent` dim. Key `r` refreshes
   (re-runs `compute_states`).
2. **Adopt** — checkbox list of adoptable skills (state `untracked` or `drift`
   in any harness). After selection: if any skill exists in more than one
   harness, pick the source harness; then pick batch targets; then adopt via
   `import_skill` per skill. Refreshes after adopting.
3. **Plugins** — checkbox list of discovered plugins (`plugin`, `harness`,
   skill count, in-repo count). Batch targets once; adopts whole plugins via
   `adopt_plugin`; shows adopted/skipped summary (collisions skip with
   warning, as in the CLI).
4. **Apply** — shows pending changes (`apply_all(dry_run=True)`). A confirm
   action runs `apply_all(dry_run=False)` and shows the applied changes (or
   "nothing to do").
5. **Harness** — table of the resolved registry (name, base, skills path);
   inputs to `add` (name + base) and `remove` (selected row). Mutations write
   `harnesses.json` via `harness_add` / `harness_remove`.

Target selection (Adopt/Plugins) offers the registered harness names plus
`ignore`, mirroring `_prompt_targets` semantics.

## Dependency & convention change

- Add `requirements.txt` containing `textual`.
- Update `CLAUDE.md` convention: **stdlib-only core**; an optional UI dependency
  (`textual`) is allowed in the presentation layer (`harness_tui.py`). The core
  must never import it.

## Error handling

- `textual` missing → `tui` command prints install hint, exit 2; everything
  else works.
- Invalid `harnesses.json` → same behavior as CLI (clear error at startup).
- Apply/adopt errors surface in the app's status bar/log panel rather than
  crashing the app.

## Testing

- Core unchanged → existing stdlib suite stays green and remains the unit-test
  surface.
- **One guarded smoke test** in `test_harness_sync.py`: if `textual` imports,
  boot the app via `App.run_test()` (Pilot) against a temp repo and assert the
  app mounts and the Status view renders rows. If `textual` is missing, the
  test is a no-op (prints SKIP-equivalent PASS). The TUI is not unit-tested
  beyond this.

## Non-goals

- Editing skill contents from the TUI.
- Configurable themes/colors.
- Mouse-specific design (textual's defaults apply).
- Replacing the CLI — it stays as the scriptable path.
