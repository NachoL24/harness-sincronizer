# Two-Way Sync with Conflict Detection (#5)

**Date:** 2026-07-02
**Issue:** #5 (v1 non-goal, final backlog item)

## Model

One-way `apply` (repo → harness, repo wins) stays the default. Two-way sync is
**opt-in by invocation**: a new `sync` command that can also pull harness-side
edits back into the repo, and refuses to guess when both sides changed.

Scope: all file-based asset kinds (`KINDS`: skills, agents, commands,
instructions, cosmetic kinds). Config domains (mcp, plugins, settings) stay
one-way — their sync unit is a JSON value, not a hashed file tree, and the
issue's scope is asset content.

## Last-synced state

`.sync-state.json` at the repo root (gitignored runtime data, next to
`manifest.json`):

```json
{"skills": {"branch-pr": {"claude": "<sha256>", "codex": "<sha256>"}}}
```

The recorded hash is the content hash both sides shared the last time they
were known equal. It is recorded (per kind/name/harness) whenever the tool
itself makes them equal or observes them equal:

- `apply_skill` after a push (and when it observes dst already equal)
- `refresh_skill` after a pull (for the source harness)
- `adopt_skill` / `import_skill` for the source harness
- `sync` for every pair it pushes, pulls, or observes in sync

This keeps baselines fresh even for users who never run `sync`, so the first
two-way run doesn't drown in false conflicts.

## Detection (per tracked asset × target harness)

Let `R` = repo hash, `H` = harness hash, `L` = last-synced hash (`None` when
missing; an absent file also hashes to `None`):

| Condition | Meaning | Action |
|---|---|---|
| `R == H` | in sync | record `L = R` |
| `R != H`, `H == L` | repo-only change | **push** (backup harness copy) |
| `R != H`, `R == L` | harness-only change | **pull** (backup repo copy) |
| `R != H`, both differ from `L` (incl. `L` missing) | conflict / unattributable | **report, touch nothing** |

Additional guards:

- Repo copy missing for a tracked asset → never treated as "push a deletion":
  reported as a conflict-level warning (`untrack` or re-adopt is the fix).
  Deletion is only ever explicit (`untrack`, `apply --prune`).
- Pull reuses `refresh_skill` (repo copy backed up, manifest untouched). After
  a pull the updated repo hash is used for the remaining targets of that
  asset in the same run, so a pull from account A followed by a push to stale
  account B works in one `sync`.
- Two harnesses both changed to *different* contents → the second one is a
  conflict against the freshly pulled repo copy (both-changed rule) — exactly
  right.
- `--dry-run` reports planned pushes/pulls/conflicts and writes nothing (state
  file included).

## Conflict resolution

`resolve <kind:name> <winner>` where winner is `repo` or a harness name:

- winner = `repo` → push repo copy to all targets (backups as usual)
- winner = harness `X` → `refresh_skill` from `X` (repo backup), then push to
  the remaining targets

Both paths end by recording last-synced state for every touched pair. Nothing
is ever merged automatically; resolution is always an explicit pick.

## CLI

```
python3 harness_sync.py sync [--dry-run]
python3 harness_sync.py resolve <kind:name> <repo|harness>
```

Output: one line per action (`push kind:name -> harness`,
`pull kind:name <- harness`, `conflict kind:name : harness (resolve with ...)`),
summary counts at the end. `sync` exits 1 when conflicts remain (scriptable).

## Testing

Both interpreters. Coverage: state I/O; baseline recording via
apply/refresh/adopt; repo-only push; harness-only pull (repo backup); pull
then push to stale second harness in one run; both-changed conflict (nothing
written, exit path); missing-baseline diff → conflict, equal → baselined;
repo-missing guard; resolve repo and resolve harness; dry-run inertness.
