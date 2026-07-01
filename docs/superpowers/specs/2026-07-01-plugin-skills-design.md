# Plugin Skills → Codex — Design (Issue #7, Phase 1)

Date: 2026-07-01
Status: Approved

## Goal

Discover skills bundled inside Claude plugins and let them be synced to Codex
(and any target harness) as standalone skills. Today the tool only scans
`<base>/skills/`, so it ignores the bulk of the real skill set, which lives
inside plugins.

The **unit of adoption is the whole plugin**: adopting a plugin imports all of
its skills at once — no skill-by-skill prompting within a plugin.

Phase 2 (whole-plugin sync between Claude accounts) stays out of scope.

## Discovery (per harness, via `installed_plugins.json`)

Plugins are per-harness (`<base>/plugins/`), so discovery iterates the harness
registry.

For each registered harness:
1. Read `<base>/plugins/installed_plugins.json` (format `version: 2`:
   `{"plugins": {"<plugin@marketplace>": [{"installPath", "version", ...}]}}`).
2. For each active plugin, take its `installPath` and collect skills at
   `<installPath>/skills/*/SKILL.md`.
3. Tag each discovered plugin with `(harness, plugin_key, [skills])`.

**Authoritative source = `installed_plugins.json`**, not an `rglob` over the
cache. The cache contains junk (`.cursor/skills/`, `.windsurf/skills/`, nested
`plugins/*/skills/`, stale versions); `installed_plugins.json` points only at
the active install.

**Tolerant discovery:** if the file is missing, unparseable, or an `installPath`
does not exist, that harness contributes zero plugins — never crash. This also
means harnesses without this format (e.g. Codex) simply yield nothing.

**Ceiling (Phase 1):** only `<installPath>/skills/` is read. Plugins that nest
skills elsewhere (e.g. `<installPath>/plugins/<x>/skills/`) are not discovered
in Phase 1.

## Commands

New `plugins` command group:

- **`plugins list`** — read-only. One row per discovered plugin:
  `PLUGIN | HARNESS | SKILLS | IN-REPO`, where `SKILLS` is the count and
  `IN-REPO` is how many of them already exist in the repo `skills/`.
- **`plugins adopt`** — interactive, **per plugin**. For each discovered plugin,
  prompt: `adopt plugin <name> (<N> skills) from <harness>?` and, if yes, the
  `targets` (reusing `_prompt_targets`, typically `codex`). On adoption, every
  skill in the plugin is imported into the repo `skills/<name>/` and recorded in
  the manifest with the chosen targets. The normal `apply` then pushes them.

## Reuse / refactor

Extract a shared `import_skill(paths, name, src_dir, targets)` that copies a
skill directory into the repo and records the manifest entry. `adopt_skill`
becomes a thin wrapper passing the harness path; the plugin flow calls
`import_skill` with the plugin skill path. No duplicated copy/manifest logic.

Skill names in the repo (and therefore in Codex) stay **flat** (e.g.
`brainstorming/`) so Codex loads them normally — no plugin namespacing.

## Collision handling

When adopting a plugin, if a skill's name **already exists in the repo**
`skills/` (from a standalone adopt or another plugin), that skill is **skipped
with a warning**; the rest of the plugin's skills are still adopted. Nothing in
the repo is overwritten. The user resolves collisions manually if desired.

## Manifest

Schema unchanged. Adopted plugin skills become normal per-skill entries
(`{"targets": [...]}`). Phase 1 does not record plugin origin in the manifest;
tracking the plugin→skills association for later updates is a follow-up.

## Error handling

- Missing/invalid `installed_plugins.json` → harness yields no plugins.
- `installPath` absent on disk → plugin skipped.
- Plugin with no `skills/` dir → contributes nothing.
- Name collision → skip that skill, warn, continue.

## Testing (stdlib, extend `test_harness_sync.py`)

- `read_installed_plugins`: parses active `installPath`s from a fake file;
  tolerant of a missing/invalid file (returns empty).
- `discover_plugins`: a fake harness with a plugin dir + skills is discovered,
  tagged by harness and plugin.
- `import_skill`: copies a skill dir and records the manifest entry.
- `plugins adopt` core (non-interactive): adopting a plugin imports all its
  skills with the chosen targets.
- Collision: a plugin skill whose name already exists in the repo is skipped
  with a warning; siblings still adopted.
- End-to-end: discover → adopt plugin → `apply` pushes the skills to `codex`.

## Non-goals (Phase 1)

- Whole-plugin sync between Claude accounts (Phase 2, #7).
- Non-canonical nested plugin skill locations.
- Writing plugin skills back into Claude's standalone `skills/` (redundant —
  Claude already loads them via the plugin).
- Recording plugin origin in the manifest / plugin-aware update/refresh.
