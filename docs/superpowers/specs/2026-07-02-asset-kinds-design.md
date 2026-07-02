# Asset-Kind Engine: Agents & Slash Commands — Design (Issue #9)

Date: 2026-07-02
Status: Approved (user chose the generic engine over per-kind command groups)

## Goal

Generalize the sync engine from "skills only" to **asset kinds**, and ship the
first two new kinds: **agents** (`<base>/agents/*.md`) and **slash commands**
(`<base>/commands/*.md`), which sync between Claude-type harnesses only
(verified: Codex has no agents/commands concept).

No new command groups: `status`, `adopt`, `apply`, `untrack`, `refresh`,
`prune` and the TUI cover all kinds through one flow. Future kinds (#10, #11,
#14) plug into the same table.

## Kind model

```python
KINDS = {
    "skills":   {"asset": "dir",  "claude_only": False},
    "agents":   {"asset": "file", "claude_only": True},
    "commands": {"asset": "file", "claude_only": True},
}
```

- The kind name doubles as the subdir convention: repo store `<repo>/<kind>/`,
  harness location `<base>/<kind>/`.
- **dir assets** (skills): non-hidden directory containing `SKILL.md`
  (unchanged rule).
- **file assets** (agents/commands): `*.md` files; the asset name is the full
  filename (e.g. `sdd-apply.md`) — no stem munging.
- **claude_only kinds**: codex-type harnesses scan as empty and are
  warned+skipped as apply targets for those kinds.

## Naming across the UI

Assets are addressed as `kind:name` with **skills unprefixed** (the dominant
case): `branch-pr` (skill), `agents:sdd-apply.md`, `commands:sdd-ff.md`.
`parse_asset_name("agents:x.md") -> ("agents", "x.md")`; no prefix →
`("skills", name)`. Applies to `untrack`, `refresh`, change strings
(`agents:foo -> claude-perso`), status rows, and TUI labels.

## Engine generalization (minimal churn, defaults keep 48 tests green)

Polymorphic primitives (dispatch on the filesystem, not on flags):
- `skill_hash(path)` — file → sha256 of bytes; dir → current tree hash.
- `copy_skill(src, dst)` — file → `copy2` (parent mkdir); dir → current
  rmtree+copytree.
- `backup_skill(paths, label, name, src)` — file → `copy2`; dir → copytree.

Kind-aware scanning and paths:
- `scan_kind(root, kind)` — dir kinds: current `scan`; file kinds: `*.md`
  files mapped name→hash.
- `harness_kind_dir(paths, h, kind) -> Path | None` — `None` when the kind is
  claude_only and the harness is codex-type (scans empty, apply warns+skips).

Flows gain a `kind: str = "skills"` keyword (names unchanged — they predate
the generalization):
- `compute_states(paths, kind="skills")` — same row shape.
- `import_skill(..., kind)`, `adopt_skill(..., kind)` — manifest section =
  kind name (`man["agents"][name] = {"targets": [...]}`; schema identical).
- `apply_skill(..., kind)`; `apply_all` iterates ALL kinds; `prune_all` too.
- `untrack_skill(..., kind)`, `refresh_skill(..., kind)`.

Manifest: top-level sections `"skills"` (existing), `"agents"`, `"commands"`
(additive; `"mcp"` untouched). `ignore` semantics identical.

## CLI

- `status` — one table, rows from all kinds (non-skill rows prefixed).
- `adopt` — interactive walk includes agents/commands (prefixed prompts);
  targets restricted to claude-type harnesses for claude_only kinds.
- `apply [--dry-run] [--prune]` — covers all kinds; change lines prefixed.
- `untrack <asset>` / `refresh <asset> [source]` — accept `kind:name`.

## TUI

- Status tab: prefixed rows (kind visible in the name); `u` untrack parses the
  prefix.
- Adopt tab: adoptable agents/commands appear in the same checkbox list with
  prefixed labels; batch targets unchanged (claude_only enforcement inside the
  core apply/adopt, with Activity log lines when something is skipped).
- Apply tab: free — it already renders `apply_all`/`prune_all` output.

## Safety

Unchanged rules, now per kind: never delete unmanaged content; `--prune` only
de-targeted tracked assets; every overwrite/delete backed up under
`.harness-sync-backups/<ts>/…` (repo label `"repo"`).

## Testing (extend `test_harness_sync.py`; all existing tests stay green)

- `scan_kind` file kind; `skill_hash`/`copy_skill`/`backup_skill` on files.
- `parse_asset_name` (prefixed / unprefixed).
- Agent states across claude/claude-perso/codex (codex always absent).
- Adopt agent → repo `agents/` + manifest section; apply to a second
  claude-type harness; codex target warned+skipped.
- Untrack / refresh / prune for a file asset.
- Guarded TUI test: agent row appears prefixed in status and in the adopt
  list.

## Non-goals

Hooks/settings (#10 — embedded JSON merge, not a file asset), cosmetic assets
(#11 — some are single files at fixed paths, a later kind variant), whole
plugins (#14), two-way (#5).
