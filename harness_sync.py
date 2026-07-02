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


def read_installed_plugins(plugins_dir: Path) -> list[tuple[str, Path]]:
    f = plugins_dir / "installed_plugins.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text())
    except json.JSONDecodeError:
        return []
    result: list[tuple[str, Path]] = []
    for key, entries in data.get("plugins", {}).items():
        for entry in entries:
            install_path = entry.get("installPath")
            if install_path:
                result.append((key, Path(install_path)))
    return result


def discover_plugins(paths: Paths) -> list[dict]:
    plugins: list[dict] = []
    for harness, skills_dir in paths.harness_skills.items():
        plugins_dir = skills_dir.parent / "plugins"
        for plugin_key, install_path in read_installed_plugins(plugins_dir):
            sdir = install_path / "skills"
            if not sdir.is_dir():
                continue
            skills = [
                (d.name, d)
                for d in sorted(sdir.iterdir())
                if d.is_dir() and (d / "SKILL.md").exists()
            ]
            if skills:
                plugins.append({"plugin": plugin_key, "harness": harness, "skills": skills})
    return plugins


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"skills": {}}
    return json.loads(path.read_text())


def save_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"harnesses": {}}
    return json.loads(path.read_text())


def save_registry(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def harness_add(paths: Paths, name: str, base: str) -> None:
    if not paths.registry.exists():
        data = {"harnesses": {n: {"base": str(b)} for n, b in default_harnesses().items()}}
    else:
        data = load_registry(paths.registry)
    data["harnesses"][name] = {"base": base}
    save_registry(paths.registry, data)


def harness_remove(paths: Paths, name: str) -> None:
    data = load_registry(paths.registry)
    data["harnesses"].pop(name, None)
    save_registry(paths.registry, data)


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


def backup_skill(paths: Paths, label: str, name: str, src: Path) -> None:
    backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / label / name
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, backup)


def import_skill(paths: Paths, name: str, src_dir: Path, targets: list[str]) -> None:
    copy_skill(src_dir, paths.repo_skills / name)
    man = load_manifest(paths.manifest)
    man["skills"][name] = {"targets": list(targets)}
    save_manifest(paths.manifest, man)


def adopt_skill(paths: Paths, name: str, source_harness: str, targets: list[str]) -> None:
    import_skill(paths, name, paths.harness_skills[source_harness] / name, targets)


def adopt_plugin(paths: Paths, plugin: dict, targets: list[str]) -> tuple[list[str], list[str]]:
    adopted: list[str] = []
    skipped: list[str] = []
    for name, src in plugin["skills"]:
        if (paths.repo_skills / name).exists():
            skipped.append(name)
            continue
        import_skill(paths, name, src, targets)
        adopted.append(name)
    return adopted, skipped


def untrack_skill(paths: Paths, name: str) -> None:
    man = load_manifest(paths.manifest)
    if name not in man["skills"]:
        raise KeyError(name)
    del man["skills"][name]
    save_manifest(paths.manifest, man)
    repo_dir = paths.repo_skills / name
    if repo_dir.is_dir():
        backup_skill(paths, "repo", name, repo_dir)
        shutil.rmtree(repo_dir)


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
            backup_skill(paths, h, name, dst)
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


