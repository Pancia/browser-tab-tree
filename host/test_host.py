#!/usr/bin/env python3
"""Test harness for host.py — exercises the native messaging host without Chrome.

Sends length-prefixed JSON events to host.py's stdin via subprocess, then
checks the resulting current.md and state.json.

Usage: python host/test_host.py
"""

import json
import os
import struct
import subprocess
import sys
import tempfile

HOST_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host.py")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def encode_message(obj: dict) -> bytes:
    """Encode a dict as a Chrome native-messaging frame: 4-byte LE length + JSON."""
    data = json.dumps(obj).encode("utf-8")
    return struct.pack("<I", len(data)) + data


def run_host(events: list[dict], output_dir: str) -> subprocess.CompletedProcess:
    """Start host.py, feed it length-prefixed events, close stdin, wait."""
    payload = b"".join(encode_message(e) for e in events)
    env = {**os.environ, "BTT_OUTPUT_DIR": output_dir}
    return subprocess.run(
        [sys.executable, HOST_PY],
        input=payload,
        capture_output=True,
        timeout=10,
        env=env,
    )


def read_output(output_dir: str, filename: str) -> str:
    path = os.path.join(output_dir, filename)
    with open(path) as f:
        return f.read()


def read_state(output_dir: str) -> dict:
    return json.loads(read_output(output_dir, "state.json"))


