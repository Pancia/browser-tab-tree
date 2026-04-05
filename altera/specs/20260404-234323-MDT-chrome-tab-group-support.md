# Spec: Chrome Tab Group Support

**Date**: 2026-04-04
**Status**: draft

## Overview

Chrome/Brave tab groups are a core organizational feature that the current system ignores. Tabs placed in groups lose their group title, color, and visual hierarchy in `current.md`. This spec adds full tab group awareness: the extension sends group metadata and group-membership changes to the host, which tracks groups in its data model and renders them as visually distinct subsections in the markdown output.

Based on sketch `20260404-233833-MDT-tab-group-support`.

## Requirements

1. **Extension: `tabGroups` permission** — Add `"tabGroups"` to `manifest.json` permissions to unlock the `chrome.tabGroups` API and the `groupId` field on tab objects.

2. **Extension: Send `groupId` on TAB_OPEN** — Include `groupId` (integer, `-1` if ungrouped) in every `TAB_OPEN` event payload, both in the `onCreated` listener and in `syncExistingTabs()`.

3. **Extension: Detect `groupId` changes** — In the `chrome.tabs.onUpdated` listener, when `changeInfo.groupId !== undefined`, send a `TAB_GROUP_CHANGED` event with `{tabId, groupId}`. This must not interfere with the existing `TAB_NAVIGATE` logic (both can fire from the same `onUpdated` call).

4. **Extension: Track group metadata lifecycle** — Add listeners for `chrome.tabGroups.onCreated`, `chrome.tabGroups.onUpdated` (both send `GROUP_UPDATE` with `{groupId, windowId, title, color, collapsed}`), and `chrome.tabGroups.onRemoved` (sends `GROUP_REMOVE` with `{groupId}`).

5. **Extension: Sync existing groups at startup** — Add `syncExistingGroups()` that queries all existing tab groups and sends `GROUP_UPDATE` for each. Call it *before* `syncExistingTabs()` so the host has group metadata before processing tab events.

6. **Host: Groups data model** — Add a module-level `groups: dict[int, Group]` alongside `tabs`. Add `groupId` (int, default `-1`) to each tab's dict.

7. **Host: New event handlers** — Implement `handle_group_update`, `handle_group_remove`, and `handle_tab_group_changed`, and register them in `HANDLERS`.

8. **Host: Store `groupId` in `handle_tab_open`** — Read `event.get("groupId", -1)` and store it in the tab dict.

9. **Host: Persist groups in `state.json`** — Change `write_state()` to serialize `{"tabs": ..., "groups": ...}`. Update `load_state()` to handle both the new nested format and the legacy flat-tabs format (auto-detect via presence of `"tabs"` key).

10. **Host: Render groups in `current.md`** — Within each window section, partition tabs into ungrouped and grouped. Render ungrouped root tabs first, then each group as a `### <emoji> <title>` subsection, ordered by the minimum tab index within the group.

11. **Host: Cross-group parent-child handling** — A tab whose parent has a different `groupId` is treated as a root within its own group's section. When rendering a tab's children, skip children whose `groupId` differs from the current tab's—they appear in their own group section.

12. **Host: Color emoji map** — Map Chrome's 9 group colors to emoji: grey→⚪, blue→🔵, red→🔴, yellow→🟡, green→🟢, pink→🩷, purple→🟣, cyan→🩵, orange→🟠.

13. **Tests** — Add test cases in `test_host.py` covering: GROUP_UPDATE + TAB_OPEN with groupId, TAB_GROUP_CHANGED moving a tab into/out of a group, GROUP_REMOVE cleanup, markdown rendering with group headings and emoji, cross-group parent-child rendering, and backward-compatible state.json loading.

## Acceptance Criteria

- [ ] `manifest.json` includes `"tabGroups"` in permissions
- [ ] TAB_OPEN events include `groupId` field (both live and sync)
- [ ] `chrome.tabs.onUpdated` sends TAB_GROUP_CHANGED when `changeInfo.groupId` is present, without breaking TAB_NAVIGATE
- [ ] GROUP_UPDATE events fire on group create, update, and startup sync
- [ ] GROUP_REMOVE events fire on group removal
- [ ] `syncExistingGroups()` runs before `syncExistingTabs()` at startup
- [ ] Host stores `groupId` on each tab, defaulting to `-1`
- [ ] Host `groups` dict is populated by GROUP_UPDATE and cleaned by GROUP_REMOVE
- [ ] TAB_GROUP_CHANGED updates a tab's `groupId` in the host
- [ ] GROUP_REMOVE defensively resets any tabs still referencing the removed group
- [ ] `state.json` contains `{"tabs": ..., "groups": ...}` structure
- [ ] `load_state()` handles both new and legacy `state.json` formats
- [ ] `current.md` renders grouped tabs under `### <emoji> <title>` headings
- [ ] Unnamed groups render as `### <emoji> (unnamed)`
- [ ] Groups are ordered by minimum tab index within the window section
- [ ] Ungrouped tabs render before group sections
- [ ] A child tab in a different group than its parent appears as a root in its own group's section
- [ ] Children with mismatched groupId are skipped when rendering a parent's subtree
- [ ] All existing tests in `test_host.py` continue to pass
- [ ] New tests cover the 6 scenarios listed in requirement 13
- [ ] `cd host && python3 test_host.py` exits 0