def prune_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest)
    changes: list[str] = []
    for name, cfg in sorted(man["skills"].items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        for h, skills_dir in paths.harness_skills.items():
            if h in targets:
                continue
            dst = skills_dir / name
            if not dst.is_dir():
                continue
            changes.append(f"{name} -x {h}")
            if dry_run:
                continue
            backup_skill(paths, h, name, dst)
            shutil.rmtree(dst)
    return changes


def cmd_status(paths: Paths) -> None:
    names = list(paths.harness_skills)
    rows = compute_states(paths)
    w = {h: max(len(h), 10) for h in names}
    print(f"{'SKILL':32} {'REPO':5} " + " ".join(f"{h:{w[h]}}" for h in names))
    for r in rows:
        cells = " ".join(f"{r[h]:{w[h]}}" for h in names)
        print(f"{r['name']:32} {'yes' if r['repo'] else 'no':5} " + cells)


def _prompt(msg: str, choices: list[str]) -> str:
    joined = "/".join(choices)
    while True:
        ans = input(f"{msg} [{joined}]: ").strip().lower()
        if ans in choices:
            return ans


def _prompt_targets(names: list[str]) -> list[str]:
    while True:
        raw = input(f"  targets (comma-separated from {names}, or 'all'/'ignore'): ").strip().lower()
        if raw == "ignore":
            return ["ignore"]
        if raw == "all":
            return list(names)
        chosen = [x.strip() for x in raw.split(",") if x.strip()]
        if chosen and all(c in names for c in chosen):
            return chosen


def cmd_adopt(paths: Paths) -> None:
    names = list(paths.harness_skills)
    for row in compute_states(paths):
        name = row["name"]
        available = [h for h in names if row[h] in ("untracked", "drift")]
        if not available:
            continue
        status = ", ".join(f"{h}:{row[h]}" for h in names)
        print(f"\nSkill: {name}  ({status})")
        if input("  adopt? [y/N]: ").strip().lower() != "y":
            continue
        source = available[0] if len(available) == 1 else _prompt("  source", available)
        targets = _prompt_targets(names)
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


def cmd_harness_list(paths: Paths) -> None:
    for name, skills in paths.harness_skills.items():
        print(f"{name:16} base={skills.parent}  skills={skills}")


def cmd_plugins_list(paths: Paths) -> None:
    plugins = discover_plugins(paths)
    if not plugins:
        print("no plugins found")
        return
    repo = set(scan(paths.repo_skills))
    print(f"{'PLUGIN':40} {'HARNESS':14} {'SKILLS':7} {'IN-REPO':7}")
    for p in plugins:
        names = [n for n, _ in p["skills"]]
        in_repo = sum(1 for n in names if n in repo)
        print(f"{p['plugin']:40} {p['harness']:14} {len(names):<7} {in_repo:<7}")


def cmd_plugins_adopt(paths: Paths) -> None:
    registered = list(paths.harness_skills)
    for p in discover_plugins(paths):
        skills = [n for n, _ in p["skills"]]
        print(f"\nPlugin: {p['plugin']}  ({len(skills)} skills, from {p['harness']})")
        if input("  adopt whole plugin? [y/N]: ").strip().lower() != "y":
            continue
        targets = _prompt_targets(registered)
        adopted, skipped = adopt_plugin(paths, p, targets)
        msg = f"  adopted {len(adopted)} skills -> {targets}"
        if skipped:
            msg += f"; skipped (name already in repo): {skipped}"
        print(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-sync")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show skill states across harnesses")
    sub.add_parser("adopt", help="interactively import skills into the repo")
    ap = sub.add_parser("apply", help="push manifest skills to harnesses")
    ap.add_argument("--dry-run", action="store_true")
    hp = sub.add_parser("harness", help="manage the harness registry")
    hsub = hp.add_subparsers(dest="haction", required=True)
    hsub.add_parser("list", help="list registered harnesses")
    ha = hsub.add_parser("add", help="add/update a harness")
    ha.add_argument("name")
    ha.add_argument("base")
    hr = hsub.add_parser("remove", help="remove a harness")
    hr.add_argument("name")
    pp = sub.add_parser("plugins", help="discover and adopt plugin-bundled skills")
    psub = pp.add_subparsers(dest="paction", required=True)
    psub.add_parser("list", help="list discovered plugin skills")
    psub.add_parser("adopt", help="interactively adopt whole plugins into the repo")
    sub.add_parser("tui", help="launch the full-screen dashboard (requires textual)")
    args = parser.parse_args(argv)

    try:
        paths = resolve_paths(Path(__file__).resolve().parent)
    except json.JSONDecodeError as e:
        print(f"error: invalid harnesses.json: {e}", file=sys.stderr)
        return 2

    if args.cmd == "status":
        cmd_status(paths)
    elif args.cmd == "adopt":
        cmd_adopt(paths)
    elif args.cmd == "apply":
        cmd_apply(paths, args.dry_run)
    elif args.cmd == "harness":
        if args.haction == "list":
            cmd_harness_list(paths)
        elif args.haction == "add":
            harness_add(paths, args.name, args.base)
            print(f"added harness '{args.name}' -> {args.base}")
        elif args.haction == "remove":
            harness_remove(paths, args.name)
            print(f"removed harness '{args.name}'")
    elif args.cmd == "plugins":
        if args.paction == "list":
            cmd_plugins_list(paths)
        elif args.paction == "adopt":
            cmd_plugins_adopt(paths)
    elif args.cmd == "tui":
        try:
            from harness_tui import run as tui_run
        except ImportError:
            print("error: the TUI requires textual — pip install textual", file=sys.stderr)
            return 2
        tui_run(Path(__file__).resolve().parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
