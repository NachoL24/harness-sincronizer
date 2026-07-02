import contextlib
import io
import json
import os
import tempfile
from pathlib import Path

import harness_sync as hs


def _make_skill(base: Path, name: str, files: dict[str, str]) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in files.items():
        p = d / fn
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_skill_hash_is_order_and_path_sensitive():
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        a = _make_skill(base, "a", {"SKILL.md": "x", "extra.md": "y"})
        b = _make_skill(base, "b", {"extra.md": "y", "SKILL.md": "x"})
        c = _make_skill(base, "c", {"SKILL.md": "different", "extra.md": "y"})
        assert hs.skill_hash(a) == hs.skill_hash(b)   # order-independent
        assert hs.skill_hash(a) != hs.skill_hash(c)   # content-sensitive


def test_scan_missing_dir_is_empty():
    with tempfile.TemporaryDirectory() as t:
        assert hs.scan(Path(t) / "nope") == {}


def test_scan_lists_skill_dirs_only():
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        _make_skill(base, "one", {"SKILL.md": "1"})
        (base / "loose.txt").write_text("ignore me")
        result = hs.scan(base)
        assert set(result) == {"one"}


def test_resolve_paths_honors_env():
    with tempfile.TemporaryDirectory() as t:
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(t) / "cc")
        os.environ["CODEX_HOME"] = str(Path(t) / "cx")
        try:
            paths = hs.resolve_paths(Path(t) / "repo")
            assert paths.harness_skills["claude"] == Path(t) / "cc" / "skills"
            assert paths.harness_skills["codex"] == Path(t) / "cx" / "skills"
            assert paths.repo_skills == Path(t) / "repo" / "skills"
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
            del os.environ["CODEX_HOME"]


def test_load_manifest_absent_returns_empty():
    with tempfile.TemporaryDirectory() as t:
        assert hs.load_manifest(Path(t) / "manifest.json") == {"skills": {}}


def test_manifest_roundtrip():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "manifest.json"
        data = {"skills": {"branch-pr": {"targets": ["claude", "codex"]}}}
        hs.save_manifest(p, data)
        assert hs.load_manifest(p) == data
        assert p.read_text().endswith("\n")


def _paths_in(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={"claude": t / "cc" / "skills", "codex": t / "cx" / "skills"},
        harness_types={"claude": "claude", "codex": "codex"},
    )


def test_compute_states_covers_all_cases():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["codex"], "alpha", {"SKILL.md": "OLD"})
        _make_skill(p.harness_skills["codex"], "beta", {"SKILL.md": "x"})

        rows = {r["name"]: r for r in hs.compute_states(p)}

        assert rows["alpha"]["repo"] is True
        assert rows["alpha"]["claude"] == "synced"
        assert rows["alpha"]["codex"] == "drift"
        assert rows["beta"]["repo"] is False
        assert rows["beta"]["claude"] == "absent"
        assert rows["beta"]["codex"] == "untracked"


def test_adopt_skill_imports_and_records():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.harness_skills["claude"], "gamma", {"SKILL.md": "body"})

        hs.adopt_skill(p, "gamma", "claude", ["claude", "codex"])

        assert (p.repo_skills / "gamma" / "SKILL.md").read_text() == "body"
        man = hs.load_manifest(p.manifest)
        assert man["skills"]["gamma"] == {"targets": ["claude", "codex"]}


def test_apply_pushes_backs_up_and_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "delta", {"SKILL.md": "new"})
        _make_skill(p.harness_skills["codex"], "delta", {"SKILL.md": "old"})

        changes = hs.apply_skill(p, "delta", ["codex"])
        assert changes == ["delta -> codex"]
        assert (p.harness_skills["codex"] / "delta" / "SKILL.md").read_text() == "new"
        backups = list(p.backups.rglob("delta/SKILL.md"))
        assert backups and backups[0].read_text() == "old"

        assert hs.apply_skill(p, "delta", ["codex"]) == []


def test_apply_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "eps", {"SKILL.md": "new"})
        changes = hs.apply_skill(p, "eps", ["claude"], dry_run=True)
        assert changes == ["eps -> claude"]
        assert not (p.harness_skills["claude"] / "eps").exists()


