# Spec: Browser Tab Tree MVP

**Date**: 2026-04-04
**Status**: draft

## Overview

A Chromium extension that tracks tab parentage via `openerTabId` and writes a live markdown tree to disk through Native Messaging. The extension captures three event types (TAB_OPEN, TAB_CLOSE, TAB_NAVIGATE), sends them as JSONL to a single-file zero-dependency Python native host, which maintains an in-memory tree and atomically writes `current.md` on every change. The goal is a living, human-readable, editor-friendly map of your browsing research trails.

This is the MVP: get the core event loop working end-to-end with correct tree structure and reliable file output. Richness and polish come later.

## Requirements

1. **Chrome Extension (MV3)** — A service worker that listens to `chrome.tabs.onCreated`, `chrome.tabs.onRemoved`, and `chrome.tabs.onUpdated`, and sends JSONL events over a `chrome.runtime.connectNative()` port to the native host.

2. **Three Event Types Only** — `TAB_OPEN` (tab created, includes openerTabId if available), `TAB_CLOSE` (tab removed), `TAB_NAVIGATE` (URL changed within an existing tab). No window events, no move/pin/activate tracking.

3. **JSONL Wire Format** — Each message sent over the native messaging port is a single JSON object. One event per message. Fields: `{type, ts, tabId, windowId?, openerTabId?, url?, title?}`. The native host receives these framed by Chrome's 4-byte little-endian length prefix protocol.

4. **Single-File Python Native Host** — `host.py`, zero external dependencies, Python 3.10+. Reads length-prefixed JSON from stdin, maintains the tab tree in memory, writes output files. Logs events to a JSONL append-only file.

5. **JSONL Log File** — `logs/YYYY-MM-DD.jsonl` — append-only, one JSON object per line, daily rotation. This is the source of truth. Raw events exactly as received, plus a timestamp if not already present.

6. **State Snapshot** — `state.json` — Written atomically alongside `current.md` on every update. Contains the full in-memory tree (tab dict keyed by tabId, each with `{tabId, windowId, openerTabId, url, title, children: [tabId, ...]}`). On startup, the native host loads `state.json` if it exists and is from the current day, avoiding a full log replay.

7. **`current.md` Output** — Atomically written (write-to-temp + `os.rename`) on every tree mutation. Format:
   ```markdown
   # Open Tabs

   ## Window 1847
   - [Google Search: clojure](https://google.com/search?q=clojure)
     - [GitHub - fulcro](https://github.com/fulcrologic/fulcro)

   ## Window 1848
   - [Claude](https://claude.ai)
   ```
   Two-space indent per tree level. Closed tabs are removed immediately (recoverable from log). Empty windows are omitted.

8. **Tree Structure Rules**:
   - On TAB_OPEN: if `openerTabId` is set and that tab exists in the tree, insert as child. Otherwise, insert as root of its window.
   - On TAB_CLOSE: remove the tab. Promote its children to its parent (grandparent promotion). If the closed tab was a root, its children become roots.
   - On TAB_NAVIGATE: update `url` and `title` in-place. Only process when `changeInfo.url` is present (real navigation, not loading state change). Skip chrome://, about:, and extension:// URLs.

9. **Session Restore Handling** — On extension startup (service worker activation), query all existing tabs via `chrome.tabs.query({})` and send a synthetic `TAB_OPEN` for each. The native host treats these as new roots (no parentage). This gives a flat but complete starting tree.

10. **MV3 Service Worker Lifecycle** — The native messaging port keeps the service worker alive, but Chrome enforces a ~5-minute hard cap. On `port.onDisconnect`, the extension must detect this in its next activation and reconnect via `connectNative()`. The native host must handle stdin EOF gracefully: flush state.json and exit. A new host process spawns on reconnect. The host reads `state.json` on startup to restore state across these restarts.

11. **`install.sh`** — A shell script that:
    - Determines the absolute path to `host.py`
    - Generates the native messaging host manifest JSON (`name`, `description`, `path`, `type: "stdio"`, `allowed_origins`)
    - Writes it to `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.browser_tab_tree.json`
    - Makes `host.py` executable
    - Prints success message with the extension ID placeholder to fill in

12. **Navigation Filtering** — Only log TAB_NAVIGATE for URLs with a hostname and path (http/https). Skip `chrome://`, `about:`, `chrome-extension://`, `data:`, `blob:`, empty URLs, and `new tab` pages.

13. **Debouncing** — No debounce for the MVP. Every event triggers an immediate `current.md` write. The atomic write pattern (temp file + rename) makes this safe. Debouncing is a future optimization.

## Acceptance Criteria

