#!/usr/bin/env python3
"""harness-sync: selective skill sync between Claude Code and Codex."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HARNESSES = ("claude", "codex")


@dataclass(frozen=True)
class Paths:
    repo_skills: Path
    manifest: Path
    backups: Path
    harness_skills: dict[str, Path]


def harness_skill_dir(harness: str) -> Path:
    if harness == "claude":
        base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        return base / "skills"
    if harness == "codex":
        base = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return base / "skills"
    raise ValueError(f"unknown harness: {harness}")


def resolve_paths(repo_root: Path) -> Paths:
    return Paths(
        repo_skills=repo_root / "skills",
        manifest=repo_root / "manifest.json",
        backups=repo_root / ".harness-sync-backups",
        harness_skills={h: harness_skill_dir(h) for h in HARNESSES},
    )


def skill_hash(skill_dir: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        h.update(f.relative_to(skill_dir).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def scan(skills_dir: Path) -> dict[str, str]:
    if not skills_dir.is_dir():
        return {}
    return {d.name: skill_hash(d) for d in sorted(skills_dir.iterdir()) if d.is_dir()}


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"skills": {}}
    return json.loads(path.read_text())


def save_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def compute_states(paths: Paths) -> list[dict]:
    repo = scan(paths.repo_skills)
    harness = {h: scan(paths.harness_skills[h]) for h in HARNESSES}
    names = set(repo) | {n for hs_map in harness.values() for n in hs_map}
    rows = []
    for name in sorted(names):
        r = repo.get(name)
        row = {"name": name, "repo": r is not None}
        for h in HARNESSES:
            hh = harness[h].get(name)
            if hh is None:
                row[h] = "absent"
            elif r is None:
                row[h] = "untracked"
            elif hh == r:
                row[h] = "synced"
            else:
                row[h] = "drift"
        rows.append(row)
    return rows


def copy_skill(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def adopt_skill(paths: Paths, name: str, source_harness: str, targets: list[str]) -> None:
    copy_skill(paths.harness_skills[source_harness] / name, paths.repo_skills / name)
    man = load_manifest(paths.manifest)
    man["skills"][name] = {"targets": list(targets)}
    save_manifest(paths.manifest, man)


def apply_skill(paths: Paths, name: str, targets: list[str], dry_run: bool = False) -> list[str]:
    src = paths.repo_skills / name
    src_hash = skill_hash(src)
    changes: list[str] = []
    for h in HARNESSES:
        if h not in targets:
            continue
        dst = paths.harness_skills[h] / name
        if dst.is_dir() and skill_hash(dst) == src_hash:
            continue
        changes.append(f"{name} -> {h}")
        if dry_run:
            continue
        if dst.exists():
            backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / h / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dst, backup)
        copy_skill(src, dst)
    return changes


def apply_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest)
    changes: list[str] = []
    for name, cfg in sorted(man["skills"].items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        changes += apply_skill(paths, name, targets, dry_run)
    return changes
