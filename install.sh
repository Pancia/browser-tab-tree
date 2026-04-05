#!/bin/bash
set -euo pipefail

HOST_PATH="$(cd "$(dirname "$0")/host" && pwd)/run_host.sh"
MANIFEST_NAME="com.browser_tab_tree"

# Detect browser
BROWSER="${1:-brave}"
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

MANIFEST_CONTENT=$(cat << EOF
{
  "name": "$MANIFEST_NAME",
  "description": "Browser Tab Tree native messaging host",
  "path": "$HOST_PATH",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://${2:-EXTENSION_ID_HERE}/"]
}
EOF
)

chmod +x "$HOST_PATH"

# Install to browser-specific user dir
mkdir -p "$MANIFEST_DIR"
echo "$MANIFEST_CONTENT" > "$MANIFEST_DIR/$MANIFEST_NAME.json"
echo "Installed to: $MANIFEST_DIR/$MANIFEST_NAME.json"

# Brave also checks Chrome's user-level NativeMessagingHosts directory
if [ "$BROWSER" = "brave" ]; then
  CHROME_USER_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
  mkdir -p "$CHROME_USER_DIR"
  echo "$MANIFEST_CONTENT" > "$CHROME_USER_DIR/$MANIFEST_NAME.json"
  echo "Installed to: $CHROME_USER_DIR/$MANIFEST_NAME.json"
fi

echo ""
echo "Browser: $BROWSER"
echo "Extension ID: ${2:-'NOT SET — pass extension ID as second argument'}"
echo "Usage: ./install.sh [browser] <extension-id>"
