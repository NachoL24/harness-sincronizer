# harness-sync

Selective **skill synchronization** between AI coding harnesses — today
**Claude Code ↔ Codex**. A neutral git repo is the source of truth: it holds the
canonical skills and a manifest of what to sync where. Nothing is synced
blindly — you decide, skill by skill.

> v1 covers **skills only**. MCP servers, instruction files, pruning, and
> two-way auto-sync are intentionally out of scope (see `CLAUDE.md`).

## Requirements

- Python **3.11+**
- No dependencies (standard library only)

## How it works

| Location | Path | Role |
|----------|------|------|
| Repo | `./skills/` + `./manifest.json` | **source of truth** (local, gitignored) |
| Claude Code | `~/.claude/skills/` (or `$CLAUDE_CONFIG_DIR/skills`) | sync target |
| Codex | `~/.codex/skills/` (or `$CODEX_HOME/skills`) | sync target |

> `skills/`, `manifest.json` and `harnesses.json` are **per-user runtime data**
> and are gitignored — you build your own canonical store locally via `adopt`.
> They are not shared through this repo.

A skill is a directory (e.g. `branch-pr/`) containing `SKILL.md` plus any
support files. The tool compares a content hash of each skill across the three
locations to derive its state:

- `synced` — repo matches the harness
- `drift` — exists in the harness but differs from the repo
- `untracked` — exists in a harness, not yet in the repo
- `absent` — not present in that harness

## Usage

### 1. See what's where

```bash
python3 harness_sync.py status
```

Prints a table of every skill and its state in Claude and Codex. Read-only.

### 2. Adopt skills into the repo (interactive)

```bash
python3 harness_sync.py adopt
```

For each `untracked` or `drift` skill, it asks:

- **adopt?** `y`/`N`
- **source** — which harness to import the content from (only asked when the
  skill exists in more than one)
- **targets** — where it should be pushed: `claude` / `codex` / `both` /
  `ignore`

Your answers are written to `manifest.json` and the chosen content is copied
into `skills/`. `ignore` means "tracked but never pushed".

Example `manifest.json`:

```json
{
  "skills": {
    "branch-pr":      { "targets": ["claude", "codex"] },
    "lambda-builder": { "targets": ["claude"] },
    "find-skills":    { "targets": ["ignore"] }
  }
}
```

You can also edit `manifest.json` by hand — `apply` reads it directly.

### 3. Push to harnesses

```bash
python3 harness_sync.py apply --dry-run   # preview, writes nothing
python3 harness_sync.py apply             # actually sync
```

`apply` is **idempotent** (skips skills already in sync) and **safe**:

- it never deletes skills from a harness — only adds/updates what's in the
  manifest;
- before overwriting an existing skill, it backs it up to
  `.harness-sync-backups/<timestamp>/<harness>/<name>/`.

## Quick test drive

```bash
git clone <this-repo>
cd harness-sincronizer
python3 test_harness_sync.py          # run the suite (should print PASS x11)
python3 harness_sync.py status        # inspect your real harness skills
python3 harness_sync.py adopt         # pick a couple of skills to track
python3 harness_sync.py apply --dry-run
python3 harness_sync.py apply
```

## Harnesses (the registry)

The set of harnesses the tool syncs is configurable via `harnesses.json` at the
repo root. Each entry maps a name to a **base config dir**; the skills path is
derived as `<base>/skills`.

```json
{
  "harnesses": {
    "claude":       { "base": "~/.claude" },
    "claude-perso": { "base": "~/.claude-perso" },
    "codex":        { "base": "~/.codex" }
  }
}
```

- **No `harnesses.json`** → built-in defaults: `claude` → `$CLAUDE_CONFIG_DIR`
  or `~/.claude`, `codex` → `$CODEX_HOME` or `~/.codex`. (Backwards compatible —
  the env-var override still works in this mode.)
- **`harnesses.json` present** → it fully defines the harness set and **env vars
  are ignored** (explicit wins). Order in the file = column order in `status`.

Manage it with:

```bash
python3 harness_sync.py harness list                       # show resolved registry
python3 harness_sync.py harness add claude-perso ~/.claude-perso
python3 harness_sync.py harness remove codex
```

The first `harness add` (when no file exists) seeds the registry with the
current defaults plus your new entry, so nothing is lost. `manifest.json`
`targets` reference these names; a target naming an unknown harness is warned
and skipped.

### Two Claude accounts

Register the second account once, and it becomes a permanent column:

```bash
python3 harness_sync.py harness add claude-perso ~/.claude-perso
python3 harness_sync.py status   # claude, claude-perso and codex as columns
```

## Development

- Tests: `python3 test_harness_sync.py` (stdlib runner, no framework).
- TDD: failing test first, then minimal implementation.
- Design & plan: `docs/superpowers/`.
