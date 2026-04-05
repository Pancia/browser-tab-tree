#!/usr/bin/env python3
"""Validation tests for the Browser Tab Tree Chrome extension.

Tests:
  1. manifest.json is valid and has required fields
  2. background.js is syntactically correct (no obvious issues)
  3. End-to-end: simulated extension events flow through host.py correctly
  4. install.sh generates a valid native messaging host manifest
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXT_DIR = SCRIPT_DIR
HOST_PY = SCRIPT_DIR.parent / "host" / "host.py"
INSTALL_SH = SCRIPT_DIR.parent / "install.sh"

passed = 0
failed = 0


def check(label: str, ok: bool) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def frame(event: dict) -> bytes:
    """Encode a native messaging frame (4-byte LE length + JSON)."""
    body = json.dumps(event).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def run_host(events: list[dict], output_dir: Path) -> subprocess.CompletedProcess:
    """Run host.py with framed events on stdin."""
    stdin_data = b"".join(frame(e) for e in events)
    env = os.environ.copy()
    env["BTT_OUTPUT_DIR"] = str(output_dir)
    return subprocess.run(
        [sys.executable, str(HOST_PY)],
        input=stdin_data,
        capture_output=True,
        env=env,
        timeout=10,
    )


# ===== Test: manifest.json =====
print("\n--- test_manifest_json ---")
manifest_path = EXT_DIR / "manifest.json"
manifest = json.loads(manifest_path.read_text())

check("manifest_version is 3", manifest.get("manifest_version") == 3)
check("has name", "name" in manifest)
check("has version", "version" in manifest)
check("has tabs permission", "tabs" in manifest.get("permissions", []))
check("has nativeMessaging permission", "nativeMessaging" in manifest.get("permissions", []))
check("has service_worker", "service_worker" in manifest.get("background", {}))
check("service_worker is background.js", manifest.get("background", {}).get("service_worker") == "background.js")


# ===== Test: background.js structure =====
print("\n--- test_background_js ---")
bg_js = (EXT_DIR / "background.js").read_text()

check("connects to com.browser_tab_tree", "com.browser_tab_tree" in bg_js)
check("has onCreated listener", "chrome.tabs.onCreated" in bg_js)
check("has onRemoved listener", "chrome.tabs.onRemoved" in bg_js)
check("sends TAB_OPEN", '"TAB_OPEN"' in bg_js)
check("sends TAB_CLOSE", '"TAB_CLOSE"' in bg_js)
check("sends openerTabId", "openerTabId" in bg_js)
check("has startup sync", "chrome.tabs.query" in bg_js)
check("has port disconnect handler", "onDisconnect" in bg_js)
check("has ensurePort function", "ensurePort" in bg_js)


# ===== Test: end-to-end tree structure via openerTabId (Phase 3) =====
print("\n--- test_e2e_opener_tab_tree ---")
with tempfile.TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    events = [
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 1, "windowId": 100,
         "url": "https://google.com", "title": "Google"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:01Z", "tabId": 2, "windowId": 100,
         "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:02Z", "tabId": 3, "windowId": 100,
         "url": "https://docs.python.org", "title": "Python Docs", "openerTabId": 1},
    ]
    result = run_host(events, output_dir)
    check("host exits 0", result.returncode == 0)

    md = (output_dir / "current.md").read_text()
    lines = md.splitlines()
    google_line = next((l for l in lines if "Google" in l), "")
    github_line = next((l for l in lines if "GitHub" in l), "")
    python_line = next((l for l in lines if "Python Docs" in l), "")
    check("Google is root (no indent)", google_line.startswith("- ["))
    check("GitHub is child (indented)", github_line.startswith("  - ["))
    check("Python Docs is child (indented)", python_line.startswith("  - ["))

    state = json.loads((output_dir / "state.json").read_text())
    tab2 = state.get("2", state.get(2, {}))
    check("tab 2 parentId is 1", tab2.get("parentId") == 1)


# ===== Test: orphan promotion on TAB_CLOSE (Phase 3) =====
print("\n--- test_e2e_orphan_promotion ---")
with tempfile.TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    events = [
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 1, "windowId": 100,
         "url": "https://google.com", "title": "Google"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:01Z", "tabId": 2, "windowId": 100,
         "url": "https://github.com", "title": "GitHub", "openerTabId": 1},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:02Z", "tabId": 3, "windowId": 100,
         "url": "https://docs.python.org", "title": "Python Docs", "openerTabId": 2},
        # Close middle node — tab 3 should promote to child of tab 1
        {"type": "TAB_CLOSE", "ts": "2026-04-04T12:00:03Z", "tabId": 2},
    ]
    result = run_host(events, output_dir)
    check("host exits 0", result.returncode == 0)

    md = (output_dir / "current.md").read_text()
    check("GitHub removed", "GitHub" not in md)
    lines = md.splitlines()
    google_line = next((l for l in lines if "Google" in l), "")
    python_line = next((l for l in lines if "Python Docs" in l), "")
    check("Google still root", google_line.startswith("- ["))
    check("Python Docs promoted to child of Google", python_line.startswith("  - ["))

    state = json.loads((output_dir / "state.json").read_text())
    tab3 = state.get("3", state.get(3, {}))
    check("tab 3 parentId is now 1 (grandparent)", tab3.get("parentId") == 1)


# ===== Test: end-to-end flat tab list (Phase 2 behavior) =====
print("\n--- test_e2e_flat_tab_list ---")
with tempfile.TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    events = [
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 1, "windowId": 100,
         "url": "https://google.com", "title": "Google"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:01Z", "tabId": 2, "windowId": 100,
         "url": "https://github.com", "title": "GitHub"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:02Z", "tabId": 3, "windowId": 100,
         "url": "https://example.com", "title": "Example"},
    ]
    result = run_host(events, output_dir)
    check("host exits 0", result.returncode == 0)

    md = (output_dir / "current.md").read_text()
    check("Google in output", "[Google](https://google.com)" in md)
    check("GitHub in output", "[GitHub](https://github.com)" in md)
    check("Example in output", "[Example](https://example.com)" in md)
    check("all tabs are roots (no indentation)", all(
        not line.startswith("  -") for line in md.splitlines() if line.startswith(" ")
    ))

    log_files = list((output_dir / "logs").glob("*.jsonl"))
    check("log file created", len(log_files) == 1)
    log_lines = log_files[0].read_text().strip().splitlines()
    check("3 log entries", len(log_lines) == 3)


# ===== Test: TAB_CLOSE removes tab =====
print("\n--- test_e2e_tab_close ---")
with tempfile.TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    events = [
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 1, "windowId": 100,
         "url": "https://google.com", "title": "Google"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:01Z", "tabId": 2, "windowId": 100,
         "url": "https://github.com", "title": "GitHub"},
        {"type": "TAB_CLOSE", "ts": "2026-04-04T12:00:02Z", "tabId": 1},
    ]
    result = run_host(events, output_dir)
    check("host exits 0", result.returncode == 0)

    md = (output_dir / "current.md").read_text()
    check("Google removed", "Google" not in md)
    check("GitHub still present", "[GitHub](https://github.com)" in md)


# ===== Test: startup sync (multiple tabs at once) =====
print("\n--- test_e2e_startup_sync ---")
with tempfile.TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    # Simulate what the extension does on startup: send TAB_OPEN for all existing tabs
    events = [
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 10, "windowId": 1,
         "url": "https://a.com", "title": "A"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 20, "windowId": 1,
         "url": "https://b.com", "title": "B"},
        {"type": "TAB_OPEN", "ts": "2026-04-04T12:00:00Z", "tabId": 30, "windowId": 2,
         "url": "https://c.com", "title": "C"},
    ]
    result = run_host(events, output_dir)
    check("host exits 0", result.returncode == 0)

    md = (output_dir / "current.md").read_text()
    check("window 1 header", "## Window 1" in md)
    check("window 2 header", "## Window 2" in md)
    check("tab A present", "[A](https://a.com)" in md)
    check("tab B present", "[B](https://b.com)" in md)
    check("tab C present", "[C](https://c.com)" in md)

    state = json.loads((output_dir / "state.json").read_text())
    check("state has 3 tabs", len(state) == 3)


# ===== Test: install.sh =====
print("\n--- test_install_sh ---")
check("install.sh exists", INSTALL_SH.exists())
check("install.sh is executable", os.access(INSTALL_SH, os.X_OK))
install_content = INSTALL_SH.read_text()
check("references host.py", "host.py" in install_content)
check("references NativeMessagingHosts", "NativeMessagingHosts" in install_content)
check("references com.browser_tab_tree", "com.browser_tab_tree" in install_content)
check("accepts extension ID argument", "${1:-" in install_content)


# ===== Summary =====
print(f"\n{'=' * 40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'=' * 40}")
sys.exit(1 if failed else 0)
