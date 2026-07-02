# Untrack + Opt-in Pruning — Design (Issue #4)

Date: 2026-07-01
Status: Approved (untrack semantics chosen by default recommendation — user AFK;
revisit if objected)

## Goal

Complete the tracking lifecycle. Today skills can only enter management
(`adopt`) and be pushed (`apply`); leaving requires hand-editing
`manifest.json`, and nothing can ever be removed from a harness. This change
adds both exits, keeping the v1 safety posture: deletion is explicit, opt-in,
and always backed up.

## Operations

### 1. `untrack <skill>` (repo side)

Stop managing a skill entirely:
- Remove its entry from `manifest.json`.
- Back up the repo copy to `.harness-sync-backups/<ts>/repo/<name>/`, then
  delete `skills/<name>/` from the repo.
- Harness copies are **never touched** by untrack.

Rationale for deleting the repo copy: `skills/` is gitignored, so a leftover
orphan dir would reappear in `status` as a stale repo-only entry; the backup
(plus the still-present harness copies) makes untrack fully recoverable via
re-adopt. "Keep tracked but push nowhere" remains expressible with
`targets: ["ignore"]` — that is a different operation and is unaffected.

CLI: `python3 harness_sync.py untrack <name>` (errors clearly if the name is
not in the manifest).

### 2. `apply --prune` (harness side, opt-in)

Delete from harnesses what the manifest no longer targets there:
- For each manifest skill and each registered harness `h`: if `h` is not in
  the skill's `targets` and `<harness_skills[h]>/<name>` exists, the copy is
  pruned (backup first, then delete).
- **`ignore` skips pruning entirely**: `targets: ["ignore"]` means "tracked but
  intentionally left alone" — prune never touches ignore'd skills anywhere.
- **Foreign safety**: skills not present in the manifest are never deleted,
  under any flag. Only explicitly de-targeted, tracked skills are pruned.
- Off by default. `apply --dry-run --prune` lists prospective deletions
  (`<name> -x <harness>` lines, distinct from push lines `<name> -> <harness>`)
  without performing them.

## Core functions (pure, path-injected)

- `backup_skill(paths, label, name, src)` — shared backup helper
  (`backups/<ts>/<label>/<name>`); refactor the inline backup in `apply_skill`
  to use it; `untrack` uses label `"repo"`, prune uses the harness name.
- `untrack_skill(paths, name) -> None` — manifest removal + repo backup+delete.
  Raises `KeyError` if the skill is not tracked.
- `prune_all(paths, dry_run=False) -> list[str]` — returns `"<name> -x <h>"`
  change strings; iterates manifest × registry with the rules above.

CLI composition: `apply --prune` runs `apply_all` then `prune_all` and prints
both change sets (dry-run respected by both).

## TUI integration

- **Status tab**: binding `u` — untrack the skill under the cursor. Only acts
  when that skill is tracked (repo=yes); logs the outcome to Activity. The
  operation is backed up and harness-safe, so no modal confirmation in v1.
- **Apply tab**: a `Checkbox("also prune de-targeted skills")` above the Apply
  button. The pending (dry-run) panel includes prune lines when checked;
  toggling refreshes the panel. "Apply now" honors the checkbox.

## Error handling

- `untrack` of an unknown skill: clear error (CLI: message + exit 1; TUI: log
  line), nothing modified.
- Prune of a path that vanished mid-run: skip silently (nothing to delete).
- All deletions preceded by backup; backup failure aborts that item's deletion.

## Testing (stdlib, extend `test_harness_sync.py`)

- `untrack_skill`: manifest entry gone, repo dir gone, backup exists, harness
  copies untouched; unknown name raises.
- `prune_all`: de-targeted skill removed from harness with backup; `ignore`
  skill untouched everywhere; foreign (unmanifested) harness skill untouched;
  `dry_run=True` reports without deleting.
- `apply_skill` still passes after the `backup_skill` refactor.
- Guarded TUI test: pilot presses `u` on a tracked row → manifest entry
  removed.

## Non-goals

- Bulk untrack / untrack-by-plugin.
- Pruning untracked or foreign skills (never).
- Deleting backups (they accumulate; cleanup is manual).
