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
    harness_types: dict[str, str]


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


def infer_type(name: str) -> str:
    return "codex" if name == "codex" else "claude"


def load_harness_types(repo_root: Path) -> dict[str, str]:
    path = registry_path(repo_root)
    if not path.exists():
        return {name: infer_type(name) for name in default_harnesses()}
    data = json.loads(path.read_text())
    return {name: cfg.get("type", infer_type(name))
            for name, cfg in data["harnesses"].items()}


def resolve_paths(repo_root: Path) -> Paths:
    bases = load_harnesses(repo_root)
    return Paths(
        repo_skills=repo_root / "skills",
        manifest=repo_root / "manifest.json",
        backups=repo_root / ".harness-sync-backups",
        registry=registry_path(repo_root),
        harness_skills={name: base / "skills" for name, base in bases.items()},
        harness_types=load_harness_types(repo_root),
    )


KINDS = {
    "skills": {"asset": "dir", "claude_only": False},
    "agents": {"asset": "file", "claude_only": True},
    "commands": {"asset": "file", "claude_only": True},
}


def parse_asset_name(s: str) -> tuple[str, str]:
    if ":" in s:
        kind, _, name = s.partition(":")
        if kind in KINDS:
            return kind, name
    return "skills", s


def format_asset_name(kind: str, name: str) -> str:
    return name if kind == "skills" else f"{kind}:{name}"


def skill_hash(skill_dir: Path) -> str:
    if skill_dir.is_file():
        return hashlib.sha256(skill_dir.read_bytes()).hexdigest()
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
    return {
        d.name: skill_hash(d)
        for d in sorted(skills_dir.iterdir())
        if d.is_dir() and not d.name.startswith(".") and (d / "SKILL.md").exists()
    }


def scan_kind(root: Path, kind: str) -> dict[str, str]:
    if KINDS[kind]["asset"] == "dir":
        return scan(root)
    if not root.is_dir():
        return {}
    return {f.name: skill_hash(f) for f in sorted(root.glob("*.md")) if f.is_file()}


def harness_kind_dir(paths: Paths, harness: str, kind: str) -> Path | None:
    if KINDS[kind]["claude_only"] and paths.harness_types[harness] == "codex":
        return None
    return paths.harness_skills[harness].parent / kind


def repo_kind_dir(paths: Paths, kind: str) -> Path:
    return paths.repo_skills.parent / kind


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
            # canonical layout first so it wins the dedupe over nested layouts
            skill_roots = [install_path / "skills"]
            nested = install_path / "plugins"
            if nested.is_dir():
                skill_roots += sorted(d / "skills" for d in nested.iterdir() if d.is_dir())
            seen: dict[str, Path] = {}
            for root in skill_roots:
                if not root.is_dir():
                    continue
                for d in sorted(root.iterdir()):
                    if d.is_dir() and (d / "SKILL.md").exists() and d.name not in seen:
                        seen[d.name] = d
            if seen:
                plugins.append({"plugin": plugin_key, "harness": harness,
                                "skills": sorted(seen.items())})
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


def harness_add(paths: Paths, name: str, base: str, type: str | None = None) -> None:
    if not paths.registry.exists():
        data = {"harnesses": {n: {"base": str(b)} for n, b in default_harnesses().items()}}
    else:
        data = load_registry(paths.registry)
    entry: dict = {"base": base}
    if type:
        entry["type"] = type
    data["harnesses"][name] = entry
    save_registry(paths.registry, data)


def _require_tomllib():
    try:
        import tomllib
        return tomllib
    except ImportError:
        raise RuntimeError(
            "MCP sync requires Python 3.11+ (tomllib) — run with python3.11 or newer")


def mcp_config_path(base: Path, htype: str) -> Path:
    if htype == "codex":
        return base / "config.toml"
    p = base / ".claude.json"
    if p.exists():
        return p
    if base == Path.home() / ".claude":
        return Path.home() / ".claude.json"
    return p


def read_mcp_servers(path: Path, htype: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    if htype == "codex":
        tomllib = _require_tomllib()
        return tomllib.loads(path.read_text()).get("mcp_servers", {})
    return json.loads(path.read_text()).get("mcpServers", {})


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)  # JSON escaping is valid for TOML basic strings
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise ValueError(f"unsupported TOML value: {v!r}")


