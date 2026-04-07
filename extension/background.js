// Browser Tab Tree — MV3 service worker
// Phase 4: TAB_OPEN, TAB_CLOSE, TAB_NAVIGATE with URL filtering

const HOST_NAME = "com.browser_tab_tree";

let port = null;

function ensurePort() {
  if (!port) {
    port = chrome.runtime.connectNative(HOST_NAME);
    port.onMessage.addListener(enqueueCommand);
    port.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError;
      console.error(`[BrowserTabTree] Host disconnected: ${err ? err.message : "unknown reason"}`);
      port = null;
    });
  }
  return port;
}

// --- Command handler (messages FROM host) ---
// Commands are queued and executed sequentially so async Chrome API calls
// don't race each other (e.g. ungroup must finish before group).

const cmdQueue = [];
let cmdRunning = false;

function enqueueCommand(msg) {
  if (!msg.command) return;
  cmdQueue.push(msg);
  drainQueue();
}

async function drainQueue() {
  if (cmdRunning) return;
  cmdRunning = true;
  while (cmdQueue.length > 0) {
    const msg = cmdQueue.shift();
    await handleCommand(msg);
  }
  cmdRunning = false;
}

async function handleCommand(msg) {
  console.log("[BrowserTabTree] Command received:", msg);
  try {
    if (msg.command === "group_tabs") {
      const groupId = await chrome.tabs.group({
        tabIds: msg.tabIds,
        createProperties: msg.windowId ? { windowId: msg.windowId } : undefined,
      });
      if (msg.title || msg.color) {
        await chrome.tabGroups.update(groupId, {
          ...(msg.title && { title: msg.title }),
          ...(msg.color && { color: msg.color }),
        });
      }
      console.log("[BrowserTabTree] Grouped tabs, groupId:", groupId);
    } else if (msg.command === "move_tab") {
      await chrome.tabs.move(msg.tabId, { index: msg.index, ...(msg.windowId && { windowId: msg.windowId }) });
    } else if (msg.command === "close_tab") {
      await chrome.tabs.remove(msg.tabId);
    } else if (msg.command === "ungroup_tabs") {
      await chrome.tabs.ungroup(msg.tabIds);
    } else if (msg.command === "restore_session") {
      await restoreSession(msg.windows);
    }
  } catch (e) {
    console.error("[BrowserTabTree] Command error:", e);
  }
}

