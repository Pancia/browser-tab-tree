#!/usr/bin/env python3
"""Parse a browser-tab-tree current.md and send a restore_session command.

Usage:
    git show <commit>:browser-sync/current.md | python3 restore_session.py
    python3 restore_session.py /path/to/current.md
    python3 restore_session.py --dry-run < current.md
"""

import json
import os
import re
import sys

EMOJI_TO_COLOR = {
    "⚪": "grey", "🔵": "blue", "🔴": "red", "🟡": "yellow",
    "🟢": "green", "🩷": "pink", "🟣": "purple", "🩵": "cyan", "🟠": "orange",
}

LINK_RE = re.compile(r"^- \[(?:⏻︎ )?(.+?)\]\((.+?)\)$")
WINDOW_RE = re.compile(r"^## Window \d+")
GROUP_RE = re.compile(r"^### (.) (.+)$")

DEFAULT_FIFO = os.path.expanduser("~/TheAkashicRecords/browser-sync/cmd.fifo")


def parse_current_md(text):
    windows = []
    current_window = None
    current_group = None

    for line in text.splitlines():
        line = line.strip()

        if WINDOW_RE.match(line):
            current_window = {"tabs": [], "groups": []}
            windows.append(current_window)
            current_group = None
            continue

        if current_window is None:
            continue

        group_match = GROUP_RE.match(line)
        if group_match:
            emoji, title = group_match.group(1), group_match.group(2)
            color = EMOJI_TO_COLOR.get(emoji, "grey")
            current_group = {
                "title": title,
                "color": color,
                "tabIndices": [],
            }
            current_window["groups"].append(current_group)
            continue

        link_match = LINK_RE.match(line)
        if link_match:
            title, url = link_match.group(1), link_match.group(2)
            idx = len(current_window["tabs"])
            current_window["tabs"].append({"url": url, "title": title})
            if current_group is not None:
                current_group["tabIndices"].append(idx)

    return windows


def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if args:
        with open(args[0]) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    windows = parse_current_md(text)

    total_tabs = sum(len(w["tabs"]) for w in windows)
    total_groups = sum(len(w["groups"]) for w in windows)
    print(f"Parsed {len(windows)} windows, {total_tabs} tabs, {total_groups} groups",
          file=sys.stderr)

    cmd = {"command": "restore_session", "windows": windows}

    if dry_run:
        print(json.dumps(cmd, indent=2))
        return

    fifo_path = os.environ.get("BTT_FIFO", DEFAULT_FIFO)
    if not os.path.exists(fifo_path):
        print(f"Error: FIFO not found at {fifo_path}", file=sys.stderr)
        print("Is the host running? Set BTT_FIFO to override.", file=sys.stderr)
        sys.exit(1)

    with open(fifo_path, "w") as fifo:
        fifo.write(json.dumps(cmd, separators=(",", ":")) + "\n")

    print("Restore command sent to FIFO", file=sys.stderr)


if __name__ == "__main__":
    main()
