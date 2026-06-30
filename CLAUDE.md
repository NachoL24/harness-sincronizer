# harness-sync — Project Guide

Selective skill synchronization between AI coding harnesses (Claude Code and
Codex), using a **neutral repo as the source of truth**.

## What this is

`harness_sync.py` is a single, dependency-free Python CLI. The repo's `skills/`
directory holds the canonical copy of each skill; `manifest.json` records, per
skill, which harnesses it should be pushed to. You decide what to sync — nothing
is synced blindly.

## Architecture

- **Pure, path-injected functions** do the work (hashing, scanning, manifest
  I/O, adopt, apply). A thin `argparse` CLI wraps them. This keeps everything
  unit-testable without touching the real `~/.claude` / `~/.codex` dirs.
- **State** is derived by comparing a content hash of each skill directory
  across three locations: the repo, Claude, and Codex. States: `synced`,
  `drift`, `untracked`, `absent`.
- **Source of truth = the repo.** `apply` overwrites harness content from the
  repo. It never deletes skills from a harness, and backs up any overwritten
  directory to `.harness-sync-backups/` first.

## Commands

- `python3 harness_sync.py status` — read-only state table across harnesses.
- `python3 harness_sync.py adopt` — interactive; imports skills into the repo
  and records targets in the manifest. The non-interactive core is
  `adopt_skill()`.
- `python3 harness_sync.py apply [--dry-run]` — declarative; pushes manifest
  skills to their target harnesses. Idempotent.

## Harness paths (env overrides)

- Claude skills: `$CLAUDE_CONFIG_DIR/skills` (default `~/.claude/skills`)
- Codex skills: `$CODEX_HOME/skills` (default `~/.codex/skills`)

`CLAUDE_CONFIG_DIR` is the hook for the future "two Claude accounts" use case —
point it at a second config dir and sync works unchanged.

## Testing

Standard library only, no framework:

```bash
python3 test_harness_sync.py
```

The runner prints `PASS`/`FAIL` per test and exits non-zero on any failure.
Follow TDD: write the failing test first, then the minimal implementation.

## Conventions

- Python 3.11+, **standard library only**. Do not add dependencies.
- All code, comments, and commit messages in English.
- Keep `harness_sync.py` as one focused module unless it genuinely grows too
  large.

## Non-goals (v1)

MCP server sync (JSON↔TOML), instruction-file sync (`CLAUDE.md`↔`AGENTS.md`),
pruning/deletion from harnesses, and two-way auto propagation. These are meant
to layer onto the same base later.

Design and plan live under `docs/superpowers/`.
