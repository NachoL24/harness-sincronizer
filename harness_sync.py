#!/usr/bin/env python3
"""harness-sync: selective skill sync between Claude Code and Codex."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HARNESSES = ("claude", "codex")


@dataclass(frozen=True)
class Paths:
    repo_skills: Path
    manifest: Path
    backups: Path
    registry: Path
    harness_skills: dict[str, Path]


def default_harnesses() -> dict[str, Path]:
    return {
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")),
        "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    }


def registry_path(repo_root: Path) -> Path:
    return repo_root / "harnesses.json"


def load_harnesses(repo_root: Path) -> dict[str, Path]:
    path = registry_path(repo_root)
    if not path.exists():
        return default_harnesses()
    data = json.loads(path.read_text())
    return {name: Path(cfg["base"]).expanduser() for name, cfg in data["harnesses"].items()}


def resolve_paths(repo_root: Path) -> Paths:
    bases = load_harnesses(repo_root)
    return Paths(
        repo_skills=repo_root / "skills",
        manifest=repo_root / "manifest.json",
        backups=repo_root / ".harness-sync-backups",
        registry=registry_path(repo_root),
        harness_skills={name: base / "skills" for name, base in bases.items()},
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
    names = list(paths.harness_skills)
    harness = {h: scan(paths.harness_skills[h]) for h in names}
    all_names = set(repo) | {n for m in harness.values() for n in m}
    rows = []
    for name in sorted(all_names):
        r = repo.get(name)
        row = {"name": name, "repo": r is not None}
        for h in names:
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
    for h in targets:
        if h not in paths.harness_skills:
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
        for t in targets:
            if t not in paths.harness_skills:
                print(f"warning: skill '{name}' targets unknown harness '{t}' — skipping", file=sys.stderr)
        changes += apply_skill(paths, name, targets, dry_run)
    return changes


def cmd_status(paths: Paths) -> None:
    rows = compute_states(paths)
    print(f"{'SKILL':32} {'REPO':5} {'CLAUDE':10} {'CODEX':10}")
    for r in rows:
        print(f"{r['name']:32} {'yes' if r['repo'] else 'no':5} {r['claude']:10} {r['codex']:10}")


def _prompt(msg: str, choices: list[str]) -> str:
    joined = "/".join(choices)
    while True:
        ans = input(f"{msg} [{joined}]: ").strip().lower()
        if ans in choices:
            return ans


def cmd_adopt(paths: Paths) -> None:
    for row in compute_states(paths):
        name = row["name"]
        available = [h for h in HARNESSES if row[h] in ("untracked", "drift")]
        if not available:
            continue
        status = ", ".join(f"{h}:{row[h]}" for h in HARNESSES)
        print(f"\nSkill: {name}  ({status})")
        if input("  adopt? [y/N]: ").strip().lower() != "y":
            continue
        source = available[0] if len(available) == 1 else _prompt("  source", available)
        choice = _prompt("  targets", ["claude", "codex", "both", "ignore"])
        targets = list(HARNESSES) if choice == "both" else [choice]
        adopt_skill(paths, name, source, targets)
        print(f"  adopted {name} from {source} -> {targets}")


def cmd_apply(paths: Paths, dry_run: bool) -> None:
    changes = apply_all(paths, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    if not changes:
        print("nothing to do")
        return
    for c in changes:
        print(f"{prefix}{c}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-sync")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show skill states across harnesses")
    sub.add_parser("adopt", help="interactively import skills into the repo")
    ap = sub.add_parser("apply", help="push manifest skills to harnesses")
    ap.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    paths = resolve_paths(Path(__file__).resolve().parent)
    if args.cmd == "status":
        cmd_status(paths)
    elif args.cmd == "adopt":
        cmd_adopt(paths)
    elif args.cmd == "apply":
        cmd_apply(paths, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
