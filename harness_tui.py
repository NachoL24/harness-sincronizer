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
    Button, Checkbox, DataTable, Footer, Header, Input, Label, Log, Select,
    SelectionList, Static, TabbedContent, TabPane,
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
        Binding("u", "untrack_cursor", "Untrack"),
        Binding("q", "quit", "Quit"),
        Binding("1", "tab('tab-status')", "Status", show=False),
        Binding("2", "tab('tab-adopt')", "Adopt", show=False),
        Binding("3", "tab('tab-plugins')", "Plugins", show=False),
        Binding("4", "tab('tab-apply')", "Apply", show=False),
        Binding("5", "tab('tab-harness')", "Harness", show=False),
    ]
    # Height discipline is the load-bearing part of this stylesheet: every
    # scrollable gets 1fr, never auto, so no pane can outgrow the screen and
    # scroll the tab bar out of view.
    CSS = """
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }
    DataTable { height: 1fr; }
    #status-summary { height: 1; margin-bottom: 1; }
    .picker { height: 1fr; }
    .picker SelectionList { height: 1fr; border: round $primary; }
    .side { width: 44; padding-left: 2; }
    .side SelectionList { height: 1fr; }
    .side Button { width: 100%; margin-top: 1; }
    .panel-title { text-style: bold; color: $text-muted; }
    #apply-pending { height: 1fr; border: round $primary; }
    #apply-btn { width: 24; margin-top: 1; }
    #prune-check { margin-top: 1; }
    #harness-row { height: auto; margin-top: 1; }
    #harness-name, #harness-base { width: 1fr; }
    #log { height: 6; border: round $primary; margin: 0 1; }
    """

    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self.repo_root = repo_root
        self.paths = hs.resolve_paths(repo_root)

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Status", id="tab-status"):
                yield Static(id="status-summary")
                yield DataTable(id="status-table", cursor_type="row")
            with TabPane("Adopt", id="tab-adopt"):
                with Horizontal(classes="picker"):
                    with Vertical():
                        yield Label("Skills (untracked/drift)", classes="panel-title")
                        yield SelectionList(id="adopt-skills")
                    with Vertical(classes="side"):
                        yield Label("Targets", classes="panel-title")
                        yield SelectionList(id="adopt-targets")
                        yield Label("Source (when ambiguous)", classes="panel-title")
                        yield Select([("auto (first available)", "auto")],
                                     value="auto", id="adopt-source")
                        yield Button("Adopt selected", id="adopt-btn", variant="primary")
            with TabPane("Plugins", id="tab-plugins"):
                with Horizontal(classes="picker"):
                    with Vertical():
                        yield Label("Plugins", classes="panel-title")
                        yield SelectionList(id="plugins-list")
                    with Vertical(classes="side"):
                        yield Label("Targets", classes="panel-title")
                        yield SelectionList(id="plugins-targets")
                        yield Button("Adopt selected plugins", id="plugins-btn", variant="primary")
            with TabPane("Apply", id="tab-apply"):
                yield Log(id="apply-pending")
                yield Checkbox("also prune de-targeted skills", id="prune-check")
                yield Button("Apply now", id="apply-btn", variant="warning")
            with TabPane("Harness", id="tab-harness"):
                yield DataTable(id="harness-table", cursor_type="row")
                with Horizontal(id="harness-row"):
                    yield Input(placeholder="name", id="harness-name")
                    yield Input(placeholder="base dir (e.g. ~/.claude-perso)", id="harness-base")
                    yield Button("Add", id="harness-add-btn", variant="primary")
                    yield Button("Remove selected", id="harness-remove-btn", variant="error")
        yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "nord"
        self.query_one("#log", Log).border_title = "Activity"
        self.query_one("#apply-pending", Log).border_title = "Pending changes (dry-run)"
        self.action_refresh()

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

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
        rows = hs.compute_states(self.paths)
        counts = {"synced": 0, "drift": 0, "untracked": 0}
        for row in rows:
            states = {row[h] for h in names}
            if "drift" in states:
                counts["drift"] += 1
            elif "untracked" in states:
                counts["untracked"] += 1
            elif "synced" in states:
                counts["synced"] += 1
            cells = [row["name"], "yes" if row["repo"] else "no"]
            for h in names:
                state = row[h]
                cells.append(Text(state, style=STATE_STYLE.get(state, "")))
            table.add_row(*cells)
        summary = Text(f"{len(rows)} skills · ")
        summary.append(f"{counts['synced']} synced", style=STATE_STYLE["synced"])
        summary.append(" · ")
        summary.append(f"{counts['drift']} drift", style=STATE_STYLE["drift"])
        summary.append(" · ")
        summary.append(f"{counts['untracked']} untracked", style=STATE_STYLE["untracked"])
        self.query_one("#status-summary", Static).update(summary)

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
        pending = self.query_one("#apply-pending", Log)
        pending.clear()
        changes = hs.apply_all(self.paths, dry_run=True)
        if self.query_one("#prune-check", Checkbox).value:
            changes += hs.prune_all(self.paths, dry_run=True)
        if not changes:
            pending.write_line("nothing to do")
        for c in changes:
            pending.write_line(c)

    def _refresh_harness(self) -> None:
        table = self.query_one("#harness-table", DataTable)
        table.clear(columns=True)
        table.add_columns("NAME", "BASE", "SKILLS PATH")
        for name, skills in self.paths.harness_skills.items():
            table.add_row(name, str(skills.parent), str(skills))

    @on(Button.Pressed, "#apply-btn")
    def do_apply(self) -> None:
        changes = hs.apply_all(self.paths)
        if self.query_one("#prune-check", Checkbox).value:
            changes += hs.prune_all(self.paths)
        if not changes:
            self._log("apply: nothing to do")
        for c in changes:
            self._log(f"applied {c}")
        self.action_refresh()

    @on(Checkbox.Changed, "#prune-check")
    def prune_toggled(self) -> None:
        self._refresh_apply()

    def action_untrack_cursor(self) -> None:
        if self.query_one(TabbedContent).active != "tab-status":
            self._log("untrack: switch to the Status tab first")
            return
        table = self.query_one("#status-table", DataTable)
        if table.row_count == 0:
            return
        name = str(table.get_row_at(table.cursor_row)[0])
        try:
            hs.untrack_skill(self.paths, name)
        except KeyError:
            self._log(f"untrack: '{name}' is not tracked")
            return
        self._log(f"untracked {name} (repo copy backed up; harnesses untouched)")
        self.action_refresh()

    @on(Button.Pressed, "#harness-add-btn")
    def add_harness(self) -> None:
        name = self.query_one("#harness-name", Input).value.strip()
        base = self.query_one("#harness-base", Input).value.strip()
        if not name or not base:
            self._log("harness add: name and base are required")
            return
        hs.harness_add(self.paths, name, base)
        self._log(f"added harness '{name}' -> {base}")
        self.action_refresh()

    @on(Button.Pressed, "#harness-remove-btn")
    def remove_harness(self) -> None:
        table = self.query_one("#harness-table", DataTable)
        if table.row_count == 0:
            self._log("harness remove: no harnesses")
            return
        name = table.get_row_at(table.cursor_row)[0]
        hs.harness_remove(self.paths, name)
        self._log(f"removed harness '{name}'")
        self.action_refresh()

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


def run(repo_root: Path) -> None:
    HarnessSyncApp(repo_root).run()
