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
                yield Label("Adopt view (Task 3)", classes="panel-title")
            with TabPane("Plugins", id="tab-plugins"):
                yield Label("Plugins view (Task 3)", classes="panel-title")
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
        pass  # Task 3

    def _refresh_plugins(self) -> None:
        pass  # Task 3

    def _refresh_apply(self) -> None:
        pass  # Task 4

    def _refresh_harness(self) -> None:
        pass  # Task 4

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)


def run(repo_root: Path) -> None:
    HarnessSyncApp(repo_root).run()