def test_apply_all_skips_ignored_and_leaves_untracked():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "keep", {"SKILL.md": "k"})
        _make_skill(p.repo_skills, "skip", {"SKILL.md": "s"})
        hs.save_manifest(p.manifest, {"skills": {
            "keep": {"targets": ["claude"]},
            "skip": {"targets": ["ignore"]},
        }})
        _make_skill(p.harness_skills["claude"], "foreign", {"SKILL.md": "f"})

        changes = hs.apply_all(p)
        assert changes == ["keep -> claude"]
        assert (p.harness_skills["claude"] / "keep").exists()
        assert not (p.harness_skills["claude"] / "skip").exists()
        assert (p.harness_skills["claude"] / "foreign" / "SKILL.md").read_text() == "f"


def _make_plugin(harness_base: Path, plugin_key: str, install_path: Path, skill_names: list[str]) -> None:
    for s in skill_names:
        d = install_path / "skills" / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {s}")
    pj = harness_base / "plugins" / "installed_plugins.json"
    pj.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "plugins": {}}
    if pj.exists():
        data = json.loads(pj.read_text())
    data["plugins"].setdefault(plugin_key, []).append(
        {"installPath": str(install_path), "version": "1.0.0"}
    )
    pj.write_text(json.dumps(data))


def test_read_installed_plugins_tolerant():
    with tempfile.TemporaryDirectory() as t:
        assert hs.read_installed_plugins(Path(t) / "nope") == []
        pdir = Path(t) / "plugins"
        pdir.mkdir()
        (pdir / "installed_plugins.json").write_text("{bad")
        assert hs.read_installed_plugins(pdir) == []


def test_read_installed_plugins_parses_active():
    with tempfile.TemporaryDirectory() as t:
        pdir = Path(t) / "plugins"
        pdir.mkdir()
        (pdir / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
            "sp@mkt": [{"installPath": "/x/sp/1.0", "version": "1.0"}]}}))
        assert hs.read_installed_plugins(pdir) == [("sp@mkt", Path("/x/sp/1.0"))]


def test_discover_plugins_finds_skills_tagged():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)  # claude base = t/cc, codex base = t/cx
        install = t / "cc" / "plugins" / "cache" / "sp" / "1.0"
        _make_plugin(t / "cc", "sp@mkt", install, ["brainstorming", "tdd"])
        plugins = hs.discover_plugins(p)
        assert len(plugins) == 1
        assert plugins[0]["plugin"] == "sp@mkt"
        assert plugins[0]["harness"] == "claude"
        assert sorted(n for n, _ in plugins[0]["skills"]) == ["brainstorming", "tdd"]


def test_load_harnesses_absent_uses_env_defaults():
    with tempfile.TemporaryDirectory() as t:
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(t) / "cc")
        os.environ["CODEX_HOME"] = str(Path(t) / "cx")
        try:
            h = hs.load_harnesses(Path(t) / "repo")
            assert h == {"claude": Path(t) / "cc", "codex": Path(t) / "cx"}
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
            del os.environ["CODEX_HOME"]


def test_load_harnesses_present_parses_and_expands():
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t) / "repo"
        repo.mkdir()
        (repo / "harnesses.json").write_text(
            '{"harnesses": {"work": {"base": "~/wk"}, "codex": {"base": "/abs/cx"}}}'
        )
        h = hs.load_harnesses(repo)
        assert h["work"] == Path.home() / "wk"
        assert h["codex"] == Path("/abs/cx")
        assert list(h) == ["work", "codex"]  # insertion order preserved


def test_load_harnesses_invalid_json_raises():
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t) / "repo"
        repo.mkdir()
        (repo / "harnesses.json").write_text("{not valid")
        raised = False
        try:
            hs.load_harnesses(repo)
        except json.JSONDecodeError:
            raised = True
        assert raised


def _paths_in_3(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={
            "claude": t / "cc" / "skills",
            "claude-perso": t / "cp" / "skills",
            "codex": t / "cx" / "skills",
        },
        harness_types={"claude": "claude", "claude-perso": "claude", "codex": "codex"},
    )


def test_compute_states_three_harnesses():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in_3(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})       # synced
        _make_skill(p.harness_skills["claude-perso"], "alpha", {"SKILL.md": "OLD"})  # drift
        # codex: absent for alpha
        rows = {r["name"]: r for r in hs.compute_states(p)}
        assert rows["alpha"]["claude"] == "synced"
        assert rows["alpha"]["claude-perso"] == "drift"
        assert rows["alpha"]["codex"] == "absent"