def read_md(output_dir: str) -> str:
    return read_output(output_dir, "current.md")


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def check(condition: bool, label: str, detail: str = ""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_basic_tab_open():
    """1. Basic TAB_OPEN (root tab) — verify it appears in current.md."""
    print("\n--- test_basic_tab_open ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0", f"rc={proc.returncode} stderr={proc.stderr!r}")

        md = read_md(tmp)
        check("## Window 100" in md, "window header present", md)
        check("[Google](https://google.com)" in md, "tab link present", md)

        state = read_state(tmp)
        check("1" in state or 1 in state, "tab 1 in state.json")


def test_child_tab():
    """2. TAB_OPEN with openerTabId — verify nesting in current.md."""
    print("\n--- test_child_tab ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 100,
             "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0")

        md = read_md(tmp)
        # The child should be indented under the parent.
        lines = md.splitlines()
        parent_idx = next((i for i, l in enumerate(lines) if "Google" in l), None)
        child_idx = next((i for i, l in enumerate(lines) if "GitHub" in l), None)
        check(parent_idx is not None and child_idx is not None, "both tabs in md")
        if parent_idx is not None and child_idx is not None:
            check(child_idx > parent_idx, "child after parent")
            parent_indent = len(lines[parent_idx]) - len(lines[parent_idx].lstrip())
            child_indent = len(lines[child_idx]) - len(lines[child_idx].lstrip())
            check(child_indent > parent_indent, "child indented deeper than parent",
                  f"parent_indent={parent_indent} child_indent={child_indent}")


def test_close_leaf():
    """3. TAB_CLOSE of a leaf — verify removal."""
    print("\n--- test_close_leaf ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 100,
             "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
            {"type": "TAB_CLOSE", "tabId": 2},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0")

        md = read_md(tmp)
        check("GitHub" not in md, "closed leaf removed from md", md)
        check("Google" in md, "parent still present", md)


def test_close_parent_promotes_children():
    """4. TAB_CLOSE of a parent — verify orphan promotion."""
    print("\n--- test_close_parent_promotes_children ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 100,
             "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
            {"type": "TAB_OPEN", "tabId": 3, "windowId": 100,
             "url": "https://docs.python.org", "title": "Python Docs", "openerTabId": 1},
            # Close the parent — children should become roots
            {"type": "TAB_CLOSE", "tabId": 1},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0")

        md = read_md(tmp)
        check("Google" not in md, "closed parent removed", md)
        check("GitHub" in md, "child 1 still present", md)
        check("Python Docs" in md, "child 2 still present", md)

        # Both children should be at root level (same indent as a normal root)
        lines = [l for l in md.splitlines() if l.strip().startswith("- [")]
        for line in lines:
            indent = len(line) - len(line.lstrip())
            check(indent == 0, f"promoted child at root indent: {line.strip()!r}",
                  f"indent={indent}")


def test_close_parent_promotes_to_grandparent():
    """4b. TAB_CLOSE of a middle node — children move to grandparent."""
    print("\n--- test_close_parent_promotes_to_grandparent ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 100,
             "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
            {"type": "TAB_OPEN", "tabId": 3, "windowId": 100,
             "url": "https://docs.python.org", "title": "Python Docs", "openerTabId": 2},
            # Close the middle node (tab 2) — tab 3 should become child of tab 1
            {"type": "TAB_CLOSE", "tabId": 2},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0")

        md = read_md(tmp)
        check("GitHub" not in md, "closed middle node removed", md)
        check("Google" in md, "grandparent still present", md)
        check("Python Docs" in md, "grandchild still present", md)

        lines = md.splitlines()
        gp_line = next((l for l in lines if "Google" in l), "")
        gc_line = next((l for l in lines if "Python Docs" in l), "")
        if gp_line and gc_line:
            gp_indent = len(gp_line) - len(gp_line.lstrip())
            gc_indent = len(gc_line) - len(gc_line.lstrip())
            check(gc_indent > gp_indent, "grandchild nested under grandparent",
                  f"gp_indent={gp_indent} gc_indent={gc_indent}")


def test_tab_navigate():
    """5. TAB_NAVIGATE — verify URL/title update without tree structure change."""
    print("\n--- test_tab_navigate ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 100,
             "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
            {"type": "TAB_NAVIGATE", "tabId": 1,
             "url": "https://google.com/search?q=python", "title": "Google Search: python"},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0")

        md = read_md(tmp)
        check("Google Search: python" in md, "updated title present", md)
        check("google.com/search?q=python" in md, "updated URL present", md)
        # Child should still be nested
        lines = md.splitlines()
        parent_idx = next((i for i, l in enumerate(lines) if "Google Search" in l), None)
        child_idx = next((i for i, l in enumerate(lines) if "GitHub" in l), None)
        if parent_idx is not None and child_idx is not None:
            p_indent = len(lines[parent_idx]) - len(lines[parent_idx].lstrip())
            c_indent = len(lines[child_idx]) - len(lines[child_idx].lstrip())
            check(c_indent > p_indent, "child still nested after navigate")


def test_multiple_windows():
    """6. Multiple windows — verify separate window sections in current.md."""
    print("\n--- test_multiple_windows ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 200,
             "url": "https://github.com", "title": "GitHub"},
            {"type": "TAB_OPEN", "tabId": 3, "windowId": 200,
             "url": "https://claude.ai", "title": "Claude"},
        ]
        proc = run_host(events, tmp)
        check(proc.returncode == 0, "host exits 0")

        md = read_md(tmp)
        check("## Window 100" in md, "window 100 header", md)
        check("## Window 200" in md, "window 200 header", md)

        # Google should be under window 100, GitHub and Claude under window 200
        w100_pos = md.index("Window 100")
        w200_pos = md.index("Window 200")
        google_pos = md.index("Google")
        github_pos = md.index("GitHub")

        # Google should appear in the window 100 section
        if w100_pos < w200_pos:
            check(w100_pos < google_pos < w200_pos, "Google under window 100")
            check(github_pos > w200_pos, "GitHub under window 200")
        else:
            check(w200_pos < github_pos < w100_pos, "GitHub under window 200")
            check(google_pos > w100_pos, "Google under window 100")


def test_restart_from_state():
    """7. Restart from state.json — verify current.md is identical after restart."""
    print("\n--- test_restart_from_state ---")
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"type": "TAB_OPEN", "tabId": 1, "windowId": 100,
             "url": "https://google.com", "title": "Google"},
            {"type": "TAB_OPEN", "tabId": 2, "windowId": 100,
             "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
            {"type": "TAB_OPEN", "tabId": 3, "windowId": 200,
             "url": "https://claude.ai", "title": "Claude"},
        ]
        # First run: establish state
        proc1 = run_host(events, tmp)
        check(proc1.returncode == 0, "first run exits 0")

        md1 = read_md(tmp)
        state1 = read_output(tmp, "state.json")

        # Second run: no new events, just restart — should load state.json
        proc2 = run_host([], tmp)
        check(proc2.returncode == 0, "restart exits 0")

        md2 = read_md(tmp)
        check(md1 == md2, "current.md identical after restart",
              f"BEFORE:\n{md1}\nAFTER:\n{md2}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _pass, _fail

    if not os.path.isfile(HOST_PY):
        print(f"ERROR: host.py not found at {HOST_PY}")
        sys.exit(2)

    tests = [
        test_basic_tab_open,
        test_child_tab,
        test_close_leaf,
        test_close_parent_promotes_children,
        test_close_parent_promotes_to_grandparent,
        test_tab_navigate,
        test_multiple_windows,
        test_restart_from_state,
    ]

    for t in tests:
        try:
            t()
        except Exception as exc:
            _fail += 1
            print(f"  ERROR {t.__name__}: {exc}")

    print(f"\n{'='*40}")
    print(f"  {_pass} passed, {_fail} failed")
    print(f"{'='*40}")
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    main()
