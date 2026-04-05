#!/usr/bin/env python3
"""Native messaging host for Browser Tab Tree.

Reads Chrome native-messaging framed events from stdin (4-byte LE length
prefix + JSON payload), maintains an in-memory tab tree, and writes:
  - logs/YYYY-MM-DD.jsonl  (raw events, append)
  - state.json             (full tab dict, atomic)
  - current.md             (rendered markdown tree, atomic)
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("BTT_OUTPUT_DIR", _SCRIPT_DIR / "output"))

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

Tab = dict[str, Any]
# Keys: tabId (int), windowId (int), parentId (int|None),
#        url (str), title (str), index (int), children (list[int])

tabs: dict[int, Tab] = {}

# ---------------------------------------------------------------------------
# Message I/O (native messaging protocol)
# ---------------------------------------------------------------------------


def read_message() -> dict | None:
    """Read one native-messaging frame from stdin.

    Returns the decoded JSON dict, or None on EOF.
    """
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) == 0:
        return None  # EOF
    if len(raw_len) < 4:
        return None  # truncated header — treat as EOF
    (msg_len,) = struct.unpack("<I", raw_len)
    raw_body = sys.stdin.buffer.read(msg_len)
    if len(raw_body) < msg_len:
        return None  # truncated body
    return json.loads(raw_body)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def handle_tab_open(event: dict) -> None:
    tab_id: int = event["tabId"]
    window_id: int = event["windowId"]
    opener_id: int | None = event.get("openerTabId")
    url: str = event.get("url", "")
    title: str = event.get("title", "")
    index: int = event.get("index", 0)

    parent_id: int | None = None
    if opener_id is not None and opener_id in tabs:
        parent_id = opener_id
        tabs[opener_id]["children"].append(tab_id)

    tabs[tab_id] = {
        "tabId": tab_id,
        "windowId": window_id,
        "parentId": parent_id,
        "url": url,
        "title": title,
        "index": index,
        "children": [],
    }


def handle_tab_close(event: dict) -> None:
    tab_id: int = event["tabId"]
    tab = tabs.get(tab_id)
    if tab is None:
        return

    parent_id = tab["parentId"]

    # Re-parent children
    for child_id in tab["children"]:
        child = tabs.get(child_id)
        if child is None:
            continue
        child["parentId"] = parent_id
        if parent_id is not None and parent_id in tabs:
            tabs[parent_id]["children"].append(child_id)

    # Remove from parent's children list
    if parent_id is not None and parent_id in tabs:
        children = tabs[parent_id]["children"]
        try:
            children.remove(tab_id)
        except ValueError:
            pass

    del tabs[tab_id]


def handle_tab_navigate(event: dict) -> None:
    tab_id: int = event["tabId"]
    tab = tabs.get(tab_id)
    if tab is None:
        return
    tab["url"] = event.get("url", tab["url"])
    tab["title"] = event.get("title", tab["title"])


def handle_tab_move(event: dict) -> None:
    tab_id: int = event["tabId"]
    tab = tabs.get(tab_id)
    if tab is None:
        return
    tab["index"] = event.get("index", tab["index"])
    if "windowId" in event:
        tab["windowId"] = event["windowId"]


HANDLERS: dict[str, Any] = {
    "TAB_OPEN": handle_tab_open,
    "TAB_CLOSE": handle_tab_close,
    "TAB_NAVIGATE": handle_tab_navigate,
    "TAB_MOVE": handle_tab_move,
}

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        os.rename(tmp, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_log(event: dict) -> None:
    log_dir = OUTPUT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


def write_state() -> None:
    _atomic_write(
        OUTPUT_DIR / "state.json",
        json.dumps(tabs, indent=2, sort_keys=True) + "\n",
    )


def render_markdown() -> str:
    """Render tabs as a markdown tree grouped by window."""
    # Group tabs by windowId
    windows: dict[int, list[Tab]] = {}
    for tab in tabs.values():
        windows.setdefault(tab["windowId"], [])

    # Identify root tabs (parentId is None) per window
    roots: dict[int, list[int]] = {}
    for tab in tabs.values():
        if tab["parentId"] is None:
            roots.setdefault(tab["windowId"], []).append(tab["tabId"])

    lines: list[str] = ["# Open Tabs"]

    def _render_tab(tab_id: int, depth: int) -> None:
        tab = tabs.get(tab_id)
        if tab is None:
            return
        indent = "  " * depth
        title = tab["title"] or tab["url"] or "(untitled)"
        url = tab["url"]
        lines.append(f"{indent}- [{title}]({url})")
        for child_id in sorted(tab["children"], key=lambda c: tabs[c]["index"] if c in tabs else 0):
            _render_tab(child_id, depth + 1)

    for wid in sorted(windows):
        root_ids = roots.get(wid, [])
        if not root_ids:
            continue
        root_ids.sort(key=lambda tid: tabs[tid]["index"] if tid in tabs else 0)
        lines.append(f"\n## Window {wid}")
        for tid in root_ids:
            _render_tab(tid, 0)

    return "\n".join(lines) + "\n"


def write_current_md() -> None:
    _atomic_write(OUTPUT_DIR / "current.md", render_markdown())


def flush_outputs(event: dict | None = None) -> None:
    if event is not None:
        append_log(event)
    write_state()
    write_current_md()


# ---------------------------------------------------------------------------
# Startup — restore state
# ---------------------------------------------------------------------------


def load_state() -> None:
    global tabs
    state_path = OUTPUT_DIR / "state.json"
    if not state_path.exists():
        return
    # Only load if written today (by mtime)
    mtime = datetime.fromtimestamp(state_path.stat().st_mtime)
    if mtime.date() != date.today():
        return
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Keys in JSON are strings; convert to int
        tabs = {int(k): v for k, v in raw.items()}
    except (json.JSONDecodeError, OSError, ValueError):
        tabs = {}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    load_state()

    while True:
        msg = read_message()
        if msg is None:
            # EOF — flush final state and exit cleanly
            flush_outputs()
            sys.exit(0)

        event_type = msg.get("type")
        handler = HANDLERS.get(event_type)  # type: ignore[arg-type]
        if handler is not None:
            handler(msg)

        flush_outputs(event=msg)


if __name__ == "__main__":
    main()