def test_apply_all_warns_and_skips_unknown_target():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in_3(t)
        _make_skill(p.repo_skills, "beta", {"SKILL.md": "b"})
        hs.save_manifest(p.manifest, {"skills": {
            "beta": {"targets": ["claude-perso", "ghost"]},
        }})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = hs.apply_all(p)
        assert changes == ["beta -> claude-perso"]           # known target applied
        assert (p.harness_skills["claude-perso"] / "beta").exists()
        assert "ghost" in err.getvalue()                     # unknown target warned


def test_harness_add_seeds_defaults_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        p.registry.parent.mkdir(parents=True, exist_ok=True)
        assert not p.registry.exists()
        hs.harness_add(p, "claude-perso", "~/.claude-perso")
        data = hs.load_registry(p.registry)
        assert set(data["harnesses"]) == {"claude", "codex", "claude-perso"}
        assert data["harnesses"]["claude-perso"] == {"base": "~/.claude-perso"}


def test_harness_remove_deletes_entry():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        p.registry.parent.mkdir(parents=True, exist_ok=True)
        hs.save_registry(p.registry, {"harnesses": {
            "claude": {"base": "~/.claude"}, "codex": {"base": "~/.codex"},
        }})
        hs.harness_remove(p, "codex")
        data = hs.load_registry(p.registry)
        assert set(data["harnesses"]) == {"claude"}


def test_import_skill_copies_and_records():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        src = t / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("x")
        hs.import_skill(p, "foo", src, ["codex"])
        assert (p.repo_skills / "foo" / "SKILL.md").read_text() == "x"
        assert hs.load_manifest(p.manifest)["skills"]["foo"] == {"targets": ["codex"]}


def test_adopt_plugin_imports_all_and_skips_collision():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "dup", {"SKILL.md": "existing"})  # collision
        install = t / "cc" / "plugins" / "sp" / "1.0"
        _make_plugin(t / "cc", "sp@mkt", install, ["fresh", "dup"])
        plugin = hs.discover_plugins(p)[0]
        adopted, skipped = hs.adopt_plugin(p, plugin, ["codex"])
        assert adopted == ["fresh"]
        assert skipped == ["dup"]
        assert (p.repo_skills / "fresh" / "SKILL.md").exists()
        assert (p.repo_skills / "dup" / "SKILL.md").read_text() == "existing"  # untouched
        man = hs.load_manifest(p.manifest)
        assert man["skills"]["fresh"] == {"targets": ["codex"]}
        assert "dup" not in man["skills"]


def test_tui_smoke():
    try:
        import textual  # noqa: F401
    except ImportError:
        return  # textual not installed — smoke test is a no-op
    import asyncio
    from textual.widgets import DataTable
    from harness_tui import HarnessSyncApp

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        (repo / "skills").mkdir(parents=True)
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": str(t / "cc")}, "codex": {"base": str(t / "cx")}}}))
        _make_skill(t / "cc" / "skills", "alpha", {"SKILL.md": "x"})

        async def go():
            app = HarnessSyncApp(repo)
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one("#status-table", DataTable)
                assert table.row_count == 1

        asyncio.run(go())


def test_tui_harness_add_via_real_click():
    try:
        import textual  # noqa: F401
    except ImportError:
        return  # textual not installed — smoke test is a no-op
    import asyncio
    from textual.widgets import DataTable, Input
    from harness_tui import HarnessSyncApp

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        (repo / "skills").mkdir(parents=True)
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": str(t / "cc")}, "codex": {"base": str(t / "cx")}}}))

        async def go():
            app = HarnessSyncApp(repo)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app.query_one("TabbedContent").active = "tab-harness"
                await pilot.pause()
                app.query_one("#harness-name", Input).value = "work"
                app.query_one("#harness-base", Input).value = str(t / "wk")
                # a REAL click — fails with OutOfBounds if the button is
                # pushed off-screen (regression: Input width 100%)
                await pilot.click("#harness-add-btn")
                await pilot.pause()
                table = app.query_one("#harness-table", DataTable)
                assert table.row_count == 3, table.row_count

        asyncio.run(go())


