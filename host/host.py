#!/usr/bin/env python3
"""Native messaging host for Browser Tab Tree.

Reads Chrome native-messaging framed events from stdin (4-byte LE length
prefix + JSON payload), maintains an in-memory tab tree, and writes:
  - logs/YYYY-MM-DD.jsonl  (raw events, append)
  - state.json             (full tab dict, atomic)
  - current.md             (rendered markdown tree, atomic)
"""

from __future__ import annotations

import gzip
import json
import os
import struct
import sys
import tempfile
import threading
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
groups: dict[int, dict] = {}

GROUP_COLOR_EMOJI: dict[str, str] = {
    "grey": "⚪", "blue": "🔵", "red": "🔴", "yellow": "🟡",
    "green": "🟢", "pink": "🩷", "purple": "🟣", "cyan": "🩵", "orange": "🟠",
}

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


def send_message(msg: dict) -> None:
    """Send a native-messaging frame to the extension via stdout."""
    raw = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(raw)))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Command FIFO — accepts commands from CLI, forwards to extension
# ---------------------------------------------------------------------------

FIFO_PATH = OUTPUT_DIR / "cmd.fifo"


def _ensure_fifo() -> None:
    """Create the FIFO if it doesn't exist."""
    if FIFO_PATH.exists():
        if not FIFO_PATH.is_fifo():
            FIFO_PATH.unlink()
        else:
            return
    os.mkfifo(FIFO_PATH)


def _fifo_reader() -> None:
    """Background thread: read JSON commands from FIFO and send to extension."""
    _ensure_fifo()
    while True:
        try:
            with open(FIFO_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cmd = json.loads(line)
                        send_message(cmd)
                    except (json.JSONDecodeError, OSError) as e:
                        sys.stderr.write(f"[host] bad command: {e}\n")
        except OSError:
            pass  # FIFO was deleted or broken, retry


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
        "groupId": event.get("groupId", -1),
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


def handle_group_update(event: dict) -> None:
    group_id: int = event["groupId"]
    groups[group_id] = {
        "groupId": group_id,
        "windowId": event.get("windowId", 0),
        "title": event.get("title", ""),
        "color": event.get("color", "grey"),
        "collapsed": event.get("collapsed", False),
    }


def handle_group_remove(event: dict) -> None:
    group_id: int = event["groupId"]
    groups.pop(group_id, None)
    # Reset any tabs still referencing this group
    for tab in tabs.values():
        if tab.get("groupId") == group_id:
            tab["groupId"] = -1


def handle_tab_group_changed(event: dict) -> None:
    tab_id: int = event["tabId"]
    tab = tabs.get(tab_id)
    if tab is None:
        return
    tab["groupId"] = event.get("groupId", -1)


def handle_sync_start(_event: dict) -> None:
    """Extension is about to send a full sync — clear stale state."""
    tabs.clear()
    groups.clear()


HANDLERS: dict[str, Any] = {
    "SYNC_START": handle_sync_start,
    "TAB_OPEN": handle_tab_open,
    "TAB_CLOSE": handle_tab_close,
    "TAB_NAVIGATE": handle_tab_navigate,
    "TAB_MOVE": handle_tab_move,
    "GROUP_UPDATE": handle_group_update,
    "GROUP_REMOVE": handle_group_remove,
    "TAB_GROUP_CHANGED": handle_tab_group_changed,
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


def compress_old_logs() -> None:
    """Gzip any JSONL logs from previous days."""
    log_dir = OUTPUT_DIR / "logs"
    if not log_dir.exists():
        return
    today = date.today().isoformat()
    for log_file in log_dir.glob("*.jsonl"):
        if log_file.stem == today:
            continue
        gz_path = log_file.with_suffix(".jsonl.gz")
        try:
            with open(log_file, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                f_out.writelines(f_in)
            log_file.unlink()
        except OSError:
            pass


def append_log(event: dict) -> None:
    log_dir = OUTPUT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


def write_state() -> None:
    _atomic_write(
        OUTPUT_DIR / "state.json",
        json.dumps({"tabs": tabs, "groups": groups}, indent=2, sort_keys=True) + "\n",
    )


def render_markdown() -> str:
    """Render tabs as a markdown tree grouped by window."""
    # Group tabs by windowId
    windows: dict[int, list[Tab]] = {}
    for tab in tabs.values():
        windows.setdefault(tab["windowId"], [])

    lines: list[str] = ["# Open Tabs"]

    def _render_tab(tab_id: int, depth: int, render_gid: int) -> None:
        tab = tabs.get(tab_id)
        if tab is None:
            return
        indent = "  " * depth
        title = tab["title"] or tab["url"] or "(untitled)"
        url = tab["url"]
        lines.append(f"{indent}- [{title}]({url})")
        for child_id in sorted(tab["children"], key=lambda c: tabs[c].get("index", 0) if c in tabs else 0):
            child = tabs.get(child_id)
            if child is not None and child.get("groupId", -1) != render_gid:
                continue
            _render_tab(child_id, depth + 1, render_gid)

    for wid in sorted(windows):
        # Partition tabs into group roots: tabs that are roots within their group
        # A tab is a group root if parentId is None or parent has different groupId
        group_roots: dict[int, list[int]] = {}  # groupId -> [tabId, ...]
        for tab in tabs.values():
            if tab["windowId"] != wid:
                continue
            gid = tab.get("groupId", -1)
            parent = tabs.get(tab["parentId"]) if tab["parentId"] is not None else None
            if parent is None or parent.get("groupId", -1) != gid:
                group_roots.setdefault(gid, []).append(tab["tabId"])

        # Ungrouped roots first
        ungrouped = group_roots.pop(-1, [])
        if not ungrouped and not group_roots:
            continue

        lines.append(f"\n## Window {wid}")

        ungrouped.sort(key=lambda tid: tabs[tid].get("index", 0) if tid in tabs else 0)
        for tid in ungrouped:
            _render_tab(tid, 0, -1)

        # Groups ordered by minimum tab index within the group
        def _group_sort_key(gid: int) -> int:
            all_group_tabs = [t for t in tabs.values() if t.get("groupId") == gid and t["windowId"] == wid]
            if all_group_tabs:
                return min(t.get("index", 0) for t in all_group_tabs)
            return 0

        for gid in sorted(group_roots, key=_group_sort_key):
            group = groups.get(gid, {})
            color = group.get("color", "grey")
            emoji = GROUP_COLOR_EMOJI.get(color, "⚪")
            title = group.get("title", "") or "(unnamed)"
            lines.append(f"\n### {emoji} {title}")
            root_ids = group_roots[gid]
            root_ids.sort(key=lambda tid: tabs[tid].get("index", 0) if tid in tabs else 0)
            for tid in root_ids:
                _render_tab(tid, 0, gid)

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
    global tabs, groups
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
        # New format: {"tabs": {...}, "groups": {...}}
        if "tabs" in raw and isinstance(raw.get("tabs"), dict):
            tabs = {int(k): v for k, v in raw["tabs"].items()}
            groups = {int(k): v for k, v in raw.get("groups", {}).items()}
        else:
            # Legacy flat-tabs format
            tabs = {int(k): v for k, v in raw.items()}
            groups = {}
    except (json.JSONDecodeError, OSError, ValueError):
        tabs = {}
        groups = {}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    compress_old_logs()
    load_state()

    # Start command FIFO listener in background
    t = threading.Thread(target=_fifo_reader, daemon=True)
    t.start()

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
