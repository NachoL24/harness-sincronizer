# harness-sync — Project Guide

Selective skill synchronization between AI coding harnesses (Claude Code and
Codex), using a **neutral repo as the source of truth**.

## What this is

`harness_sync.py` is a single, dependency-free Python CLI. The repo's `skills/`
directory holds the canonical copy of each skill; `manifest.json` records, per
skill, which harnesses it should be pushed to. You decide what to sync — nothing
is synced blindly.

**`skills/`, `manifest.json` and `harnesses.json` are per-user runtime data and
are gitignored** — they live in your local checkout, not in this public tool
repo. Each user builds their own canonical store via `adopt`.

## Architecture

- **Pure, path-injected functions** do the work (hashing, scanning, manifest
  I/O, adopt, apply). A thin `argparse` CLI wraps them. This keeps everything
  unit-testable without touching the real `~/.claude` / `~/.codex` dirs.
- **Skill detection**: a skill is a non-hidden directory containing `SKILL.md`;
  dot-dirs (e.g. `.system`) and support dirs without `SKILL.md` are ignored.
- **State** is derived by comparing a content hash of each skill directory
  across three locations: the repo, Claude, and Codex. States: `synced`,
  `drift`, `untracked`, `absent`.
- **Source of truth = the repo.** `apply` overwrites harness content from the
  repo. Deletion only happens when explicitly asked — `untrack` (repo side) or
  `apply --prune` (harness side) — and every overwritten or deleted directory
  is backed up to `.harness-sync-backups/` first. Foreign (unmanifested)
  skills and `ignore`-targeted skills are never deleted.

## Commands

- `python3 harness_sync.py status` — read-only state table across harnesses.
- `python3 harness_sync.py adopt` — interactive; imports skills into the repo
  and records targets in the manifest. The non-interactive core is
  `adopt_skill()`.
- `python3 harness_sync.py apply [--dry-run] [--prune]` — declarative; pushes
  manifest skills to their target harnesses. Idempotent. `--prune` also deletes
  tracked skills from harnesses they are de-targeted from (backup first;
  `ignore`/foreign skills always spared).
- `python3 harness_sync.py refresh <name> [source]` — re-import a tracked,
  drifted skill's content from a harness into the repo (previous repo copy
  backed up; manifest untouched). Source defaults to the only drifted harness.
- `python3 harness_sync.py untrack <name>` — stop managing a skill: manifest
  entry and repo copy removed (repo copy backed up); harness copies untouched.
  Core: `untrack_skill()` (raises `KeyError` if untracked).
- `python3 harness_sync.py harness list|add <name> <base>|remove <name>` —
  manage the harness registry (`harnesses.json`).
- `python3 harness_sync.py plugins list|adopt` — discover skills bundled inside
  Claude plugins (per harness, via `installed_plugins.json`) and adopt them
  whole-plugin at a time into the repo. Repo-name collisions are skipped with a
  warning. `adopt_plugin()` is the non-interactive core.
- `python3 harness_sync.py` (no subcommand) or `... tui` — full-screen
  dashboard, the **default command** (Status / Adopt / Plugins / MCP / Apply /
  Harness). Requires `textual`; presentation-only layer in `harness_tui.py`,
  lazy-imported with an install hint when missing. The MCP tab needs Python
  3.11+ (shows a hint otherwise); the Apply tab includes skills, optional
  prune, and `mcp:` pending lines.
- `python3.12 harness_sync.py mcp list|adopt|apply [--dry-run]` — sync global
  MCP server definitions (Claude `.claude.json` JSON ↔ Codex `config.toml`
  TOML). Needs Python 3.11+ (`tomllib`, lazily gated — the rest of the CLI
  runs on older interpreters). Surgical writes: JSON touches only
  `mcpServers`; TOML splices only managed `[mcp_servers.*]` blocks. Manifest
  section: top-level `"mcp"` (`{targets, config}` per server). Registry
  entries may carry `"type": "claude"|"codex"` (inferred when absent).

## Harnesses (the registry)

The harness set is configurable via `harnesses.json` (repo root), mapping each
name to a **base config dir**; the skills path is derived as `<base>/skills`.

- **Registry absent** → built-in defaults: `claude` → `$CLAUDE_CONFIG_DIR` or
  `~/.claude`, `codex` → `$CODEX_HOME` or `~/.codex`. Env-var override applies.
- **Registry present** → it is authoritative and env vars are ignored.
- `harness add` with no file seeds the current defaults plus the new entry.
- Manifest `targets` reference registry names; unknown targets are warned and
  skipped by `apply`.

This is how the "N Claude accounts + Codex" use case works: register each
account once and it becomes a permanent column.

## Testing

Standard library only, no framework:

```bash
python3 test_harness_sync.py
```

The runner prints `PASS`/`FAIL` per test and exits non-zero on any failure.
Follow TDD: write the failing test first, then the minimal implementation.

## Conventions

- Python 3.11+. The **core is stdlib-only** (`harness_sync.py`,
  `test_harness_sync.py` must run without any third-party package). The one
  allowed dependency is `textual` (declared in `requirements.txt`), and ONLY
  inside the presentation layer `harness_tui.py` — never import it from the
  core.
- All code, comments, and commit messages in English.
- Keep `harness_sync.py` as one focused module unless it genuinely grows too
  large.

## Non-goals (v1)

Instruction-file sync (`CLAUDE.md`↔`AGENTS.md`) and two-way auto propagation.
These are meant to layer onto the same base later. (MCP sync and
untrack/pruning shipped after v1.)

Design and plan live under `docs/superpowers/`.
