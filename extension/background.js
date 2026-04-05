// Browser Tab Tree — MV3 service worker
// Phase 4: TAB_OPEN, TAB_CLOSE, TAB_NAVIGATE with URL filtering

const HOST_NAME = "com.browser_tab_tree";

let port = null;

function ensurePort() {
  if (!port) {
    port = chrome.runtime.connectNative(HOST_NAME);
    port.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError;
      console.error(`[BrowserTabTree] Host disconnected: ${err ? err.message : "unknown reason"}`);
      port = null;
    });
  }
  return port;
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
