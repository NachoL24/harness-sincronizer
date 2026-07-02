# Instruction-File Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `instructions` fixed-name kind syncing `<base>/CLAUDE.md` (claude-type) ↔ `<base>/AGENTS.md` (codex-type) through the existing flows as `instructions:global.md`.

**Architecture:** Add `names` to the KINDS schema; introduce `harness_asset_path` (single path resolver for all kinds) and `_harness_kind_scan` (fixed-name kinds yield one logical asset `global.md`); rewire `compute_states`/`adopt_skill`/`apply_skill`/`refresh_skill`/`prune_all` to use them. Repo store `instructions/global.md` needs no scanner change.

**Tech Stack:** stdlib; suites on python3 and python3.12.

## Global Constraints

- `KINDS["instructions"] = {"asset": "file", "claude_only": False, "names": {"claude": "CLAUDE.md", "codex": "AGENTS.md"}}`; canonical asset name `global.md`.
- Plain verbatim copy; overwrites are backed up; nothing syncs until adopted.
- All 55 existing tests stay green; English; Co-Authored-By trailer.

---

### Task 0: Branch
- [ ] `git checkout main && git checkout -b feature/instructions-sync`; commit spec+plan (`docs: add instructions-sync spec and plan`).

### Task 1: Path resolver + fixed-name scan (TDD)
- [ ] Failing tests: `harness_asset_path` returns `base/CLAUDE.md` (claude), `base/AGENTS.md` (codex), `None` for codex+agents; `_harness_kind_scan` yields `{"global.md": hash}` when the file exists, `{}` otherwise; regular kinds unaffected.
- [ ] Implement:

```python
FIXED_ASSET = "global.md"

def harness_asset_path(paths, harness, kind, name):
    spec = KINDS[kind]
    if spec["claude_only"] and paths.harness_types[harness] == "codex":
        return None
    base = paths.harness_skills[harness].parent
    if "names" in spec:
        return base / spec["names"][paths.harness_types[harness]]
    return base / kind / name

def _harness_kind_scan(paths, harness, kind):
    if "names" in KINDS[kind]:
        p = harness_asset_path(paths, harness, kind, FIXED_ASSET)
        return {FIXED_ASSET: skill_hash(p)} if p and p.is_file() else {}
    hd = harness_kind_dir(paths, harness, kind)
    return scan_kind(hd, kind) if hd is not None else {}
```

- [ ] Both suites green; commit (`feat: fixed-name kind primitives`).

### Task 2: Rewire flows + instructions kind (TDD)
- [ ] Failing test `test_instructions_roundtrip`: claude base with `CLAUDE.md` "shared rules"; adopt `global.md` from claude with targets [claude, codex] → repo `instructions/global.md` + manifest section; `apply_all` writes codex `<base>/AGENTS.md`; second apply `== []`; codex edit → `drift`; `refresh` pulls it back; `untrack` leaves harness files.
- [ ] Implement: add the KINDS entry; `compute_states` harness loop → `_harness_kind_scan`; `adopt_skill` src via `harness_asset_path`; `apply_skill` dst via `harness_asset_path` (drop the separate `harness_kind_dir` call, keep the None warning); `refresh_skill` src via `harness_asset_path`; `prune_all` dst via `harness_asset_path` (None → skip).
- [ ] Both suites green (55 + new); commit (`feat: instructions kind — CLAUDE.md/AGENTS.md sync`).

### Task 3: Docs + smoke
- [ ] README section (Instruction files: fixed names, `instructions:global.md`, plain copy, opt-in overwrite warning); CLAUDE.md commands/kind notes; remove instruction-sync from non-goals; `cp CLAUDE.md AGENTS.md`.
- [ ] Smoke: real `status | rg instructions` shows one row (untracked in all three, since contents differ nothing is synced yet).
- [ ] Suites; commit (`docs: document instruction-file sync`).

---

## Self-Review
Spec→tasks: KINDS entry+resolver+scan (T1/T2) ✓ flows rewired (T2) ✓ addressing/CLI/TUI inherited ✓ safety note documented (T3) ✓ tests enumerated ✓. No placeholders; signatures consistent (`harness_asset_path(paths, h, kind, name)` used by adopt/apply/refresh/prune). ✓
