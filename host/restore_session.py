#!/usr/bin/env python3
"""Parse a browser-tab-tree current.md and send a restore_session command.

Usage:
    git show <commit>:browser-sync/current.md | python3 restore_session.py
    python3 restore_session.py /path/to/current.md
    python3 restore_session.py --dry-run < current.md
    python3 restore_session.py --no-follow < current.md   # fire and forget
"""

import json
import os
import re
import sys
import time

EMOJI_TO_COLOR = {
    "⚪": "grey", "🔵": "blue", "🔴": "red", "🟡": "yellow",
    "🟢": "green", "🩷": "pink", "🟣": "purple", "🩵": "cyan", "🟠": "orange",
}

LINK_RE = re.compile(r"^- \[(?:⏻︎ )?(.+?)\]\((.+?)\)$")
WINDOW_RE = re.compile(r"^## Window \d+")
GROUP_RE = re.compile(r"^### (.) (.+)$")

DEFAULT_OUTPUT_DIR = os.path.expanduser("~/TheAkashicRecords/browser-sync")


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


def tail_progress(progress_path, timeout=120):
    """Tail progress.jsonl and print human-readable status until complete."""
    deadline = time.time() + timeout
    seen = 0

    # Wait for file to appear
    while not os.path.exists(progress_path):
        if time.time() > deadline:
            print("Timed out waiting for progress file", file=sys.stderr)
            return
        time.sleep(0.1)

    while time.time() < deadline:
        try:
            with open(progress_path) as f:
                lines = f.readlines()
        except OSError:
            time.sleep(0.1)
            continue

        for line in lines[seen:]:
            seen += 1
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            status = evt.get("status")
            if status == "started":
                print(f"Restoring {evt.get('totalWindows')} windows, {evt.get('totalTabs')} tabs...")
            elif status == "window_created":
                print(f"  [{evt.get('window')}/{evt.get('totalWindows')}] Window created ({evt.get('tabCount')} tabs)")
            elif status == "batch_discarded":
                group = evt.get("group", "?")
                count = evt.get("tabCount", 0)
                print(f"    ✓ {group} ({count} tabs) — discarded")
            elif status == "complete":
                print(f"Done! {evt.get('totalTabs')} tabs restored across {evt.get('totalWindows')} windows.")
                return

        time.sleep(0.2)

    print("Timed out waiting for completion", file=sys.stderr)


def main():
    flags = {"--dry-run", "--no-follow"}
    dry_run = "--dry-run" in sys.argv
    no_follow = "--no-follow" in sys.argv
    args = [a for a in sys.argv[1:] if a not in flags]

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

    output_dir = os.environ.get("BTT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    fifo_path = os.environ.get("BTT_FIFO", os.path.join(output_dir, "cmd.fifo"))
    if not os.path.exists(fifo_path):
        print(f"Error: FIFO not found at {fifo_path}", file=sys.stderr)
        print("Is the host running? Set BTT_FIFO to override.", file=sys.stderr)
        sys.exit(1)

    with open(fifo_path, "w") as fifo:
        fifo.write(json.dumps(cmd, separators=(",", ":")) + "\n")

    print("Restore command sent", file=sys.stderr)

    if not no_follow:
        progress_path = os.path.join(output_dir, "progress.jsonl")
        tail_progress(progress_path)


if __name__ == "__main__":
    main()