def _toml_server_block(name: str, cfg: dict) -> str:
    lines = [f"[mcp_servers.{name}]"]
    subtables = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            subtables[k] = v
            continue
        lines.append(f"{k} = {_toml_value(v)}")
    for k, sub in subtables.items():
        lines.append(f"\n[mcp_servers.{name}.{k}]")
        for kk, vv in sub.items():
            lines.append(f"{kk} = {_toml_value(vv)}")
    return "\n".join(lines) + "\n"


def _strip_mcp_blocks(text: str, names: set[str]) -> str:
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            header = stripped[1:-1]
            if header.startswith("mcp_servers."):
                skip = header.split(".")[1] in names
            else:
                skip = False
        if not skip:
            out.append(line)
    return "".join(out)


def write_mcp_servers(path: Path, htype: str, servers: dict[str, dict]) -> None:
    if htype == "codex":
        _require_tomllib()  # version gate before touching anything
        text = path.read_text() if path.exists() else ""
        text = _strip_mcp_blocks(text, set(servers)).rstrip("\n")
        blocks = "\n".join(_toml_server_block(n, c) for n, c in sorted(servers.items()))
        path.write_text((text + "\n\n" if text else "") + blocks)
    else:
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault("mcpServers", {}).update(servers)
        path.write_text(json.dumps(data, indent=2) + "\n")


def harness_remove(paths: Paths, name: str) -> None:
    data = load_registry(paths.registry)
    data["harnesses"].pop(name, None)
    save_registry(paths.registry, data)


def compute_states(paths: Paths, kind: str = "skills") -> list[dict]:
    repo = scan_kind(repo_kind_dir(paths, kind), kind)
    names = list(paths.harness_skills)
    harness = {}
    for h in names:
        hd = harness_kind_dir(paths, h, kind)
        harness[h] = scan_kind(hd, kind) if hd is not None else {}
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
    if dst.is_dir():
        shutil.rmtree(dst)
    elif dst.exists():
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dst)
    else:
        shutil.copytree(src, dst)


def backup_skill(paths: Paths, label: str, name: str, src: Path) -> None:
    backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / label / name
    backup.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, backup)
    else:
        shutil.copytree(src, backup)


def import_skill(paths: Paths, name: str, src_dir: Path, targets: list[str],
                 kind: str = "skills") -> None:
    copy_skill(src_dir, repo_kind_dir(paths, kind) / name)
    man = load_manifest(paths.manifest)
    man.setdefault(kind, {})[name] = {"targets": list(targets)}
    save_manifest(paths.manifest, man)


def adopt_skill(paths: Paths, name: str, source_harness: str, targets: list[str],
                kind: str = "skills") -> None:
    src = harness_kind_dir(paths, source_harness, kind) / name
    import_skill(paths, name, src, targets, kind)


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


def refresh_skill(paths: Paths, name: str, source_harness: str, kind: str = "skills") -> None:
    man = load_manifest(paths.manifest)
    if name not in man.get(kind, {}):
        raise KeyError(name)
    repo_asset = repo_kind_dir(paths, kind) / name
    if repo_asset.exists():
        backup_skill(paths, "repo", name, repo_asset)
    copy_skill(harness_kind_dir(paths, source_harness, kind) / name, repo_asset)


def _remove_asset(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def untrack_skill(paths: Paths, name: str, kind: str = "skills") -> None:
    man = load_manifest(paths.manifest)
    if name not in man.get(kind, {}):
        raise KeyError(name)
    del man[kind][name]
    save_manifest(paths.manifest, man)
    repo_asset = repo_kind_dir(paths, kind) / name
    if repo_asset.exists():
        backup_skill(paths, "repo", name, repo_asset)
        _remove_asset(repo_asset)


def apply_skill(paths: Paths, name: str, targets: list[str], dry_run: bool = False,
                kind: str = "skills") -> list[str]:
    src = repo_kind_dir(paths, kind) / name
    src_hash = skill_hash(src)
    changes: list[str] = []
    for h in targets:
        if h not in paths.harness_skills:
            continue
        hd = harness_kind_dir(paths, h, kind)
        if hd is None:
            print(f"warning: {kind} '{name}' cannot target codex-type harness '{h}' — skipping",
                  file=sys.stderr)
            continue
        dst = hd / name
        if dst.exists() and skill_hash(dst) == src_hash:
            continue
        changes.append(f"{format_asset_name(kind, name)} -> {h}")
        if dry_run:
            continue
        if dst.exists():
            backup_skill(paths, h, name, dst)
        copy_skill(src, dst)
    return changes


def apply_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest)
    changes: list[str] = []
    for kind in KINDS:
        for name, cfg in sorted(man.get(kind, {}).items()):
            targets = cfg.get("targets", [])
            if "ignore" in targets:
                continue
            for t in targets:
                if t not in paths.harness_skills:
                    print(f"warning: {kind} '{name}' targets unknown harness '{t}' — skipping",
                          file=sys.stderr)
            changes += apply_skill(paths, name, targets, dry_run, kind)
    return changes


