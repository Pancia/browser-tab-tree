// Browser Tab Tree — MV3 service worker
// Phase 4: TAB_OPEN, TAB_CLOSE, TAB_NAVIGATE with URL filtering

const HOST_NAME = "com.browser_tab_tree";

let port = null;

function ensurePort() {
  if (!port) {
    port = chrome.runtime.connectNative(HOST_NAME);
    port.onDisconnect.addListener(() => {
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
    url: tab.pendingUrl || tab.url || "",
    title: tab.title || "",
  };
  if (tab.openerTabId != null) {
    event.openerTabId = tab.openerTabId;
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
  if (!changeInfo.url) return;
  if (!isNavigableUrl(changeInfo.url)) return;
  send({
    type: "TAB_NAVIGATE",
    ts: now(),
    tabId: tabId,
    url: changeInfo.url,
    title: tab.title || "",
  });
});

// --- Startup: sync all existing tabs ---

async function syncExistingTabs() {
  const allTabs = await chrome.tabs.query({});
  for (const tab of allTabs) {
    send({
      type: "TAB_OPEN",
      ts: now(),
      tabId: tab.id,
      windowId: tab.windowId,
      url: tab.url || "",
      title: tab.title || "",
    });
  }
}

syncExistingTabs();
