# Cosmetic Asset Kinds — Design + Plan (Issue #11)

Date: 2026-07-02
Status: Approved

## Goal

Sync Claude cosmetic/preference assets between Claude accounts via four new
KINDS entries (all `claude_only`):

| Kind | Model | Location | Pattern/logical |
|------|-------|----------|-----------------|
| `output-styles` | file dir | `<base>/output-styles/` | `*.md` |
| `themes` | file dir | `<base>/themes/` | `*.json` (measured: `gentleman.json`) |
| `statusline` | fixed file | `<base>/statusline-command.sh` | logical = filename |
| `keybindings` | fixed file | `<base>/keybindings.json` | logical = filename |

## Engine schema extensions (the whole change)

- Optional `"pattern"` on file kinds (default `"*.md"`): `scan_kind` globs it.
  `themes` sets `"*.json"`.
- Fixed-name kinds gain `"logical"` (the canonical asset name). `instructions`
  keeps `logical = "global.md"` (constant `FIXED_ASSET` preserved for
  back-compat); `statusline`/`keybindings` use their real filename as logical,
  with `names = {"claude": <filename>}` (claude_only ⇒ the codex mapping is
  never consulted).
- `scan_kind` handles fixed kinds on the repo side (`{logical: hash}` when
  `root/<logical>` is a file); `_harness_kind_scan`/`harness_asset_path`
  switch from the global constant to `spec["logical"]`.

Everything else (states/adopt/apply/untrack/refresh/prune, prefixed
addressing, CLI, TUI, backups) is inherited unchanged.

## Never-sync reminder (unchanged non-goals)

`sessions/`, `history.jsonl`, caches, telemetry, `projects/`, logs, memories —
per-machine state, never assets.

## Plan (TDD, single branch `feature/cosmetic-kinds`)

1. Tests: themes `*.json` scanned; statusline fixed-kind states across two
   claude harnesses + codex absent; adopt statusline from claude → repo
   `statusline/statusline-command.sh` + manifest; apply → claude-perso;
   roundtrip idempotent; instructions regression intact (FIXED_ASSET).
2. Implement schema keys + the three touchpoints (`scan_kind`,
   `_harness_kind_scan`, `harness_asset_path`).
3. Docs (README cosmetic section; CLAUDE.md kind table) + AGENTS.md re-sync.
4. Suites on 3.9/3.12; real smoke (`status | rg 'themes:|statusline'`);
   pipeline (push, PR closes #11, squash merge).