def test_untrack_removes_manifest_and_repo_with_backup():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["claude"]}}})

        hs.untrack_skill(p, "alpha")

        assert "alpha" not in hs.load_manifest(p.manifest)["skills"]
        assert not (p.repo_skills / "alpha").exists()                      # repo copy gone
        backups = list(p.backups.rglob("repo/alpha/SKILL.md"))
        assert backups and backups[0].read_text() == "v1"                  # backed up
        assert (p.harness_skills["claude"] / "alpha" / "SKILL.md").exists()  # harness untouched


def test_untrack_unknown_raises():
    with tempfile.TemporaryDirectory() as tmp:
        p = _paths_in(Path(tmp))
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        raised = False
        try:
            hs.untrack_skill(p, "ghost")
        except KeyError:
            raised = True
        assert raised


def test_prune_removes_detargeted_with_backup():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "old"})
        _make_skill(p.harness_skills["codex"], "alpha", {"SKILL.md": "v1"})
        # alpha targeted only to codex -> claude copy is de-targeted
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["codex"]}}})

        changes = hs.prune_all(p)

        assert changes == ["alpha -x claude"]
        assert not (p.harness_skills["claude"] / "alpha").exists()
        assert (p.harness_skills["codex"] / "alpha").exists()              # targeted stays
        backups = list(p.backups.rglob("claude/alpha/SKILL.md"))
        assert backups and backups[0].read_text() == "old"


def test_prune_spares_ignore_and_foreign():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "kept", {"SKILL.md": "k"})
        _make_skill(p.harness_skills["claude"], "kept", {"SKILL.md": "k"})
        _make_skill(p.harness_skills["claude"], "foreign", {"SKILL.md": "f"})
        hs.save_manifest(p.manifest, {"skills": {"kept": {"targets": ["ignore"]}}})

        changes = hs.prune_all(p)

        assert changes == []
        assert (p.harness_skills["claude"] / "kept").exists()      # ignore -> untouched
        assert (p.harness_skills["claude"] / "foreign").exists()   # unmanifested -> untouched


def test_prune_dry_run_deletes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "v1"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "v1"})
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["codex"]}}})

        changes = hs.prune_all(p, dry_run=True)

        assert changes == ["alpha -x claude"]
        assert (p.harness_skills["claude"] / "alpha").exists()


def test_tui_untrack_binding():
    try:
        import textual  # noqa: F401
    except ImportError:
        return
    import asyncio
    from harness_tui import HarnessSyncApp

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        (repo / "skills").mkdir(parents=True)
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": str(t / "cc")}, "codex": {"base": str(t / "cx")}}}))
        _make_skill(repo / "skills", "alpha", {"SKILL.md": "x"})
        _make_skill(t / "cc" / "skills", "alpha", {"SKILL.md": "x"})
        hs.save_manifest(repo / "manifest.json", {"skills": {"alpha": {"targets": ["claude"]}}})

        async def go():
            app = HarnessSyncApp(repo)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("u")
                await pilot.pause()
                assert "alpha" not in hs.load_manifest(repo / "manifest.json")["skills"]
                assert not (repo / "skills" / "alpha").exists()
                assert (t / "cc" / "skills" / "alpha").exists()  # harness untouched

        asyncio.run(go())


def test_discover_plugins_nested_layout_with_dedupe():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        install = t / "cc" / "plugins" / "cache" / "pony" / "abc"
        # "lazy" exists ONLY in the nested layout <installPath>/plugins/<x>/skills/
        nested_lazy = install / "plugins" / "pony" / "skills" / "lazy"
        nested_lazy.mkdir(parents=True)
        (nested_lazy / "SKILL.md").write_text("# nested lazy")
        # "dup" exists in BOTH layouts (canonical must win the dedupe)
        nested_dup = install / "plugins" / "pony" / "skills" / "dup"
        nested_dup.mkdir(parents=True)
        (nested_dup / "SKILL.md").write_text("# nested dup")
        canonical_dup = install / "skills" / "dup"
        canonical_dup.mkdir(parents=True)
        (canonical_dup / "SKILL.md").write_text("# canonical dup")
        pj = t / "cc" / "plugins" / "installed_plugins.json"
        pj.parent.mkdir(parents=True, exist_ok=True)
        pj.write_text(json.dumps({"version": 2, "plugins": {
            "pony@mkt": [{"installPath": str(install), "version": "1"}]}}))

        plugins = hs.discover_plugins(p)

        assert len(plugins) == 1
        names = [n for n, _ in plugins[0]["skills"]]
        assert names == ["dup", "lazy"]                                  # nested-only found
        assert dict(plugins[0]["skills"])["dup"] == canonical_dup        # canonical wins


