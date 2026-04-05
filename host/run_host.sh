#!/bin/bash
# Wrapper for Chrome Native Messaging — ensures python3 is found
# even when Chrome launches without the user's shell environment.
DIR="$(cd "$(dirname "$0")" && pwd)"

# Load config from ~/.config/browser-tab-tree/config.json
CONFIG="$HOME/.config/browser-tab-tree/config.json"
if [ -f "$CONFIG" ]; then
  BTT_OUTPUT_DIR="$(python3 -c "import json,sys,os;v=json.load(sys.stdin).get('output_dir','');print(os.path.expanduser(v))" < "$CONFIG")"
fi

export BTT_OUTPUT_DIR="${BTT_OUTPUT_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/browser-tab-tree}"
exec /usr/bin/env -P "/Users/anthony/.pyenv/shims:/usr/local/bin:/usr/bin:/bin" python3 "$DIR/host.py"
