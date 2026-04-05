# Sketch: Tab Group Support

**Date**: 2026-04-04
**Status**: exploring

## Motivation

Chrome/Brave tab groups are a core organizational primitive that current.md ignores entirely. Users who group tabs lose that structure in the markdown output. Adding group awareness lets current.md reflect how tabs are actually organized in the browser, with group titles, colors, and visual hierarchy.

## Design

### 1. Extension: Add `tabGroups` permission

In `extension/manifest.json`, add `"tabGroups"` to the permissions array. This unlocks `chrome.tabGroups.get()`, `chrome.tabGroups.onCreated`, `chrome.tabGroups.onUpdated`, `chrome.tabGroups.onRemoved`, and the `groupId` field on tab objects.

```json
"permissions": ["tabs", "tabGroups", "nativeMessaging"]
```

### 2. Extension: Send `groupId` in TAB_OPEN events

In `background.js:32-49` (`chrome.tabs.onCreated` listener), add `groupId` to the event payload:

```js
event.groupId = tab.groupId;  // -1 if ungrouped
```

Do the same in `syncExistingTabs()` (line 99-112).

### 3. Extension: Detect groupId changes via onUpdated

In the existing `chrome.tabs.onUpdated` listener (line 65-75), add a check for `changeInfo.groupId !== undefined`. When detected, send a new event:

```js
if (changeInfo.groupId !== undefined) {
  send({
    type: "TAB_GROUP_CHANGED",
    ts: now(),
    tabId: tabId,
    groupId: changeInfo.groupId,  // -1 means removed from group
  });
}
```

This fires when a tab is added to a group, moved between groups, or removed from a group. It's separate from URL-change navigation events—both can fire from the same `onUpdated` call, so handle both (don't early-return on one).

### 4. Extension: Track group metadata lifecycle

Add three new listeners for the group objects themselves:

```js
chrome.tabGroups.onCreated.addListener((group) => {
  send({
    type: "GROUP_UPDATE",
    ts: now(),
    groupId: group.id,
    windowId: group.windowId,
    title: group.title || "",
    color: group.color,       // "grey"|"blue"|"red"|"yellow"|"green"|"pink"|"purple"|"cyan"|"orange"
    collapsed: group.collapsed,
  });
});

chrome.tabGroups.onUpdated.addListener((group) => {
  send({
    type: "GROUP_UPDATE",     // same event type — idempotent upsert on host side
    ts: now(),
    groupId: group.id,
    windowId: group.windowId,
    title: group.title || "",
    color: group.color,
    collapsed: group.collapsed,
  });
});

chrome.tabGroups.onRemoved.addListener((group) => {
  send({
    type: "GROUP_REMOVE",
    ts: now(),
    groupId: group.id,
  });
});
```

### 5. Extension: Sync existing groups at startup

Add a `syncExistingGroups()` function called before `syncExistingTabs()`:

```js
async function syncExistingGroups() {
  const allGroups = await chrome.tabGroups.query({});
  for (const group of allGroups) {
    send({
      type: "GROUP_UPDATE",
      ts: now(),
      groupId: group.id,
      windowId: group.windowId,
      title: group.title || "",
      color: group.color,
      collapsed: group.collapsed,
    });
  }
}
```

Call order matters: groups first, then tabs. This way the host already knows group metadata when it processes TAB_OPEN events with groupId.

### 6. Host: Add groups data model

In `host/host.py`, add a new top-level dict alongside `tabs`:

```python
Group = dict[str, Any]
# Keys: groupId (int), windowId (int), title (str), color (str), collapsed (bool)

groups: dict[int, Group] = {}
```

Add `groupId` to the `Tab` type comment:
```python
# Keys: tabId, windowId, parentId, url, title, index, children, groupId (int, -1 if ungrouped)
```

### 7. Host: New event handlers

```python
def handle_tab_group_changed(event: dict) -> None:
    tab_id = event["tabId"]
    tab = tabs.get(tab_id)
    if tab is None:
        return
    tab["groupId"] = event.get("groupId", -1)

def handle_group_update(event: dict) -> None:
    gid = event["groupId"]
    groups[gid] = {
        "groupId": gid,
        "windowId": event["windowId"],
        "title": event.get("title", ""),
        "color": event.get("color", "grey"),
        "collapsed": event.get("collapsed", False),
    }

def handle_group_remove(event: dict) -> None:
    gid = event["groupId"]
    groups.pop(gid, None)
    # Tabs should already have groupId=-1 via TAB_GROUP_CHANGED events
    # but clean up defensively:
    for tab in tabs.values():
        if tab.get("groupId") == gid:
            tab["groupId"] = -1
```

Register in `HANDLERS`:
```python
"TAB_GROUP_CHANGED": handle_tab_group_changed,
"GROUP_UPDATE": handle_group_update,
"GROUP_REMOVE": handle_group_remove,
```

### 8. Host: Update handle_tab_open

In `handle_tab_open()` (line 66-87), store `groupId`:

```python
tabs[tab_id] = {
    ...
    "groupId": event.get("groupId", -1),
}
```

### 9. Host: Update state.json to include groups

In `write_state()` (line 177-181), serialize both tabs and groups:

```python
def write_state() -> None:
    state = {"tabs": tabs, "groups": groups}
    _atomic_write(
        OUTPUT_DIR / "state.json",
        json.dumps(state, indent=2, sort_keys=True) + "\n",
    )
```

Update `load_state()` to handle both the new format and the old flat-tabs format for backward compatibility:

