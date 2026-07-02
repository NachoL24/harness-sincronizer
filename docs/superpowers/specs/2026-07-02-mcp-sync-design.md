# MCP Server Sync (Claude JSON ↔ Codex TOML) — Design (Issue #2)

Date: 2026-07-02
Status: Approved (CLI-only scope chosen by default recommendation — user AFK;
TUI tab is a follow-up)

## Goal

Selectively sync **global MCP server definitions** between harnesses. MCP
servers are portable (open standard); only the config **format** differs:

- Claude-type harness: `mcpServers` object inside `.claude.json` (JSON).
- Codex-type harness: `[mcp_servers.<name>]` tables inside `config.toml` (TOML).

Same model as skills: neutral store + manifest decisions + declarative apply.
Scope is global servers only — project-scoped `.mcp.json` is out (measured:
zero project servers in real use).

## Neutral model

A server is a plain dict as Claude stores it: `{command, args, env, type, ...}`.
Claude JSON is already in this shape; Codex TOML tables map 1:1 (`[mcp_servers.x]`
keys → dict keys, `[mcp_servers.x.env]` → `env` dict). Unknown keys are
preserved as-is in both directions. Values are limited to strings, numbers,
booleans, string lists, and flat string dicts (`env`) — enough for MCP configs.

## Harness `type` (registry extension)

The registry entry gains an optional `"type": "claude" | "codex"`:

```json
{"harnesses": {"claude-perso": {"base": "~/.claude-perso", "type": "claude"}}}
```

- Absent type → inferred: `"codex"` if the harness name is `codex`, else
  `"claude"`. Existing registries keep working.
- `harness add` gains an optional third argument `type` (default inferred).

## Config file location per type

- **codex**: `<base>/config.toml`.
- **claude**: `<base>/.claude.json` if it exists; if `<base>` is `~/.claude`
  and it doesn't, fall back to `~/.claude.json` (observed reality: with
  `CLAUDE_CONFIG_DIR` the file lives inside the dir; the default install keeps
  it at `$HOME/.claude.json`).
- Missing file → harness reports no servers (read) / is skipped with a warning
  (write).

## Python version handling

`tomllib` is stdlib but 3.11+; the user's default `python3` is 3.9. All MCP
functions import `tomllib` lazily and raise/print a clear error
(`MCP sync requires Python 3.11+ — run with python3.11 or newer`) instead of
breaking the rest of the CLI on old interpreters. Everything else keeps
running on 3.9.

## Read/write per format

- **Claude JSON**: `json.loads` the file, read/replace only the `mcpServers`
  key, `json.dumps` back (indent 2). Everything else in `.claude.json` is
  preserved structurally.
- **Codex TOML — text splicing, never full regeneration**: stdlib cannot write
  TOML, and regenerating the file would destroy comments/formatting of
  unrelated sections. Write path: remove ONLY the `[mcp_servers.<name>]`
  blocks (and their `.env` subtables) of the servers being written, by
  line-level scanning (a block runs from its header to the next `[header]` or
  EOF); every other line — including blocks of unmanaged servers — stays
  byte-for-byte; then append the regenerated blocks for the servers written.
  Read path: `tomllib.loads` → `mcp_servers` dict.
- Managed-only writes: servers not in the manifest are never touched in either
  format; their TOML blocks are never removed, so they keep their exact bytes.
- Backup: copy the target config file to
  `.harness-sync-backups/<ts>/<harness>/_mcp/<filename>` before writing.

## Manifest

New top-level `"mcp"` section (schema `"skills"` untouched):

```json
{
  "skills": { ... },
  "mcp": {
    "engram":    {"targets": ["claude", "codex"], "config": {"command": "/opt/homebrew/bin/engram", "args": ["mcp", "--tools=agent"]}},
    "node_repl": {"targets": ["ignore"], "config": {...}}
  }
}
```

The neutral config lives inline in the manifest (small dicts; no new dir).
`manifest.json` is gitignored, so env secrets never reach the public repo.
`targets`/`ignore` semantics identical to skills.

## Commands (CLI-only in this change; TUI tab is a follow-up)

- `mcp list` — table: server × harness, states `synced` (config equal after
  normalization), `drift`, `untracked`, `absent`, plus repo (manifest) presence.
- `mcp adopt` — interactive per server (like `adopt`): pick source harness when
  ambiguous, pick targets (`_prompt_targets`). Stores neutral config + targets
  in the manifest.
- `mcp apply [--dry-run]` — declarative: for each manifest server, write it to
  each target harness's config file in that harness's format. Idempotent
  (skip when the parsed target config already equals the manifest config).
  Unknown target → warn + skip. Never deletes unmanaged servers.

No pruning of MCP servers in this change (mirrors skills v1; prune parity can
follow later).

## Error handling

- Old Python (no `tomllib`): clear error only when an `mcp` command runs.
- Unparseable config file: clear error naming the file; nothing written.
- Missing config file on a write target: warn + skip that harness.
- Backup failure aborts the write for that file.

## Testing (stdlib, run with python3.11+; extend `test_harness_sync.py`)

- Claude JSON read/write: roundtrip preserves unrelated keys; only
  `mcpServers` changes.
- TOML read: `tomllib` parse of `[mcp_servers.x]` (+`.env`).
- TOML splice-write: unrelated sections and comments byte-identical; managed
  blocks replaced; unmanaged server blocks untouched.
- States: synced/drift/untracked/absent across two fake harnesses.
- `mcp_adopt` core (non-interactive) records manifest; `mcp_apply` pushes both
  formats, idempotent second run, dry-run writes nothing, backup created.
- Guard: running the runner on 3.9 skips MCP tests gracefully (same guarded
  pattern as the TUI tests).

## Non-goals

- Project-scoped servers (`.mcp.json`, `projects` key).
- Plugin-provided MCP servers (e.g. engram-via-plugin) — only explicit
  `mcpServers`/`[mcp_servers]` entries.
- MCP pruning; TUI tab (follow-ups).
- Comment preservation *inside* managed `[mcp_servers.*]` blocks (they are
  regenerated; comments elsewhere are preserved).
