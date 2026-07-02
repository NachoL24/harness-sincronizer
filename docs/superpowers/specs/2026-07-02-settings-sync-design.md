# Settings & Hooks Sync Between Claude Accounts (#10)

**Date:** 2026-07-02
**Issue:** #10

## Model: generic per-key settings sync

Hooks, permissions, and env are not special: they are all top-level keys of
`<base>/settings.json`. Rather than hardcoding a scope, the sync unit is **one
top-level settings key**. The user picks which keys to track at adopt time
(`hooks`, `permissions`, `env`, `statusLine`, `model`, ...). This answers the
issue's "which keys are in scope" question without baking in an answer.

Excluded keys: `enabledPlugins` and `extraKnownMarketplaces` — already owned
by the plugin-sync domain (#14). They never appear as adoptable settings keys.

Claude-type harnesses only (verified: Codex has no compatible hooks or
settings.json).

## Manifest

Top-level `"settings"` section, keyed by settings key name:

```json
"settings": {
  "hooks": {"targets": ["claude", "claude-perso"], "value": {...}},
  "statusLine": {"targets": ["claude", "claude-perso"],
                  "value": {"type": "command",
                            "command": "bash ${HARNESS_BASE}/statusline-command.sh"}}
}
```

`value` is the canonical, **account-neutral** copy of the key's value.

## Path canonicalization (`${HARNESS_BASE}`)

Real-world motivator: both accounts' `statusLine` currently point at
`/Users/nacho/.claude/statusline-command.sh` — the personal account references
the work account's file.

- **At adopt** every string inside the value gets occurrences of the source
  harness's base dir (absolute form, plus `~/`-abbreviated form when the base
  is under `$HOME`) replaced with the literal token `${HARNESS_BASE}`.
- **At apply** `${HARNESS_BASE}` is replaced with the target harness's
  absolute base dir.
- Paths pointing at a *different* account's base are foreign strings: they are
  copied verbatim (only the source's own base is canonicalized). Adopt from
  the account whose paths are self-referential.

## Referenced file sync (`settings-files/`)

After canonicalization, any string segment matching
`${HARNESS_BASE}/<rel-path>` whose `<source_base>/<rel-path>` exists as a file
is a **managed reference**:

- **Adopt** copies it to `<repo>/settings-files/<rel-path>` (flat by relative
  path, deduped across keys). A `${HARNESS_BASE}` ref with no file behind it
  is left as pure string substitution, with a warning.
- **Apply** copies `settings-files/<rel-path>` to `<target_base>/<rel-path>`
  when missing or hash-different (backup first).
- `settings-files/` is repo runtime data → added to `.gitignore` (like
  `skills/`, `manifest.json`).

## States

Per tracked key, per claude-type harness:

- `synced` — canonicalized harness value equals manifest value AND every
  referenced file exists on the harness with identical hash
- `drift` — key present but value or any referenced file differs
- `absent` — key missing from that harness's settings.json
- `untracked` — key present in a harness (and not excluded) but not in the
  manifest (these rows are the adopt candidates)

## Apply semantics

Whole-key replace: the manifest value (with `${HARNESS_BASE}` resolved) is
assigned to the key; all other settings.json keys round-trip untouched. No
deep merge — merge/conflict resolution is #5's territory. Repo is the source
of truth; drift is repaired by `apply` (repo wins) or by re-adopting the key
from the drifted account (`settings adopt` overwrites the manifest entry).

- Backup settings.json to
  `.harness-sync-backups/<ts>/<harness>/_settings/settings.json` before write;
  referenced files backed up the same way before overwrite.
- Idempotent; `--dry-run` prints and writes nothing.
- Unknown / codex-type targets warned and skipped.
- Secrets note: `env` values live only in the gitignored `manifest.json`
  (same policy as MCP server env). Per-key adopt keeps work secrets from
  leaking into personal accounts — track only the keys you mean to share.

## CLI

```
python3 harness_sync.py settings list
python3 harness_sync.py settings adopt
python3 harness_sync.py settings apply [--dry-run]
```

Same interactive shape as `mcp` / `plugins sync-*`. Pure JSON, runs on 3.9.
No TUI in this PR (precedent: CLI first).

## Testing

Both interpreters. Coverage: canonicalize/resolve round-trip (absolute + `~`
forms, foreign paths untouched); ref extraction; states incl. file-hash
drift; adopt (manifest + repo file copies + warning for dangling refs);
apply (whole-key replace preserving unrelated keys, file materialization,
backup, idempotence, dry-run, codex/unknown skip).
