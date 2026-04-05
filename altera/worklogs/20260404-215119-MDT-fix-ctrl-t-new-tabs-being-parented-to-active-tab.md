# Worklog: Fix Ctrl+T new tabs being parented to active tab

**Date**: 20260404-215119-MDT
**Task**: m-005
**Agent**: w-05

## Summary

Fixed `extension/background.js` onCreated listener to strip `openerTabId` when the new tab's URL is `chrome://newtab` or empty. This prevents Ctrl+T new tabs from being parented to the active tab in the tree. Link-opened tabs (with real URLs) still get their `openerTabId` preserved.

## How It Went

Straightforward 2-line change. No test suite exists for the extension, so verification is manual. No pre-existing test/lint targets in Makefile.

## System Learnings

Chrome sets `openerTabId` on Ctrl+T new tabs, which is semantically misleading — it doesn't mean the user intended to create a child tab.

## Process Improvements

None — task was well-scoped with clear instructions.

## Self-Improvement Notes

None.

