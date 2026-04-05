# Browser Tab Tree

Chromium extension + Python native messaging host that tracks tab parentage and writes a live markdown tree to disk.

## Architecture

```
Chrome Extension (MV3 service worker)
    → Native Messaging (stdin/stdout, 4-byte LE length-prefixed JSON)
        → host/host.py (Python 3.10+, zero deps)
            → logs/YYYY-MM-DD.jsonl   (append-only event log)
            → state.json              (atomic snapshot for fast restart)
            → current.md              (live markdown tree, atomic write)
```

## Project Structure

- `extension/` — Chrome extension (manifest.json + background.js)
- `host/host.py` — Native messaging host, single file, stdlib only
- `host/run_host.sh` — Wrapper script Chrome actually launches (handles pyenv, config loading)
- `host/test_host.py` — Test harness (sends fake events to host.py)
- `install.sh` — Registers native messaging host manifest on macOS

## Key Design Decisions

- 6 event types: TAB_OPEN, TAB_CLOSE, TAB_NAVIGATE, GROUP_UPDATE, GROUP_REMOVE, TAB_GROUP_CHANGED
- `tabGroups` permission enables Chrome tab group tracking (titles, colors, membership)
- JSONL log format (not markdown) for the source of truth
- Atomic file writes (temp + os.rename) for current.md and state.json
- Ctrl+T new tabs are roots (openerTabId stripped for chrome://newtab)
- Closed tabs removed from tree immediately (recoverable from log)
- Orphaned children promoted to grandparent (or root)
- Config via `~/.config/browser-tab-tree/config.json`, default output to `~/.local/share/browser-tab-tree`

## Running Tests

```
cd host && python3 test_host.py
```

## Development

After changes to background.js, reload the extension at chrome://extensions.
After changes to host.py or run_host.sh, reload the extension (spawns a fresh host process).
