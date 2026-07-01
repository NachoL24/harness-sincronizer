#!/usr/bin/env python3
"""harness-tui: full-screen dashboard over harness_sync (textual)."""
from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Log, Select,
    SelectionList, TabbedContent, TabPane,
)
from textual.widgets.selection_list import Selection

import harness_sync as hs

STATE_STYLE = {
    "synced": "green",
    "drift": "yellow",
    "untracked": "cyan",
    "absent": "dim",
}


class HarnessSyncApp(App):
    TITLE = "harness-sync"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]
    CSS = """
    SelectionList { border: solid $accent; }
    #log { height: 8; border: solid $accent; }
    #apply-pending { border: solid $accent; }
    Button { margin: 1 1; }
    .panel-title { padding: 0 1; text-style: bold; }
    """

    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self.repo_root = repo_root
        self.paths = hs.resolve_paths(repo_root)

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Status", id="tab-status"):
                yield DataTable(id="status-table", cursor_type="row")
            with TabPane("Adopt", id="tab-adopt"):
                with Horizontal():
                    with Vertical():
                        yield Label("Skills (untracked/drift)", classes="panel-title")
                        yield SelectionList(id="adopt-skills")
                    with Vertical():
                        yield Label("Targets", classes="panel-title")
                        yield SelectionList(id="adopt-targets")
                        yield Label("Source (when ambiguous)", classes="panel-title")
                        yield Select([("auto (first available)", "auto")],
                                     value="auto", id="adopt-source")
                        yield Button("Adopt selected", id="adopt-btn", variant="primary")
            with TabPane("Plugins", id="tab-plugins"):
                with Horizontal():
                    with Vertical():
                        yield Label("Plugins", classes="panel-title")
                        yield SelectionList(id="plugins-list")
                    with Vertical():
                        yield Label("Targets", classes="panel-title")
                        yield SelectionList(id="plugins-targets")
                        yield Button("Adopt selected plugins", id="plugins-btn", variant="primary")
            with TabPane("Apply", id="tab-apply"):
                yield Label("Apply view (Task 4)", classes="panel-title")
            with TabPane("Harness", id="tab-harness"):
                yield Label("Harness view (Task 4)", classes="panel-title")
        yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        self.paths = hs.resolve_paths(self.repo_root)
        self._refresh_status()
        self._refresh_adopt()
        self._refresh_plugins()
        self._refresh_apply()
        self._refresh_harness()

    def _refresh_status(self) -> None:
        table = self.query_one("#status-table", DataTable)
        table.clear(columns=True)
        names = list(self.paths.harness_skills)
        table.add_columns("SKILL", "REPO", *[n.upper() for n in names])
        for row in hs.compute_states(self.paths):
            cells = [row["name"], "yes" if row["repo"] else "no"]
            for h in names:
                state = row[h]
                cells.append(Text(state, style=STATE_STYLE.get(state, "")))
            table.add_row(*cells)

    def _refresh_adopt(self) -> None:
        names = list(self.paths.harness_skills)
        skills = self.query_one("#adopt-skills", SelectionList)
        skills.clear_options()
        self._adoptable: dict[str, list[str]] = {}
        for row in hs.compute_states(self.paths):
            available = [h for h in names if row[h] in ("untracked", "drift")]
            if not available:
                continue
            self._adoptable[row["name"]] = available
            detail = ", ".join(f"{h}:{row[h]}" for h in available)
            skills.add_option(Selection(f"{row['name']}  ({detail})", row["name"]))
        self._fill_targets("#adopt-targets", names)
        source = self.query_one("#adopt-source", Select)
        source.set_options([("auto (first available)", "auto")] + [(h, h) for h in names])
        source.value = "auto"

    def _refresh_plugins(self) -> None:
        plist = self.query_one("#plugins-list", SelectionList)
        plist.clear_options()
        self._plugins = hs.discover_plugins(self.paths)
        repo = set(hs.scan(self.paths.repo_skills))
        for i, p in enumerate(self._plugins):
            skill_names = [n for n, _ in p["skills"]]
            in_repo = sum(1 for n in skill_names if n in repo)
            label = f"{p['plugin']}  ({p['harness']}, {len(skill_names)} skills, {in_repo} in repo)"
            plist.add_option(Selection(label, i))
        self._fill_targets("#plugins-targets", list(self.paths.harness_skills))

    def _fill_targets(self, selector: str, names: list[str]) -> None:
        targets = self.query_one(selector, SelectionList)
        targets.clear_options()
        for h in names:
            targets.add_option(Selection(h, h))
        targets.add_option(Selection("ignore", "ignore"))

    @staticmethod
    def _batch_targets(selected: list[str]) -> list[str]:
        return ["ignore"] if "ignore" in selected else list(selected)

    @on(Button.Pressed, "#adopt-btn")
    def adopt_selected(self) -> None:
        chosen = self.query_one("#adopt-skills", SelectionList).selected
        raw_targets = self.query_one("#adopt-targets", SelectionList).selected
        if not chosen or not raw_targets:
            self._log("adopt: select at least one skill and one target")
            return
        targets = self._batch_targets(raw_targets)
        source_pref = self.query_one("#adopt-source", Select).value
        for name in chosen:
            available = self._adoptable[name]
            source = source_pref if source_pref in available else available[0]
            hs.adopt_skill(self.paths, name, source, targets)
            self._log(f"adopted {name} from {source} -> {targets}")
        self.action_refresh()

    @on(Button.Pressed, "#plugins-btn")
    def adopt_selected_plugins(self) -> None:
        chosen = self.query_one("#plugins-list", SelectionList).selected
        raw_targets = self.query_one("#plugins-targets", SelectionList).selected
        if not chosen or not raw_targets:
            self._log("plugins: select at least one plugin and one target")
            return
        targets = self._batch_targets(raw_targets)
        for i in chosen:
            plugin = self._plugins[i]
            adopted, skipped = hs.adopt_plugin(self.paths, plugin, targets)
            msg = f"{plugin['plugin']}: adopted {len(adopted)} -> {targets}"
            if skipped:
                msg += f"; skipped (already in repo): {skipped}"
            self._log(msg)
        self.action_refresh()

    def _refresh_apply(self) -> None:
        pass  # Task 4

    def _refresh_harness(self) -> None:
        pass  # Task 4

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


def run(repo_root: Path) -> None:
    HarnessSyncApp(repo_root).run()
