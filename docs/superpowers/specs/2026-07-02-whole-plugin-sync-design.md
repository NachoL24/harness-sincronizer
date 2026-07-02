# Whole-Plugin Sync Between Claude Accounts (#14)

**Date:** 2026-07-02
**Issue:** #14 (Phase 2 of plugin sync; Phase 1 = plugin skills → repo, shipped in PR #15)

## Decision: config-sync, not file copy

Claude Code plugin install state lives in three layers:

1. `<base>/settings.json` — `enabledPlugins` (`"plugin@marketplace": bool`) and
   `extraKnownMarketplaces` (`"name": {"source": {...}}`). **Declarative layer.**
2. `<base>/plugins/known_marketplaces.json` — materialized marketplace clones.
3. `<base>/plugins/installed_plugins.json` + `plugins/cache/` — install records
   and cached plugin trees, including absolute `installPath`s and commit SHAs.

Layers 2–3 are machine-managed: Claude Code regenerates them from layer 1
(verified against docs — the install step "applies on every path that loads
plugins"; a declared-but-missing plugin surfaces the exact
`claude plugin install` command on launch). Copying cache trees would fight the
auto-updater and require rewriting absolute paths.

**We sync layer 1 only.** Apply writes the declaration; Claude Code completes
the install on the target account's next launch.

No version pinning: sync tracks presence + enablement, never versions (the
auto-updater owns versions).

## Manifest

New top-level section `"plugins"` (sibling of `"mcp"`), keyed by the full
plugin id:

```json
"plugins": {
  "ponytail@ponytail": {
    "targets": ["claude", "claude-perso"],
    "marketplace": {"source": "github", "repo": "DietrichGebert/ponytail"}
  }
}
```

`marketplace` is the source dict copied verbatim from the source harness's
`known_marketplaces.json[<name>]["source"]` (marketplace name = part after
`@`). May be `null` if the source harness no longer knows the marketplace —
apply then only sets `enabledPlugins` and warns.

## States (MCP vocabulary)

Per tracked plugin, per **claude-type** harness (codex-type harnesses have no
plugin system and are excluded from rows and target prompts):

- `synced` — `enabledPlugins[key]` is `true`
- `drift` — key present but `false` (explicitly disabled on that account)
- `untracked` — enabled in the harness, not in the manifest
- `absent` — key not present

`sync-list` also shows an `INSTALLED` column (key present in
`installed_plugins.json`) so a declared-but-not-yet-installed plugin is
visible ("launch that account to finish the install").

## Apply semantics (surgical, idempotent)

For each tracked plugin, each target:

- Skip + warn: unknown harness name, or codex-type harness.
- Skip silently when `enabledPlugins[key]` is already `true` and the
  marketplace is known to the target.
- Otherwise, in the target's `settings.json` (created if absent):
  - set `enabledPlugins[key] = true`
  - add `extraKnownMarketplaces[<name>] = {"source": ...}` **only if** the
    target doesn't already know the marketplace (checked against both its
    `known_marketplaces.json` and its existing `extraKnownMarketplaces`)
- Only those two keys are ever touched; all other settings keys round-trip
  untouched. Backup of `settings.json` to
  `.harness-sync-backups/<ts>/<harness>/_plugins/settings.json` before write.
- Explicit `false` (user disabled) is overwritten to `true` only when the
  plugin targets that harness — that is the declared desired state.
- No prune in this iteration (same as MCP). De-targeting simply stops
  managing; it never disables anything.
- `--dry-run` prints pending changes, writes nothing.

## Adopt

`plugins sync-adopt` iterates states rows with any `untracked`/`drift` cell,
asks per plugin (same prompt flow as `mcp adopt`): source harness (only if
ambiguous) + targets (claude-type harnesses only, or `ignore`). Records
manifest entry with the marketplace source resolved from the source harness.

## CLI

Under the existing `plugins` group (which keeps `list`/`adopt` for Phase 1
plugin-skills):

```
python3 harness_sync.py plugins sync-list
python3 harness_sync.py plugins sync-adopt
python3 harness_sync.py plugins sync-apply [--dry-run]
```

Pure JSON — no tomllib, so this runs on Python 3.9 (unlike `mcp`). No TUI in
this PR (precedent: MCP shipped CLI-first in #2, TUI tab followed in #21).

## Reuse note for #10

The surgical read-modify-write of specific `settings.json` keys introduced
here (`read_settings` / write-with-backup) is the primitive #10
(hooks & settings sync) will build on.

## Testing

Stdlib runner, hermetic tmp dirs, both interpreters (`python3` = 3.9 and
`python3.12`):

- states: synced/drift/untracked/absent + codex excluded
- adopt: manifest entry with marketplace source captured
- apply: sets flag, adds marketplace only when unknown, preserves unrelated
  settings keys, creates settings.json when absent, backs up, idempotent,
  dry-run writes nothing, warns on codex/unknown targets