def prune_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest)
    changes: list[str] = []
    for kind in KINDS:
        for name, cfg in sorted(man.get(kind, {}).items()):
            targets = cfg.get("targets", [])
            if "ignore" in targets:
                continue
            for h in paths.harness_skills:
                if h in targets:
                    continue
                hd = harness_kind_dir(paths, h, kind)
                if hd is None:
                    continue
                dst = hd / name
                if not dst.exists():
                    continue
                changes.append(f"{format_asset_name(kind, name)} -x {h}")
                if dry_run:
                    continue
                backup_skill(paths, h, name, dst)
                _remove_asset(dst)
    return changes


def _mcp_harness_servers(paths: Paths) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    for h, skills_dir in paths.harness_skills.items():
        htype = paths.harness_types[h]
        result[h] = read_mcp_servers(mcp_config_path(skills_dir.parent, htype), htype)
    return result


def mcp_states(paths: Paths) -> list[dict]:
    man = load_manifest(paths.manifest).get("mcp", {})
    harness = _mcp_harness_servers(paths)
    names = set(man) | {n for m in harness.values() for n in m}
    rows = []
    for name in sorted(names):
        tracked = man.get(name)
        row = {"name": name, "repo": tracked is not None}
        for h in paths.harness_skills:
            cfg = harness[h].get(name)
            if cfg is None:
                row[h] = "absent"
            elif tracked is None:
                row[h] = "untracked"
            elif cfg == tracked["config"]:
                row[h] = "synced"
            else:
                row[h] = "drift"
        rows.append(row)
    return rows


def mcp_adopt_server(paths: Paths, name: str, source_harness: str, targets: list[str]) -> None:
    htype = paths.harness_types[source_harness]
    servers = read_mcp_servers(
        mcp_config_path(paths.harness_skills[source_harness].parent, htype), htype)
    man = load_manifest(paths.manifest)
    man.setdefault("mcp", {})[name] = {"targets": list(targets), "config": servers[name]}
    save_manifest(paths.manifest, man)


def mcp_apply_all(paths: Paths, dry_run: bool = False) -> list[str]:
    man = load_manifest(paths.manifest).get("mcp", {})
    current = _mcp_harness_servers(paths)
    pending: dict[str, dict[str, dict]] = {}
    changes: list[str] = []
    for name, cfg in sorted(man.items()):
        targets = cfg.get("targets", [])
        if "ignore" in targets:
            continue
        for t in targets:
            if t not in paths.harness_skills:
                print(f"warning: mcp server '{name}' targets unknown harness '{t}' — skipping",
                      file=sys.stderr)
                continue
            if current[t].get(name) == cfg["config"]:
                continue
            pending.setdefault(t, {})[name] = cfg["config"]
            changes.append(f"{name} -> {t}")
    if not dry_run:
        for h, servers in pending.items():
            htype = paths.harness_types[h]
            path = mcp_config_path(paths.harness_skills[h].parent, htype)
            if path.exists():
                backup = paths.backups / datetime.now().strftime("%Y%m%dT%H%M%S") / h / "_mcp" / path.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
            write_mcp_servers(path, htype, servers)
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


def cmd_apply(paths: Paths, dry_run: bool, prune: bool = False) -> None:
    changes = apply_all(paths, dry_run)
    if prune:
        changes += prune_all(paths, dry_run)
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


def cmd_mcp_list(paths: Paths) -> None:
    names = list(paths.harness_skills)
    rows = mcp_states(paths)
    if not rows:
        print("no mcp servers found")
        return
    w = {h: max(len(h), 10) for h in names}
    print(f"{'SERVER':24} {'REPO':5} " + " ".join(f"{h:{w[h]}}" for h in names))
    for r in rows:
        cells = " ".join(f"{r[h]:{w[h]}}" for h in names)
        print(f"{r['name']:24} {'yes' if r['repo'] else 'no':5} " + cells)


