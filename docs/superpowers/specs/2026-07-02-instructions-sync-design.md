# Instruction-File Sync (CLAUDE.md ↔ AGENTS.md) — Design (Issue #3)

Date: 2026-07-02
Status: Approved

## Goal

Sync the **global instruction file** across harnesses: Claude-type harnesses
read `<base>/CLAUDE.md`, Codex-type read `<base>/AGENTS.md`. Same intent,
different filename — a natural fit for the asset-kind engine with one
extension: **fixed-name kinds**.

## Model

```python
KINDS["instructions"] = {
    "asset": "file", "claude_only": False,
    "names": {"claude": "CLAUDE.md", "codex": "AGENTS.md"},
}
```

- A fixed-name kind has exactly **one logical asset per harness**, canonical
  name `global.md`, stored in the repo at `instructions/global.md`.
- Per harness, the physical path is `<base>/<names[type]>` (the harness BASE,
  not a subdir).
- v1 is a **plain copy** — no per-harness templating/sections (issue #3's open
  question resolved as: copy verbatim; harness-specific sections can layer
  later). Addressed as `instructions:global.md` in CLI/TUI.

## Engine extension (small, localized)

- `harness_asset_path(paths, h, kind, name) -> Path | None` — resolves the
  physical path for any kind: `None` for claude_only+codex; `base/names[type]`
  for fixed-name kinds; `harness_kind_dir/name` otherwise. `apply_skill`,
  `adopt_skill`, `refresh_skill`, `prune_all` switch to it.
- `_harness_kind_scan(paths, h, kind) -> dict[name, hash]` — fixed-name kinds
  yield `{"global.md": hash}` when the file exists; others delegate to
  `scan_kind`. `compute_states` uses it.
- Repo side needs nothing: `instructions/global.md` is a `*.md` file, already
  matched by the file-kind scan.

Everything else (states, adopt, apply, untrack, refresh, prune, backups,
prefix addressing, CLI walks, TUI) is inherited from the kind engine.

## Safety note (real-data caveat, documented)

The user's real `~/.claude/CLAUDE.md`, `~/.claude-perso/CLAUDE.md` and
`~/.codex/AGENTS.md` have **different content**. Adopting one and targeting
the others overwrites them (with backup, as always). This is opt-in per
adopt/targets — nothing syncs until explicitly adopted.

## Testing

- `harness_asset_path`: fixed-name resolution per type; claude_only None
  unchanged.
- States: claude with CLAUDE.md + codex with AGENTS.md and equal content →
  both `synced` against an adopted repo copy; differing → `drift`.
- Adopt from claude (reads `CLAUDE.md`) → repo `instructions/global.md` +
  manifest `instructions` section; apply to codex writes `<base>/AGENTS.md`
  (backup when overwriting); idempotent.
- Untrack/refresh on `instructions:global.md`.

## Non-goals

Per-project instruction files; templated/per-harness sections; `GEMINI.md`
(add a name mapping when a gemini type exists).