def test_harness_types_inferred_and_explicit():
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t) / "repo"
        repo.mkdir()
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": "~/.claude"},
            "codex": {"base": "~/.codex"},
            "work": {"base": "~/wk"},
            "cx2": {"base": "~/cx2", "type": "codex"},
        }}))
        types = hs.load_harness_types(repo)
        assert types == {"claude": "claude", "codex": "codex",
                         "work": "claude", "cx2": "codex"}


def test_resolve_paths_carries_types():
    with tempfile.TemporaryDirectory() as t:
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(t) / "cc")
        os.environ["CODEX_HOME"] = str(Path(t) / "cx")
        try:
            paths = hs.resolve_paths(Path(t) / "repo")
            assert paths.harness_types == {"claude": "claude", "codex": "codex"}
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
            del os.environ["CODEX_HOME"]


def test_harness_add_with_type():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        p.registry.parent.mkdir(parents=True, exist_ok=True)
        hs.harness_add(p, "cx2", "~/cx2", "codex")
        data = hs.load_registry(p.registry)
        assert data["harnesses"]["cx2"] == {"base": "~/cx2", "type": "codex"}


def _tomllib_available() -> bool:
    try:
        import tomllib  # noqa: F401
        return True
    except ImportError:
        return False


def test_mcp_config_path_rules():
    with tempfile.TemporaryDirectory() as t:
        base = Path(t) / "cx"
        assert hs.mcp_config_path(base, "codex") == base / "config.toml"
        cbase = Path(t) / "cc"
        cbase.mkdir()
        (cbase / ".claude.json").write_text("{}")
        assert hs.mcp_config_path(cbase, "claude") == cbase / ".claude.json"
        home_claude = Path.home() / ".claude"
        if not (home_claude / ".claude.json").exists() and (Path.home() / ".claude.json").exists():
            assert hs.mcp_config_path(home_claude, "claude") == Path.home() / ".claude.json"


def test_read_mcp_servers_json_and_missing():
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / ".claude.json"
        assert hs.read_mcp_servers(f, "claude") == {}
        f.write_text(json.dumps({"other": 1, "mcpServers": {
            "srv": {"command": "x", "args": ["a"], "env": {"K": "v"}}}}))
        servers = hs.read_mcp_servers(f, "claude")
        assert servers["srv"]["command"] == "x"


def test_read_mcp_servers_toml():
    if not _tomllib_available():
        return
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "config.toml"
        f.write_text('model = "gpt"\n\n[mcp_servers.srv]\ncommand = "x"\nargs = ["a"]\n\n[mcp_servers.srv.env]\nK = "v"\n')
        servers = hs.read_mcp_servers(f, "codex")
        assert servers == {"srv": {"command": "x", "args": ["a"], "env": {"K": "v"}}}


def test_write_mcp_servers_json_preserves_other_keys():
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / ".claude.json"
        f.write_text(json.dumps({"theme": "dark", "mcpServers": {
            "keep": {"command": "k"}, "old": {"command": "v1"}}}))
        hs.write_mcp_servers(f, "claude", {"old": {"command": "v2"}, "new": {"command": "n"}})
        data = json.loads(f.read_text())
        assert data["theme"] == "dark"                       # unrelated key preserved
        assert data["mcpServers"]["keep"] == {"command": "k"}  # unmanaged preserved
        assert data["mcpServers"]["old"] == {"command": "v2"}  # updated
        assert data["mcpServers"]["new"] == {"command": "n"}   # added


def test_write_mcp_servers_toml_splice_preserves_bytes():
    if not _tomllib_available():
        return
    import tomllib
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "config.toml"
        f.write_text(
            '# my precious comment\nmodel = "gpt"\n\n'
            '[mcp_servers.keep]\ncommand = "k"\n\n'
            '[mcp_servers.old]\ncommand = "v1"\n\n[mcp_servers.old.env]\nA = "1"\n'
        )
        hs.write_mcp_servers(f, "codex", {
            "old": {"command": "v2", "args": ["x"], "env": {"B": "2"}},
            "new": {"command": "n"},
        })
        text = f.read_text()
        assert "# my precious comment" in text               # comments preserved
        assert 'model = "gpt"' in text
        data = tomllib.loads(text)
        assert data["mcp_servers"]["keep"] == {"command": "k"}       # unmanaged intact
        assert data["mcp_servers"]["old"] == {"command": "v2", "args": ["x"], "env": {"B": "2"}}
        assert data["mcp_servers"]["new"] == {"command": "n"}