## Documentation Updates

- `CLAUDE.md` — Update "Key Design Decisions" to mention the 3 new event types (GROUP_UPDATE, GROUP_REMOVE, TAB_GROUP_CHANGED) and the `tabGroups` permission.

## Technical Approach

### Extension changes (`extension/manifest.json`, `extension/background.js`)

**manifest.json**: Add `"tabGroups"` to the permissions array (line 5).

**background.js — TAB_OPEN with groupId**: In `chrome.tabs.onCreated` (line 32–49), add `event.groupId = tab.groupId;` before the `send(event)` call. In `syncExistingTabs()` (line 99–112), add `groupId: tab.groupId` to the event payload.

**background.js — TAB_GROUP_CHANGED in onUpdated**: In the `chrome.tabs.onUpdated` listener (line 65–75), restructure to handle both `changeInfo.url` and `changeInfo.groupId` independently (remove early return, use separate `if` blocks):

```js
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && isNavigableUrl(changeInfo.url)) {
    send({ type: "TAB_NAVIGATE", ts: now(), tabId, url: changeInfo.url, title: tab.title || "" });
  }
  if (changeInfo.groupId !== undefined) {
    send({ type: "TAB_GROUP_CHANGED", ts: now(), tabId, groupId: changeInfo.groupId });
  }
});
```

**background.js — Group lifecycle listeners**: Add three new listeners for `chrome.tabGroups.onCreated`, `chrome.tabGroups.onUpdated` (both send GROUP_UPDATE), and `chrome.tabGroups.onRemoved` (sends GROUP_REMOVE). Place after the existing tab listeners.

**background.js — Startup sync**: Add `syncExistingGroups()` using `chrome.tabGroups.query({})`. Change the startup call to `syncExistingGroups().then(() => syncExistingTabs())` or use `await` in an async IIFE.

### Host changes (`host/host.py`)

**Data model** (after line 37): Add `groups: dict[int, dict] = {}`. In `handle_tab_open` (line 79–87), add `"groupId": event.get("groupId", -1)` to the tab dict.

**New handlers**: Add `handle_group_update`, `handle_group_remove`, `handle_tab_group_changed` as described in the sketch (section 7). Register all three in the `HANDLERS` dict (line 137–142).

**State persistence**: In `write_state()` (line 177–181), change to serialize `{"tabs": tabs, "groups": groups}`. In `load_state()` (line 238–253), detect the format by checking for `"tabs"` key: if present, load both `tabs` and `groups`; otherwise treat as legacy flat-tabs format.

**Markdown rendering**: In `render_markdown()` (line 184–219):
1. Add `GROUP_COLOR_EMOJI` dict at module level.
2. Replace the simple root-gathering with a `_group_roots(wid)` function that returns `{groupId: [tabId, ...]}` where a tab is a "group root" if its parentId is None or its parent has a different groupId.
3. Within each window, render ungrouped roots (groupId == -1) first, then each group as `### <emoji> <title>`, ordered by `min(tab["index"])` across the group's tabs.
4. Modify `_render_tab` to accept a `render_gid` parameter and skip children whose `groupId` differs from `render_gid`.

### Test changes (`host/test_host.py`)

Add these test functions:
- `test_group_basic` — GROUP_UPDATE + TAB_OPEN with groupId → verify group heading in markdown
- `test_tab_group_changed` — Move a tab into a group via TAB_GROUP_CHANGED → verify it moves under group heading
- `test_group_remove` — GROUP_REMOVE → verify group heading disappears, tabs become ungrouped
- `test_group_cross_parent` — Child in different group than parent → verify each appears in its own group section
- `test_group_colors` — Verify emoji rendering for multiple colors
- `test_state_restart_with_groups` — Verify state.json round-trip with groups data

## Out of Scope

- **Interleaved ordering of ungrouped tabs and groups** — Ungrouped tabs always render before groups within a window. Faithful tab-strip interleaving would add significant complexity for minimal benefit.
- **Collapsed state rendering** — The `collapsed` field is tracked in the data model but not reflected in `current.md` output. Could be added later (e.g., `(collapsed)` suffix on heading).
- **State format versioning** — Auto-detection by key presence is sufficient; no explicit `"version"` field.
- **Empty group filtering** — Empty groups (no member tabs) are tracked; they simply produce a heading with no tabs listed.
- **Firefox/Safari support** — `chrome.tabGroups` is Chromium-only.

## Open Questions

1. **Collapsed state display**: Should `current.md` indicate when a group is collapsed (e.g., `### 🔵 Research (collapsed)`)? The sketch tracks the field but doesn't render it. Recommend: defer to a follow-up since the data is already persisted.

2. **Ungrouped tab interleaving**: The current approach renders all ungrouped tabs before any groups. A more faithful rendering would interleave based on tab index position. Recommend: ship with the simpler approach, revisit if users find the ordering confusing.