- [ ] Running `echo '{"type":"TAB_OPEN","ts":"...","tabId":1,"windowId":1,"url":"https://example.com","title":"Example"}' | python3 host.py` (with proper length framing) creates `current.md` with a `[Example](https://example.com)` entry and appends to `logs/YYYY-MM-DD.jsonl`
- [ ] Sending TAB_OPEN with `openerTabId` pointing to an existing tab nests the new tab as a child in `current.md`
- [ ] Sending TAB_CLOSE for a parent tab promotes its children to the grandparent level
- [ ] Sending TAB_CLOSE for a root tab promotes its children to window roots
- [ ] Sending TAB_NAVIGATE updates the URL and title in `current.md` without changing tree structure
- [ ] `state.json` is written on every mutation and can be loaded on restart to reconstruct the tree without replaying the log
- [ ] `current.md` is written atomically (no partial writes visible to editors)
- [ ] The native host exits cleanly on stdin EOF (no crash, state.json is flushed)
- [ ] `install.sh` creates a valid native messaging host manifest at the correct macOS path
- [ ] The extension sends synthetic TAB_OPEN events for all pre-existing tabs on service worker activation
- [ ] The extension reconnects the native messaging port after service worker restart
- [ ] Chrome internal URLs (chrome://, about:, etc.) are excluded from TAB_NAVIGATE events
- [ ] `host.py` has zero external dependencies and runs on Python 3.10+
- [ ] Loading the unpacked extension in Chrome shows no errors in `chrome://extensions`

## Documentation Updates

- PLAN.md — update status from "Design complete, not yet built" to reflect MVP spec and build phases
- README.md — create with install instructions (load unpacked extension, run install.sh, fill in extension ID)

## Technical Approach

### Directory Structure

```
browser-tab-tree/
├── extension/
│   ├── manifest.json          # MV3 manifest
│   ├── background.js          # Service worker: event listeners + native messaging
│   └── icons/                 # Extension icons (placeholder PNGs)
├── host/
│   └── host.py                # Native messaging host (single file, zero deps)
├── install.sh                 # Native host registration script
├── output/                    # Default output directory (gitignored)
│   ├── current.md
│   ├── state.json
│   └── logs/
│       └── 2026-04-04.jsonl
├── PLAN.md
└── README.md
```

### Native Host (`host/host.py`)

**Message I/O**: Read 4-byte little-endian length prefix from stdin, then read that many bytes of JSON. No need to write messages back to the extension for the MVP (fire-and-forget from extension side).

**Data Model**:
```python
tabs: dict[int, Tab]  # tabId → Tab
# Tab = {"tabId": int, "windowId": int, "parentId": int|None, "url": str, "title": str, "children": list[int]}
```

**Event Handlers**:
- `handle_tab_open(event)`: Create Tab entry. If `openerTabId` exists in `tabs`, set `parentId` and append to parent's `children`. Otherwise `parentId = None` (root).
- `handle_tab_close(event)`: Find tab. For each child, set child's `parentId` to this tab's `parentId` and move into parent's `children` list (or make root). Remove tab from parent's `children`. Delete tab from `tabs`.
- `handle_tab_navigate(event)`: Update `url` and `title` on existing tab. No-op if tabId not found.

**Output Loop**: After each event handler, call `write_state()` and `write_tree()`.

- `write_state()`: Serialize `tabs` dict to JSON, write to `output/state.json.tmp`, `os.rename` to `output/state.json`.
- `write_tree()`: Group tabs by windowId. For each window, recursively render roots (tabs with `parentId == None` or parent not in `tabs`) as indented markdown. Write to `output/current.md.tmp`, `os.rename` to `output/current.md`.

**Startup**: Check for `output/state.json`. If it exists and its log date matches today, load it into `tabs`. Otherwise start empty.

**Shutdown**: On stdin EOF (read returns empty), flush state.json one final time and `sys.exit(0)`. Wrap the main loop in try/finally.

**Config**: Output directory path read from environment variable `BTT_OUTPUT_DIR`, defaulting to `output/` relative to `host.py`'s directory.

### Extension (`extension/background.js`)

**Manifest** (`extension/manifest.json`):
```json
{
  "manifest_version": 3,
  "name": "Browser Tab Tree",
  "version": "0.1.0",
  "permissions": ["tabs", "nativeMessaging"],
  "background": {
    "service_worker": "background.js"
  }
}
```

**Port Management**:
```javascript
let port = null;

function ensurePort() {
  if (!port) {
    port = chrome.runtime.connectNative("com.browser_tab_tree");
    port.onDisconnect.addListener(() => { port = null; });
  }
  return port;
}

function send(event) {
  try { ensurePort().postMessage(event); }
  catch (e) { port = null; }  // will reconnect on next send
}
```

**Event Listeners**:
- `chrome.tabs.onCreated`: Send `{type: "TAB_OPEN", ts, tabId: tab.id, windowId: tab.windowId, openerTabId: tab.openerTabId, url: tab.pendingUrl || tab.url, title: tab.title}`.
- `chrome.tabs.onRemoved`: Send `{type: "TAB_CLOSE", ts, tabId}`.
- `chrome.tabs.onUpdated`: Only fire when `changeInfo.url` is present and URL passes the protocol filter. Send `{type: "TAB_NAVIGATE", ts, tabId, url: changeInfo.url, title: tab.title}`.

**Startup Sync**: On service worker activation, `chrome.tabs.query({})` to get all open tabs, send a TAB_OPEN for each (with `openerTabId: null` since it's unknown for pre-existing tabs).

### Build Order (Phases)

**Phase 1 — Native host with fake events**: Build `host.py` with stdin message reading, JSONL logging, state.json, and current.md output. Test with a small Python script that sends length-prefixed JSON events to host.py's stdin.

**Phase 2 — Minimal extension with flat tab list**: Build `manifest.json` and `background.js` with TAB_OPEN and TAB_CLOSE only. No openerTabId usage yet — all tabs are roots. Verify events flow end-to-end and current.md updates.

**Phase 3 — Add openerTabId tree structure**: Wire up `openerTabId` in TAB_OPEN. Add orphan promotion logic in TAB_CLOSE. current.md now shows indented tree.

**Phase 4 — Add TAB_NAVIGATE**: Add `chrome.tabs.onUpdated` listener with URL filtering. Verify in-place URL/title updates in current.md.

### `install.sh`

```bash
#!/bin/bash
set -euo pipefail
HOST_PATH="$(cd "$(dirname "$0")/host" && pwd)/host.py"
MANIFEST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
MANIFEST_PATH="$MANIFEST_DIR/com.browser_tab_tree.json"
mkdir -p "$MANIFEST_DIR"
chmod +x "$HOST_PATH"
# Generate manifest (extension ID must be filled in after first load)
cat > "$MANIFEST_PATH" << EOF
{
  "name": "com.browser_tab_tree",
  "description": "Browser Tab Tree native messaging host",
  "path": "$HOST_PATH",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://${1:-EXTENSION_ID_HERE}/"]
}
EOF
echo "Installed native messaging host manifest to: $MANIFEST_PATH"
echo "Extension ID: ${1:-'NOT SET — pass extension ID as first argument'}"
```

## Out of Scope

- **Bidirectional sync** (editing current.md to control tabs)
- **Annotation preservation** in current.md (future value multiplier — when current.md is rewritten, any user-added notes are lost; preserving them requires diffing or a sidecar file)
- **Debounced writes** (every event writes immediately in MVP)
- **Cross-browser support** (Chromium only)
- **Config file** (config.yaml from PLAN.md deferred; use env vars for now)
- **Tab move/pin/activate tracking**
- **Window open/close events**
- **Time tracking or tab activity metadata**
- **Historical tree viewer or log replay CLI**
- **Extension popup or options UI**
- **openerTabId heuristic fallbacks** (e.g., inferring parentage from focus order or referrer — listed as open question)
- **Daily log rotation cleanup** (old logs accumulate; no purge mechanism)
- **Linux/Windows install paths** (install.sh is macOS-only for MVP)

## Open Questions

1. **openerTabId heuristic fallbacks** — `openerTabId` is not set for middle-click or Ctrl+click in older Chrome versions, omnibar navigation, bookmarks, or restored tabs. For MVP, tabs without openerTabId are simply roots. Future work could infer parentage from the most-recently-active tab at creation time, or from referrer headers. How aggressive should we be? The risk is false parentage being worse than no parentage.

2. **Service worker 5-minute cap** — Research suggests the native messaging port extends the 30-second idle timeout but may not bypass the 5-minute hard cap. If the cap applies, the host process dies every 5 minutes and restarts from state.json. This is acceptable for MVP but needs empirical testing. If the cap doesn't apply (port keeps it alive indefinitely), the restart logic still works as a safety net.

3. **Output directory location** — PLAN.md suggests `~/browser-tab-tree/`. The spec uses `output/` relative to the project for development convenience. The env var `BTT_OUTPUT_DIR` allows configuration. Should install.sh set this to a user-friendly default like `~/browser-tab-tree/`?

4. **Extension ID in install.sh** — The extension ID is only known after loading the unpacked extension once. The install flow is: load extension → copy ID → run `install.sh <id>` → reload extension. Is this friction acceptable or should we explore a `key` field in manifest.json for a stable ID during development?

5. **Shebang line** — `host.py` needs `#!/usr/bin/env python3` and must be executable. Should we also support a wrapper script for systems where Python 3.10+ isn't the default `python3`?
