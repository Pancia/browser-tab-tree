# Worklog: Phase 4: Add TAB_NAVIGATE listener with URL filtering and install.sh

**Date**: 20260404-213032-MDT
**Task**: m-004
**Agent**: w-04

## Summary

Added `chrome.tabs.onUpdated` listener to `extension/background.js` that sends `TAB_NAVIGATE` events to the native host. The listener filters on `changeInfo.url` (only real navigations) and uses an `isNavigableUrl` function to skip non-http(s) URLs (chrome://, about:, data:, blob:, extensions, etc.). The host already supported TAB_NAVIGATE from Phase 1. install.sh was already present from a prior phase.

Added 23 new tests covering: JS structure checks for onUpdated/TAB_NAVIGATE/URL filtering, e2e TAB_NAVIGATE with tree preservation, unknown tab no-op, and JSONL logging of navigate events.

All 106 tests pass (34 host + 72 extension).

## How It Went

Straightforward. The host already had `handle_tab_navigate` implemented, so this was purely an extension-side change. The spec was clear on URL filtering requirements. No blockers encountered.

## System Learnings

None specific — the phased build approach continues to work well, with each phase building cleanly on prior work.

## Process Improvements

None needed.

## Self-Improvement Notes

None.