```python
def load_state() -> None:
    global tabs, groups
    # ... existing mtime check ...
    raw = json.load(f)
    if "tabs" in raw and "groups" in raw:
        tabs = {int(k): v for k, v in raw["tabs"].items()}
        groups = {int(k): v for k, v in raw["groups"].items()}
    else:
        # Legacy format: flat dict of tabs
        tabs = {int(k): v for k, v in raw.items()}
        groups = {}
```

### 10. Host: Render groups in current.md

Revise `render_markdown()` (line 184-219). Within each window section, partition tabs into grouped and ungrouped. Render ungrouped root tabs first, then each group as a subsection.

Color emoji map:
```python
GROUP_COLOR_EMOJI = {
    "grey": "⚪", "blue": "🔵", "red": "🔴", "yellow": "🟡",
    "green": "🟢", "pink": "🩷", "purple": "🟣", "cyan": "🩵", "orange": "🟠",
}
```

New rendering logic within each window:

```python
for wid in sorted(windows):
    lines.append(f"\n## Window {wid}")

    # Collect root tabs for this window
    window_roots = roots.get(wid, [])
    window_roots.sort(key=lambda tid: tabs[tid]["index"] if tid in tabs else 0)

    # Partition: ungrouped roots vs grouped roots
    ungrouped = [tid for tid in window_roots if tabs.get(tid, {}).get("groupId", -1) == -1]
    grouped_by_gid: dict[int, list[int]] = {}
    for tid in window_roots:
        gid = tabs.get(tid, {}).get("groupId", -1)
        if gid != -1:
            grouped_by_gid.setdefault(gid, []).append(tid)

    # Render ungrouped tabs
    for tid in ungrouped:
        _render_tab(tid, 0)

    # Render each group
    for gid, gtabs in sorted(grouped_by_gid.items(),
                              key=lambda pair: min(tabs[t]["index"] for t in pair[1] if t in tabs)):
        group = groups.get(gid, {})
        emoji = GROUP_COLOR_EMOJI.get(group.get("color", "grey"), "⚪")
        title = group.get("title", "") or "(unnamed)"
        lines.append(f"\n### {emoji} {title}")
        for tid in gtabs:
            _render_tab(tid, 0)
```

This renders as:

```markdown
## Window 123

- [Ungrouped Tab](https://...)
  - [Child](https://...)

### 🔵 Research
- [Paper A](https://...)
  - [Related Work](https://...)
- [Paper B](https://...)

### 🔴 Shopping
- [Amazon](https://...)
```

### 11. Host: Handle children that span group boundaries

A tab's parentId tree (opener-based) is orthogonal to groupId. A child tab can be in a different group than its parent. The rendering must handle this: when rendering a group's section, only render root tabs that belong to that group. Children are rendered under their parent regardless of the child's own groupId—the tree structure takes priority within a group section.

However, if a child tab has a different groupId than its parent, it should appear as a root in its own group's section instead. Adjust the root-gathering logic: a tab is a "group root" if (a) its parentId is None, or (b) its parent has a different groupId.

```python
def _group_roots(wid: int) -> dict[int, list[int]]:
    """Return {groupId: [tabId, ...]} of tabs that are roots within their group."""
    result: dict[int, list[int]] = {}
    for tab in tabs.values():
        if tab["windowId"] != wid:
            continue
        gid = tab.get("groupId", -1)
        parent = tabs.get(tab["parentId"]) if tab["parentId"] is not None else None
        if parent is None or parent.get("groupId", -1) != gid:
            result.setdefault(gid, []).append(tab["tabId"])
    return result
```

When rendering a tab's children in `_render_tab`, skip children whose groupId differs from the current tab's groupId—they'll appear in their own group section.

### 12. Update test_host.py

Add test cases for:
- GROUP_UPDATE followed by TAB_OPEN with matching groupId
- TAB_GROUP_CHANGED moving a tab into and out of a group
- GROUP_REMOVE cleanup
- Rendering: verify markdown output contains group headings with emoji
- Cross-group parent-child rendering

## Open Questions

1. **Group position ordering**: Groups have a visual position in the tab strip, but `chrome.tabGroups` doesn't expose a positional index. The sketch uses `min(tab.index)` within the group as a proxy for group ordering. Is this sufficient, or should we track the first tab index more explicitly?

2. **Collapsed state**: The design decision says always list all tabs. Should the markdown indicate collapsed state at all (e.g., in the heading)? Something like `### 🔵 Research (collapsed)` could be informative without hiding tabs.

3. **Backward compat of state.json**: The sketch handles loading old-format state.json. Should we also version the format explicitly (e.g., `"version": 2`)?

4. **Empty groups**: Chrome allows creating an empty group briefly during drag operations. Should `GROUP_UPDATE` for a group with zero tabs be tracked, or filtered out? Leaning toward: track it, it's harmless and simplifies logic.

5. **Ungrouped tabs position**: Currently ungrouped tabs render first, then groups. Should ungrouped tabs interleave with groups based on tab index position? This would be more faithful to browser ordering but significantly more complex to render.

## Related

- `extension/background.js` — all extension event listeners
- `host/host.py` — data model, event handlers, markdown rendering
- `host/test_host.py` — test harness
- Chrome tabGroups API: `chrome.tabGroups.query()`, `onCreated`, `onUpdated`, `onRemoved`
- Chrome tabs API: `tab.groupId` field, `changeInfo.groupId` in `onUpdated`
