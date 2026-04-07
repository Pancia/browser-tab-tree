#!/usr/bin/env bash
# Restore test: 2 windows, 15 tabs, 3 groups
FIFO="${BTT_FIFO:-$HOME/TheAkashicRecords/browser-sync/cmd.fifo}"

cat > "$FIFO" <<'EOF'
{"command":"restore_session","windows":[{"tabs":[{"url":"https://en.wikipedia.org/wiki/Tab_(interface)","title":"Tab (interface)"},{"url":"https://en.wikipedia.org/wiki/Browser_extension","title":"Browser extension"},{"url":"https://en.wikipedia.org/wiki/Chromium_(web_browser)","title":"Chromium"},{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Rick Astley"},{"url":"https://www.youtube.com/watch?v=9bZkp7q19f0","title":"PSY - Gangnam Style"},{"url":"https://www.youtube.com/watch?v=kJQP7kiw5Fk","title":"Luis Fonsi - Despacito"},{"url":"https://github.com/anthropics/claude-code","title":"Claude Code"},{"url":"https://github.com/nickel-org/nickel.rs","title":"nickel.rs"},{"url":"https://news.ycombinator.com","title":"Hacker News"},{"url":"https://lobste.rs","title":"Lobsters"}],"groups":[{"title":"wiki","color":"cyan","tabIndices":[0,1,2]},{"title":"music","color":"green","tabIndices":[3,4,5]},{"title":"code","color":"purple","tabIndices":[6,7]}]},{"tabs":[{"url":"https://www.rust-lang.org","title":"Rust Lang"},{"url":"https://doc.rust-lang.org/book/","title":"The Rust Book"},{"url":"https://crates.io","title":"crates.io"},{"url":"https://play.rust-lang.org","title":"Rust Playground"},{"url":"https://docs.rs","title":"docs.rs"}],"groups":[{"title":"rust","color":"orange","tabIndices":[0,1,2,3,4]}]}]}
EOF

echo "Sent 2 windows, 15 tabs, 4 groups to $FIFO"
