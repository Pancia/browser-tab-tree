# Browser Tab Tree

A Chromium extension that tracks tab parentage and writes a live markdown tree to disk. When you open a link from a tab, the new tab appears indented under its parent — giving you a persistent, human-readable map of your browsing trails.

```markdown
# Open Tabs

## Window 1
- [Google Search: clojure](https://google.com/search?q=clojure)
  - [Fulcro Docs](https://fulcro.io/docs)
    - [RAD Tutorial](https://fulcro.io/rad)
  - [GitHub - fulcro](https://github.com/fulcrologic/fulcro)

## Window 2
- [Claude](https://claude.ai)
```

## How It Works

The extension listens to Chrome's tab events and sends them over [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) to a local Python script. The script maintains the tab tree in memory and writes three files:

- **`current.md`** — live markdown tree of all open tabs
- **`logs/YYYY-MM-DD.jsonl`** — append-only event log (source of truth)
- **`state.json`** — snapshot for fast restart

## Install

Requires Python 3.10+ and a Chromium-based browser (Chrome, Brave, Arc, Edge, etc.).

1. Clone this repo:
   ```
   git clone https://github.com/Pancia/browser-tab-tree.git
   cd browser-tab-tree
   ```

2. Load the extension in Chrome:
   - Go to `chrome://extensions`
   - Enable "Developer mode"
   - Click "Load unpacked" and select the `extension/` directory
   - Copy the extension ID shown on the card

3. Register the native messaging host:
   ```
   ./install.sh <your-extension-id>
   ```

4. Reload the extension (click the refresh icon on its card)

5. Open some tabs — check `~/.local/share/browser-tab-tree/current.md` for your tree

## Configuration

Create `~/.config/browser-tab-tree/config.json` to customize the output directory:

```json
{
  "output_dir": "~/path/to/your/output"
}
```

Default output: `~/.local/share/browser-tab-tree/`

## Current Limitations

- macOS only (the install script writes to the Chrome-specific macOS path)
- Tree structure depends on Chrome's `openerTabId` — tabs opened via address bar, bookmarks, or session restore appear as roots
- `current.md` is rewritten on every event; user edits will be overwritten
- No extension UI (popup, options page, etc.)

## License

MIT