function waitForTabLoading(tabId, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(); // proceed even on timeout
    }, timeoutMs);
    function listener(id, changeInfo) {
      if (id === tabId && changeInfo.status === "loading") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function restoreSession(windows) {
  console.log(`[BrowserTabTree] Restoring ${windows.length} windows`);
  for (const win of windows) {
    const newWin = await chrome.windows.create({ focused: false });
    const windowId = newWin.id;
    // Track the auto-created newtab so we can close it after
    const autoTabId = newWin.tabs?.[0]?.id;

    console.log(`[BrowserTabTree] Window created (id=${windowId}), restoring ${win.tabs.length} tabs`);

    // Build index of which tabs belong to which group
    const tabToGroup = new Map();
    for (const group of (win.groups || [])) {
      for (const idx of group.tabIndices) {
        tabToGroup.set(idx, group);
      }
    }

    // Process tabs group-by-group: create → group → discard, then next batch
    // Ungrouped tabs first, then each group in order
    const createdTabIds = new Array(win.tabs.length).fill(null);

    // Helper: create a batch of tabs, optionally group them, then discard
    async function createBatch(indices, group) {
      const batchIds = [];
      for (const idx of indices) {
        const tabDef = win.tabs[idx];
        if (!tabDef.url || tabDef.url.startsWith("chrome://")) continue;
        const tab = await chrome.tabs.create({
          url: tabDef.url,
          active: false,
          windowId,
        });
        await waitForTabLoading(tab.id);
        createdTabIds[idx] = tab.id;
        batchIds.push(tab.id);
      }
      if (batchIds.length === 0) return;

      // Group if needed
      if (group) {
        const groupId = await chrome.tabs.group({
          tabIds: batchIds,
          createProperties: { windowId },
        });
        await chrome.tabGroups.update(groupId, {
          ...(group.title && { title: group.title }),
          ...(group.color && { color: group.color }),
        });
        console.log(`[BrowserTabTree] Group "${group.title}" (${group.color}) with ${batchIds.length} tabs`);
      }

      // Discard this batch immediately
      for (const tabId of batchIds) {
        try {
          await chrome.tabs.discard(tabId);
        } catch (e) {
          console.warn(`[BrowserTabTree] Could not discard tab ${tabId}: ${e.message}`);
        }
      }
    }

    // Find ungrouped tab indices
    const ungroupedIndices = [];
    for (let i = 0; i < win.tabs.length; i++) {
      if (!tabToGroup.has(i)) ungroupedIndices.push(i);
    }
    await createBatch(ungroupedIndices, null);

    // Process each group
    for (const group of (win.groups || [])) {
      await createBatch(group.tabIndices, group);
    }

    // Close the auto-created newtab
    if (autoTabId) {
      try {
        await chrome.tabs.remove(autoTabId);
      } catch (_) {}
    }

    console.log(`[BrowserTabTree] Window ${windowId} done`);
  }
  console.log("[BrowserTabTree] Session restore complete");
}

function send(event) {
  try {
    ensurePort().postMessage(event);
  } catch (e) {
    port = null;
  }
}

function now() {
  return new Date().toISOString();
}

// --- Event listeners ---

chrome.tabs.onCreated.addListener((tab) => {
  const event = {
    type: "TAB_OPEN",
    ts: now(),
    tabId: tab.id,
    windowId: tab.windowId,
    index: tab.index,
    url: tab.pendingUrl || tab.url || "",
    title: tab.title || "",
    groupId: tab.groupId,
  };
  if (tab.openerTabId != null) {
    const url = tab.pendingUrl || tab.url || "";
    if (url && !url.startsWith("chrome://newtab")) {
      event.openerTabId = tab.openerTabId;
    }
  }
  send(event);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  send({
    type: "TAB_CLOSE",
    ts: now(),
    tabId: tabId,
  });
});

// URL filter: only allow http/https URLs (skip chrome://, about:, etc.)
function isNavigableUrl(url) {
  if (!url) return false;
  return url.startsWith("http://") || url.startsWith("https://");
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.groupId !== undefined) {
    send({
      type: "TAB_GROUP_CHANGED",
      ts: now(),
      tabId: tabId,
      groupId: changeInfo.groupId,
    });
  }
  if (changeInfo.url && isNavigableUrl(changeInfo.url)) {
    send({
      type: "TAB_NAVIGATE",
      ts: now(),
      tabId: tabId,
      url: changeInfo.url,
      title: tab.title || "",
    });
  }
});

// --- Tab group listeners ---

chrome.tabGroups.onCreated.addListener((group) => {
  send({
    type: "GROUP_UPDATE",
    ts: now(),
    groupId: group.id,
    windowId: group.windowId,
    title: group.title,
    color: group.color,
    collapsed: group.collapsed,
  });
});

chrome.tabGroups.onUpdated.addListener((group) => {
  send({
    type: "GROUP_UPDATE",
    ts: now(),
    groupId: group.id,
    windowId: group.windowId,
    title: group.title,
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

chrome.tabs.onMoved.addListener((tabId, moveInfo) => {
  send({
    type: "TAB_MOVE",
    ts: now(),
    tabId: tabId,
    windowId: moveInfo.windowId || undefined,
    index: moveInfo.toIndex,
  });
});

chrome.tabs.onAttached.addListener((tabId, attachInfo) => {
  send({
    type: "TAB_MOVE",
    ts: now(),
    tabId: tabId,
    windowId: attachInfo.newWindowId,
    index: attachInfo.newPosition,
  });
});

// --- Startup: sync all existing groups and tabs ---

async function syncExistingGroups() {
  const allGroups = await chrome.tabGroups.query({});
  for (const group of allGroups) {
    send({
      type: "GROUP_UPDATE",
      ts: now(),
      groupId: group.id,
      windowId: group.windowId,
      title: group.title,
      color: group.color,
      collapsed: group.collapsed,
    });
  }
}

async function syncExistingTabs() {
  const allTabs = await chrome.tabs.query({});
  for (const tab of allTabs) {
    send({
      type: "TAB_OPEN",
      ts: now(),
      tabId: tab.id,
      windowId: tab.windowId,
      index: tab.index,
      url: tab.url || "",
      title: tab.title || "",
      groupId: tab.groupId,
    });
  }
}

send({ type: "SYNC_START", ts: now() });
syncExistingGroups().then(() => syncExistingTabs());