def _mcp_paths(t: Path) -> "hs.Paths":
    p = _paths_in(t)
    (t / "cc").mkdir(parents=True, exist_ok=True)
    (t / "cc" / ".claude.json").write_text(json.dumps({"mcpServers": {
        "alpha": {"command": "a"}, "solo": {"command": "s"}}}))
    (t / "cx").mkdir(parents=True, exist_ok=True)
    (t / "cx" / "config.toml").write_text('model = "gpt"\n\n[mcp_servers.alpha]\ncommand = "OLD"\n')
    p.manifest.parent.mkdir(parents=True, exist_ok=True)
    return p


def test_mcp_states_and_adopt():
    if not _tomllib_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        p = _mcp_paths(Path(tmp))
        rows = {r["name"]: r for r in hs.mcp_states(p)}
        assert rows["alpha"]["claude"] == "untracked"
        assert rows["solo"]["codex"] == "absent"

        hs.mcp_adopt_server(p, "alpha", "claude", ["claude", "codex"])
        man = hs.load_manifest(p.manifest)
        assert man["mcp"]["alpha"] == {"targets": ["claude", "codex"],
                                       "config": {"command": "a"}}
        rows = {r["name"]: r for r in hs.mcp_states(p)}
        assert rows["alpha"]["claude"] == "synced"
        assert rows["alpha"]["codex"] == "drift"   # codex still has OLD


def test_mcp_apply_pushes_both_formats_idempotent():
    if not _tomllib_available():
        return
    import tomllib
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _mcp_paths(t)
        hs.mcp_adopt_server(p, "alpha", "claude", ["claude", "codex"])

        changes = hs.mcp_apply_all(p)
        assert changes == ["alpha -> codex"]                       # claude already synced
        toml_text = (t / "cx" / "config.toml").read_text()
        assert 'model = "gpt"' in toml_text                        # unrelated preserved
        assert tomllib.loads(toml_text)["mcp_servers"]["alpha"] == {"command": "a"}
        assert list(p.backups.rglob("_mcp/config.toml"))           # backup exists

        assert hs.mcp_apply_all(p) == []                           # idempotent


