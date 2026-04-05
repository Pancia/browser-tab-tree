#!/bin/bash
set -euo pipefail

HOST_PATH="$(cd "$(dirname "$0")/host" && pwd)/run_host.sh"
MANIFEST_NAME="com.browser_tab_tree"

# Detect browser
BROWSER="${2:-brave}"
case "$BROWSER" in
  chrome)
    MANIFEST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts" ;;
  brave)
    MANIFEST_DIR="$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts" ;;
  edge)
    MANIFEST_DIR="$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts" ;;
  arc)
    MANIFEST_DIR="$HOME/Library/Application Support/Arc/User Data/NativeMessagingHosts" ;;
  *)
    echo "Unknown browser: $BROWSER (supported: chrome, brave, edge, arc)" >&2; exit 1 ;;
esac

mkdir -p "$MANIFEST_DIR"
chmod +x "$HOST_PATH"

cat > "$MANIFEST_DIR/$MANIFEST_NAME.json" << EOF
{
  "name": "$MANIFEST_NAME",
  "description": "Browser Tab Tree native messaging host",
  "path": "$HOST_PATH",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://${1:-EXTENSION_ID_HERE}/"]
}
EOF

echo "Installed native messaging host manifest to: $MANIFEST_DIR/$MANIFEST_NAME.json"
echo "Browser: $BROWSER"
echo "Extension ID: ${1:-'NOT SET — pass extension ID as first argument'}"
echo ""
echo "Usage: ./install.sh <extension-id> [browser]"
