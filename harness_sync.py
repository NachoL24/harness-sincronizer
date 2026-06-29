#!/usr/bin/env python3
"""harness-sync: selective skill sync between Claude Code and Codex."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
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