def test_mcp_apply_dry_run_and_unknown_target():
    if not _tomllib_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _mcp_paths(t)
        hs.mcp_adopt_server(p, "alpha", "claude", ["ghost", "codex"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = hs.mcp_apply_all(p, dry_run=True)
        assert changes == ["alpha -> codex"]
        assert "ghost" in err.getvalue()
        assert "OLD" in (t / "cx" / "config.toml").read_text()     # dry-run wrote nothing


def test_default_command_is_tui():
    try:
        import textual  # noqa: F401
    except ImportError:
        return
    import harness_tui
    called = []
    orig = harness_tui.run
    harness_tui.run = lambda root: called.append(root)
    try:
        rc = hs.main([])
        assert rc == 0
        assert called, "main([]) should launch the TUI by default"
    finally:
        harness_tui.run = orig


def test_tui_mcp_tab_adopt():
    try:
        import textual  # noqa: F401
    except ImportError:
        return
    if not _tomllib_available():
        return
    import asyncio
    from textual.widgets import DataTable, SelectionList
    from harness_tui import HarnessSyncApp

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        (repo / "skills").mkdir(parents=True)
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": str(t / "cc")}, "codex": {"base": str(t / "cx")}}}))
        (t / "cc").mkdir(parents=True, exist_ok=True)
        (t / "cc" / ".claude.json").write_text(json.dumps({"mcpServers": {
            "alpha": {"command": "a"}}}))
        (t / "cx").mkdir(parents=True, exist_ok=True)
        (t / "cx" / "config.toml").write_text('model = "gpt"\n')

        async def go():
            app = HarnessSyncApp(repo)
            async with app.run_test(size=(130, 42)) as pilot:
                await pilot.pause()
                table = app.query_one("#mcp-table", DataTable)
                assert table.row_count == 1
                servers = app.query_one("#mcp-servers", SelectionList)
                assert servers.option_count == 1
                servers.select(servers.get_option_at_index(0))
                targets = app.query_one("#mcp-targets", SelectionList)
                for i in range(targets.option_count):
                    opt = targets.get_option_at_index(i)
                    if opt.value == "codex":
                        targets.select(opt)
                app.adopt_selected_mcp()
                await pilot.pause()
                man = hs.load_manifest(repo / "manifest.json")
                assert man["mcp"]["alpha"]["targets"] == ["codex"]
                assert man["mcp"]["alpha"]["config"] == {"command": "a"}

        asyncio.run(go())


def test_scan_filters_dotdirs_and_non_skills():
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        _make_skill(base, "real", {"SKILL.md": "r"})
        _make_skill(base, "_shared", {"SKILL.md": "s"})       # has SKILL.md -> kept
        (base / ".system" / "sub").mkdir(parents=True)        # dot-dir -> filtered
        (base / "not-a-skill").mkdir()                        # no SKILL.md -> filtered
        (base / "not-a-skill" / "readme.md").write_text("x")
        assert set(hs.scan(base)) == {"real", "_shared"}


def test_refresh_skill_updates_repo_with_backup():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        _make_skill(p.repo_skills, "alpha", {"SKILL.md": "old"})
        _make_skill(p.harness_skills["claude"], "alpha", {"SKILL.md": "NEW"})
        hs.save_manifest(p.manifest, {"skills": {"alpha": {"targets": ["claude"]}}})

        hs.refresh_skill(p, "alpha", "claude")

        assert (p.repo_skills / "alpha" / "SKILL.md").read_text() == "NEW"
        backups = list(p.backups.rglob("repo/alpha/SKILL.md"))
        assert backups and backups[0].read_text() == "old"
        # manifest untouched
        assert hs.load_manifest(p.manifest)["skills"]["alpha"] == {"targets": ["claude"]}


def test_refresh_skill_untracked_raises():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _paths_in(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        _make_skill(p.harness_skills["claude"], "ghost", {"SKILL.md": "x"})
        raised = False
        try:
            hs.refresh_skill(p, "ghost", "claude")
        except KeyError:
            raised = True
        assert raised


def test_parse_and_format_asset_name():
    assert hs.parse_asset_name("branch-pr") == ("skills", "branch-pr")
    assert hs.parse_asset_name("agents:sdd-apply.md") == ("agents", "sdd-apply.md")
    assert hs.format_asset_name("skills", "x") == "x"
    assert hs.format_asset_name("agents", "y.md") == "agents:y.md"


def test_scan_kind_files_and_hash_copy_file():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "agents"
        root.mkdir()
        (root / "one.md").write_text("A")
        (root / "two.md").write_text("B")
        (root / "notes.txt").write_text("ignored")
        result = hs.scan_kind(root, "agents")
        assert set(result) == {"one.md", "two.md"}
        assert hs.skill_hash(root / "one.md") != hs.skill_hash(root / "two.md")
        dst = Path(t) / "out" / "one.md"
        hs.copy_skill(root / "one.md", dst)
        assert dst.read_text() == "A"
        assert hs.scan_kind(Path(t) / "missing", "skills") == {}


def test_harness_kind_dir_claude_only():
    with tempfile.TemporaryDirectory() as tmp:
        p = _paths_in(Path(tmp))  # claude:claude, codex:codex
        assert hs.harness_kind_dir(p, "claude", "agents") is not None
        assert hs.harness_kind_dir(p, "codex", "agents") is None      # claude_only
        assert hs.harness_kind_dir(p, "codex", "skills") is not None  # skills everywhere


def _agent_paths(t: Path) -> "hs.Paths":
    return hs.Paths(
        repo_skills=t / "repo" / "skills",
        manifest=t / "repo" / "manifest.json",
        backups=t / "repo" / ".backups",
        registry=t / "repo" / "harnesses.json",
        harness_skills={"claude": t / "cc" / "skills",
                        "claude-perso": t / "cp" / "skills",
                        "codex": t / "cx" / "skills"},
        harness_types={"claude": "claude", "claude-perso": "claude", "codex": "codex"},
    )


def test_agent_states_adopt_apply_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _agent_paths(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        agents = t / "cc" / "agents"
        agents.mkdir(parents=True)
        (agents / "bot.md").write_text("agent body")

        rows = {r["name"]: r for r in hs.compute_states(p, kind="agents")}
        assert rows["bot.md"]["claude"] == "untracked"
        assert rows["bot.md"]["codex"] == "absent"          # claude_only

        hs.adopt_skill(p, "bot.md", "claude", ["claude", "claude-perso"], kind="agents")
        assert (t / "repo" / "agents" / "bot.md").read_text() == "agent body"
        assert hs.load_manifest(p.manifest)["agents"]["bot.md"] == {
            "targets": ["claude", "claude-perso"]}

        changes = hs.apply_all(p)
        assert "agents:bot.md -> claude-perso" in changes
        assert (t / "cp" / "agents" / "bot.md").read_text() == "agent body"
        assert hs.apply_all(p) == []                        # idempotent


def test_agent_apply_skips_codex_target_with_warning():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _agent_paths(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        (t / "repo" / "agents").mkdir(parents=True)
        (t / "repo" / "agents" / "bot.md").write_text("x")
        hs.save_manifest(p.manifest, {"skills": {}, "agents": {
            "bot.md": {"targets": ["codex"]}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = hs.apply_all(p)
        assert changes == []
        assert "codex" in err.getvalue()
        assert not (t / "cx" / "agents").exists()


def test_agent_untrack_refresh_prune():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        p = _agent_paths(t)
        p.manifest.parent.mkdir(parents=True, exist_ok=True)
        agents_cc = t / "cc" / "agents"
        agents_cc.mkdir(parents=True)
        (agents_cc / "bot.md").write_text("v1")
        hs.adopt_skill(p, "bot.md", "claude", ["claude"], kind="agents")

        (agents_cc / "bot.md").write_text("v2")
        hs.refresh_skill(p, "bot.md", "claude", kind="agents")
        assert (t / "repo" / "agents" / "bot.md").read_text() == "v2"

        agents_cp = t / "cp" / "agents"
        agents_cp.mkdir(parents=True)
        (agents_cp / "bot.md").write_text("stray")
        changes = hs.prune_all(p)
        assert changes == ["agents:bot.md -x claude-perso"]
        assert not (agents_cp / "bot.md").exists()

        hs.untrack_skill(p, "bot.md", kind="agents")
        assert "bot.md" not in hs.load_manifest(p.manifest).get("agents", {})
        assert not (t / "repo" / "agents" / "bot.md").exists()
        assert (agents_cc / "bot.md").exists()


def test_tui_asset_kinds_in_status_and_adopt():
    try:
        import textual  # noqa: F401
    except ImportError:
        return
    import asyncio
    from textual.widgets import DataTable, SelectionList
    from harness_tui import HarnessSyncApp

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        (repo / "skills").mkdir(parents=True)
        (repo / "harnesses.json").write_text(json.dumps({"harnesses": {
            "claude": {"base": str(t / "cc")},
            "claude-perso": {"base": str(t / "cp")},
            "codex": {"base": str(t / "cx")}}}))
        agents = t / "cc" / "agents"
        agents.mkdir(parents=True)
        (agents / "bot.md").write_text("agent")

        async def go():
            app = HarnessSyncApp(repo)
            async with app.run_test(size=(130, 42)) as pilot:
                await pilot.pause()
                table = app.query_one("#status-table", DataTable)
                labels = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
                assert "agents:bot.md" in labels
                adopt = app.query_one("#adopt-skills", SelectionList)
                values = [adopt.get_option_at_index(i).value
                          for i in range(adopt.option_count)]
                assert "agents:bot.md" in values
                # adopt it to claude-perso via the handler
                for i in range(adopt.option_count):
                    opt = adopt.get_option_at_index(i)
                    if opt.value == "agents:bot.md":
                        adopt.select(opt)
                targets = app.query_one("#adopt-targets", SelectionList)
                for i in range(targets.option_count):
                    opt = targets.get_option_at_index(i)
                    if opt.value == "claude-perso":
                        targets.select(opt)
                app.adopt_selected()
                await pilot.pause()
                man = hs.load_manifest(repo / "manifest.json")
                assert man["agents"]["bot.md"]["targets"] == ["claude-perso"]

        asyncio.run(go())


if __name__ == "__main__":
    import traceback
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
