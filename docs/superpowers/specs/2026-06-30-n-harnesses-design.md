# N Configurable Harnesses — Design (Issue #1)

Date: 2026-06-30
Status: Approved

## Goal

Replace the hardcoded two-target model (`HARNESSES = ("claude", "codex")`) with
a **configurable registry of N harnesses**, so that multiple Claude accounts and
Codex can be sync targets simultaneously. This is the architectural backbone
that later issues (#7 plugin skills, #9 agents/commands, #2 MCP, #3 instructions)
build on.

Scope stays **skills-only** — this issue only generalizes the harness set, not
the asset kinds.

## Registry

New file `harnesses.json` at the repo root:

```json
{
  "harnesses": {
    "claude":       { "base": "~/.claude" },
    "claude-perso": { "base": "~/.claude-perso" },
    "codex":        { "base": "~/.codex" }
  }
}
```

- `base` is the harness config directory. The skills path is **derived** as
  `<base>/skills`. `~` is expanded.
- Future asset kinds will derive `<base>/agents`, `<base>/commands`, etc. — not
  built here, but the base-dir shape sets it up without a registry migration.
- Insertion order in the file = column order in `status`.
- No `type` field yet (added when MCP/instructions need format awareness).

## Registry resolution & backward compatibility

`load_harnesses(repo_root) -> dict[str, Path]` (name → expanded base dir):

- **Registry absent** → built-in defaults, preserving today's behavior exactly:
  - `claude` → `$CLAUDE_CONFIG_DIR` or `~/.claude`
  - `codex` → `$CODEX_HOME` or `~/.codex`
  Existing manifests (`targets: ["claude","codex"]`) keep working unchanged.
- **Registry present** → it fully defines the harness set. **Environment
  variables are NOT consulted** (explicit > implicit). This replaces the
  per-run `CLAUDE_CONFIG_DIR=...` trick: each account is a permanent column.
- **Invalid JSON** → fail with a clear error. Do NOT fall back silently.

`resolve_paths` derives `harness_skills = {name: base/"skills"}` for every
registered harness.

## Commands

Existing: `status`, `adopt`, `apply [--dry-run]` — generalized to iterate the
registry instead of the fixed tuple.

New `harness` command group (manage the registry):

- `harness list` — print the resolved registry (name → base → derived skills
  path), so the user can confirm what the tool sees.
- `harness add <name> <base>` — add or update an entry, then write
  `harnesses.json`.
  - **Seeding rule:** if `harnesses.json` does not exist yet, create it seeded
    with the current effective defaults (`claude`, `codex` from env/defaults)
    **plus** the new entry — so existing harnesses are not lost.
- `harness remove <name>` — remove an entry and write `harnesses.json`.
  - Removing a harness does not touch manifests. If a manifest still targets a
    removed harness, that is handled by the "unknown target" rule below.

## Generalized behavior

- `compute_states` iterates the registry keys; each row carries one state per
  registered harness (`synced` / `drift` / `untracked` / `absent`).
- `cmd_status` renders **dynamic columns** — `SKILL` plus one column per
  harness. Column width = max(harness name length, longest state token).
- `cmd_adopt`:
  - **source** = choose among the harnesses where the skill is `untracked` or
    `drift` (auto-picked when only one).
  - **targets** = multi-select among all registered harness names plus
    `ignore`. The old `both` shortcut is removed (meaningless with N); accept a
    comma-separated list of names or the keyword `all`.
- `apply_skill` / `apply_all` iterate registry names. A target is valid if it is
  a registered name; `ignore` skips.

## Manifest

Schema unchanged. `targets` references any registered harness name. Existing
`["claude","codex"]` manifests remain valid.

**Unknown target rule:** if a manifest target names a harness not in the
registry, `apply` warns and skips that target (does not crash); other targets
for the same skill still apply.

## Error handling

- Base dir that doesn't exist → `scan` returns `{}` (skills report `absent`),
  the graceful behavior already observed with a non-existent config dir.
- Invalid `harnesses.json` → clear error, no silent fallback.
- Unknown manifest target → warn + skip, continue.

## Testing (stdlib, extend `test_harness_sync.py`)

- `load_harnesses`: present (with `~` expansion) vs absent (env-derived
  defaults).
- 3-harness `compute_states` scenario (`claude`, `claude-perso`, `codex`).
- `harness add` seeding rule: first add with no file creates file with defaults
  + new entry.
- `harness remove` deletes an entry.
- `adopt` with N targets writes the correct manifest.
- `apply` pushes to 3 harnesses in one run.
- Manifest target referencing an unknown harness → skipped with warning, other
  targets applied.

## Non-goals (this issue)

- Asset kinds beyond skills (agents/commands = #9).
- `type` field for format-aware sync (MCP/instructions = #2/#3).
- Concurrency / locking of the registry file.
