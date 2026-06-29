# harness-sync — v1 Design (Skills, Claude ↔ Codex)

Date: 2026-06-29
Status: Approved

## Goal

A single tool that keeps **skills** synchronized between harnesses (Claude Code
and Codex), using a **neutral repo as the source of truth** and **selective,
per-skill** decisions about what to sync and what to leave alone.

V1 scope is **skills only**. MCP, instruction files, pruning, and two-way auto
sync are explicitly out of scope (see Non-Goals).

## Context

- Claude skills live in `~/.claude/skills/` (respects `CLAUDE_CONFIG_DIR`).
- Codex skills live in `~/.codex/skills/` (respects `CODEX_HOME`).
- Both already hold copies that have **drifted**: Claude has the superset
  (e.g. `find-skills`, `lambda-builder`, `repo-index-generator`,
  `nocnoc-patterns`); Codex has an older copy from a one-time manual sync.
- A skill is a directory containing `SKILL.md` plus optional support files
  (e.g. `strict-tdd.md`). The format is identical across both harnesses, so
  syncing a skill is a **directory copy** — no transformation needed.

## Stack

Single Python script, **standard library only** (`pathlib`, `shutil`,
`hashlib`, `json`, `argparse`, `tempfile`). No third-party dependencies.

Rationale: skills-only sync is tree copy + content hashing + a manifest + one
interactive prompt. Python stdlib covers all of it. Bash would struggle with
the interactive prompts and hashing.

## Repo Layout (source of truth)

```
harness-sincronizer/
  harness_sync.py        # the CLI
  skills/                # canonical adopted skills (one dir per skill)
  manifest.json          # per-skill sync decisions
  test_harness_sync.py   # stdlib self-check
  .harness-sync-backups/ # timestamped backups of overwritten target dirs
```

## State Model

For each skill name, the tool compares a **content hash** across the three
locations (repo / Claude / Codex) and derives a state:

- `synced` — repo content == target content
- `drift` — exists in a harness but differs from repo
- `untracked` — exists in a harness, not in repo (adoption candidate)
- `repo-only` / `claude-only` / `codex-only` — present in only one place

The content hash is computed over the skill directory: a stable hash of the
sorted list of `(relative_path, sha256(file_bytes))` for all files in the
skill dir. This makes drift detection order-independent and reliable.

## Commands

### `status`
Read-only. Scans repo `skills/`, `~/.claude/skills/`, `~/.codex/skills/`,
prints a table of `skill | repo | claude | codex | state`. Touches nothing.

### `adopt` (interactive — the hybrid step)
For each skill that is `untracked` or `drift`, prompt the user:
- import into the repo? from which source (Claude / Codex)?
- targets: `claude` / `codex` / `both` / `ignore`

The chosen source content is copied into `skills/<name>/`, and the decision is
written to `manifest.json`. This handles both the initial bootstrap (repo
starts empty) and ongoing drift resolution. Re-runnable: skills already in the
manifest in `synced` state are skipped unless `--all` is passed.

### `apply`
Declarative, no prompts. Reads `manifest.json`; for each skill whose `targets`
include a harness, copies `skills/<name>/` → that harness's skills dir.
- Idempotent: skips when the target hash already matches the repo hash.
- `--dry-run`: print what would change, write nothing.
- Before overwriting an existing target dir, copy it to
  `.harness-sync-backups/<timestamp>/<harness>/<name>/`.

## Manifest Schema

```json
{
  "skills": {
    "branch-pr":      { "targets": ["claude", "codex"] },
    "lambda-builder": { "targets": ["claude"] },
    "find-skills":    { "targets": ["ignore"] }
  }
}
```

`targets` is a list drawn from `claude`, `codex`, `ignore`. `ignore` means
"tracked but intentionally not pushed anywhere" and is mutually exclusive with
the harness targets.

## Safety Rules (non-negotiable)

- The **repo is the source of truth**: `apply` overwrites target content.
- `apply` **never deletes** skills from a harness. It only adds/updates skills
  listed in the manifest. Skills present in a harness but absent from the
  manifest are reported as `untracked` and left untouched.
- Harness paths are resolved at the top of the script and honor
  `CLAUDE_CONFIG_DIR` and `CODEX_HOME` environment variables. This is the hook
  that will later support the "two Claude accounts via alias" use case with no
  rewrite.
- `apply` backs up every overwritten target directory before replacing it.

## Testing

`test_harness_sync.py`, stdlib only (`tempfile` + `assert`):
- create temp repo + fake harness dirs,
- run `adopt` (scripted, non-interactive path) → `apply`,
- assert files land in the right harness dirs,
- assert `apply` is idempotent (second run reports no changes),
- assert untracked harness skills are left untouched.

No test framework, no fixtures.

## Non-Goals (v1)

- MCP server sync (JSON ↔ TOML transformation).
- Instruction file sync (`CLAUDE.md` ↔ `AGENTS.md`).
- Pruning / deleting skills from harnesses.
- Two-way automatic propagation and conflict resolution.

All of the above are intended to layer onto this same base later.