def cmd_mcp_adopt(paths: Paths) -> None:
    names = list(paths.harness_skills)
    for row in mcp_states(paths):
        name = row["name"]
        available = [h for h in names if row[h] in ("untracked", "drift")]
        if not available:
            continue
        status = ", ".join(f"{h}:{row[h]}" for h in names)
        print(f"\nMCP server: {name}  ({status})")
        if input("  adopt? [y/N]: ").strip().lower() != "y":
            continue
        source = available[0] if len(available) == 1 else _prompt("  source", available)
        targets = _prompt_targets(names)
        mcp_adopt_server(paths, name, source, targets)
        print(f"  adopted {name} from {source} -> {targets}")


def cmd_mcp_apply(paths: Paths, dry_run: bool) -> None:
    changes = mcp_apply_all(paths, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    if not changes:
        print("nothing to do")
        return
    for c in changes:
        print(f"{prefix}{c}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-sync")
    sub = parser.add_subparsers(dest="cmd")  # optional: no subcommand -> tui
    sub.add_parser("status", help="show skill states across harnesses")
    sub.add_parser("adopt", help="interactively import skills into the repo")
    ap = sub.add_parser("apply", help="push manifest skills to harnesses")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true",
                    help="also delete de-targeted tracked skills from harnesses")
    hp = sub.add_parser("harness", help="manage the harness registry")
    hsub = hp.add_subparsers(dest="haction", required=True)
    hsub.add_parser("list", help="list registered harnesses")
    ha = hsub.add_parser("add", help="add/update a harness")
    ha.add_argument("name")
    ha.add_argument("base")
    ha.add_argument("type", nargs="?", default=None,
                    help="harness type: claude or codex (default: inferred)")
    hr = hsub.add_parser("remove", help="remove a harness")
    hr.add_argument("name")
    pp = sub.add_parser("plugins", help="discover and adopt plugin-bundled skills")
    psub = pp.add_subparsers(dest="paction", required=True)
    psub.add_parser("list", help="list discovered plugin skills")
    psub.add_parser("adopt", help="interactively adopt whole plugins into the repo")
    sub.add_parser("tui", help="launch the full-screen dashboard (requires textual)")
    up = sub.add_parser("untrack", help="stop managing a skill (repo copy backed up; harnesses untouched)")
    up.add_argument("name")
    rp = sub.add_parser("refresh", help="re-import a tracked skill's content from a harness")
    rp.add_argument("name")
    rp.add_argument("source", nargs="?", default=None,
                    help="source harness (default: the only drifted one)")
    mp = sub.add_parser("mcp", help="sync MCP server definitions between harnesses")
    msub = mp.add_subparsers(dest="maction", required=True)
    msub.add_parser("list", help="show MCP server states across harnesses")
    msub.add_parser("adopt", help="interactively import MCP servers into the manifest")
    map_ = msub.add_parser("apply", help="push manifest MCP servers to harnesses")
    map_.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd is None:
        args.cmd = "tui"

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
        cmd_apply(paths, args.dry_run, args.prune)
    elif args.cmd == "harness":
        if args.haction == "list":
            cmd_harness_list(paths)
        elif args.haction == "add":
            harness_add(paths, args.name, args.base, args.type)
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
    elif args.cmd == "untrack":
        try:
            untrack_skill(paths, args.name)
        except KeyError:
            print(f"error: '{args.name}' is not tracked", file=sys.stderr)
            return 1
        print(f"untracked '{args.name}' (repo copy backed up; harnesses untouched)")
    elif args.cmd == "refresh":
        if args.name not in load_manifest(paths.manifest)["skills"]:
            print(f"error: '{args.name}' is not tracked", file=sys.stderr)
            return 1
        source = args.source
        if source is None:
            row = next((r for r in compute_states(paths) if r["name"] == args.name), None)
            drifted = [h for h in paths.harness_skills if row and row[h] == "drift"]
            if len(drifted) != 1:
                print(f"error: specify a source harness (drifted in: {drifted or 'none'})",
                      file=sys.stderr)
                return 1
            source = drifted[0]
        if source not in paths.harness_skills:
            print(f"error: unknown harness '{source}'", file=sys.stderr)
            return 1
        try:
            refresh_skill(paths, args.name, source)
        except KeyError:
            print(f"error: '{args.name}' is not tracked", file=sys.stderr)
            return 1
        print(f"refreshed '{args.name}' from {source} (previous repo copy backed up)")
    elif args.cmd == "mcp":
        try:
            if args.maction == "list":
                cmd_mcp_list(paths)
            elif args.maction == "adopt":
                cmd_mcp_adopt(paths)
            elif args.maction == "apply":
                cmd_mcp_apply(paths, args.dry_run)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
