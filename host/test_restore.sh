#!/usr/bin/env bash
# Restore test: 2 windows, 15 tabs, 3 groups
# Generates a fake current.md and pipes it through restore_session.py
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat <<'MD' | python3 "$SCRIPT_DIR/restore_session.py"
# Open Tabs

## Window 1
- [Hacker News](https://news.ycombinator.com)
- [Lobsters](https://lobste.rs)

### 🩵 wiki
- [Tab (interface)](https://en.wikipedia.org/wiki/Tab_(interface))
- [Browser extension](https://en.wikipedia.org/wiki/Browser_extension)
- [Chromium](https://en.wikipedia.org/wiki/Chromium_(web_browser))

### 🟢 music
- [Rick Astley](https://www.youtube.com/watch?v=dQw4w9WgXcQ)
- [PSY - Gangnam Style](https://www.youtube.com/watch?v=9bZkp7q19f0)
- [Luis Fonsi - Despacito](https://www.youtube.com/watch?v=kJQP7kiw5Fk)

### 🟣 code
- [Claude Code](https://github.com/anthropics/claude-code)
- [nickel.rs](https://github.com/nickel-org/nickel.rs)

## Window 2

### 🟠 rust
- [Rust Lang](https://www.rust-lang.org)
- [The Rust Book](https://doc.rust-lang.org/book/)
- [crates.io](https://crates.io)
- [Rust Playground](https://play.rust-lang.org)
- [docs.rs](https://docs.rs)
MD
