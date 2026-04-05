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
