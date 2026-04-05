// Browser Tab Tree — MV3 service worker
// Phase 2: TAB_OPEN and TAB_CLOSE only (flat list, no openerTabId)

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
  send({
    type: "TAB_OPEN",
    ts: now(),
    tabId: tab.id,
    windowId: tab.windowId,
    url: tab.pendingUrl || tab.url || "",
    title: tab.title || "",
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  send({
    type: "TAB_CLOSE",
    ts: now(),
    tabId: tabId,
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
