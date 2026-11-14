const HOST = "com.vaais.youtube_clip_downloader";
const JOB_KEY = "clipExportJob";
const panels = new Set();
let running = null;
let snapshot = null;

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
});
chrome.runtime.onStartup.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
});

function tell(panel, message) {
  try { panel.postMessage(message); } catch { panels.delete(panel); }
}

function update(changes, persist = false) {
  snapshot = { ...snapshot, ...changes };
  for (const panel of panels) tell(panel, { type: "job", job: snapshot });
  if (persist) chrome.storage.session.set({ [JOB_KEY]: snapshot }).catch(console.error);
}

function hostError(message) {
  return /not found|forbidden|access|failed to start/i.test(message || "")
    ? "Chrome cannot connect to the Windows helper. Run Install Chrome Helper.cmd, then reconnect."
    : message || "The Windows helper disconnected. Check the output folder for any completed files.";
}

function requestHost(panel, request) {
  try {
    chrome.runtime.sendNativeMessage(HOST, request, (answer) => {
      const error = chrome.runtime.lastError?.message;
      const type = request.type === "ping" ? "health" : "folder";
      tell(panel, { type, ...(error ? { error: hostError(error) } :
        answer || { error: "The Windows helper returned an empty response." }) });
    });
  } catch (error) {
    tell(panel, { type: request.type === "ping" ? "health" : "folder", error: hostError(error.message) });
  }
}

function start(request, panel) {
  if (running) {
    tell(panel, { type: "notice", error: "An export is already running. Wait for it to finish or cancel it first." });
    return;
  }
  let native;
  try { native = chrome.runtime.connectNative(HOST); }
  catch (error) {
    tell(panel, { type: "notice", error: hostError(error.message) });
    return;
  }
  running = native;
  snapshot = { videoId: request.videoId, title: request.title, files: [], warnings: [], phase: "running" };
  update({ status: "Preparing export…" }, true);
  native.onMessage.addListener((event) => {
    if (running !== native) return;
    if (event.kind === "status" && snapshot.phase !== "cancelling") update({ status: event.message });
    else if (event.kind === "file") update({ files: [...snapshot.files, event.message] }, true);
    else if (event.kind === "log") update({ warnings: [...snapshot.warnings, event.message].slice(-35) }, true);
    else if (event.kind === "result") {
      running = null;
      const status = `${event.saved} ${event.saved === 1 ? "file" : "files"} saved`;
      const failureCount = event.failed ? ` · ${event.failed} failed` : "";
      update({ phase: event.failed ? "partial" : "done", status: status + failureCount }, true);
      native.disconnect();
    } else if (event.kind === "error" || event.kind === "cancelled") {
      running = null;
      update({ phase: event.kind === "error" ? "failed" : "cancelled", status: event.message }, true);
      native.disconnect();
    }
  });
  native.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError?.message;
    if (running !== native) return;
    running = null;
    update({ phase: "failed", status: hostError(error) }, true);
  });
  try { native.postMessage({ ...request, type: "start" }); }
  catch (error) {
    running = null;
    update({ phase: "failed", status: hostError(error.message) }, true);
    native.disconnect();
  }
}

chrome.runtime.onConnect.addListener((panel) => {
  if (panel.name !== "clip-panel" || panel.sender?.url !== chrome.runtime.getURL("panel.html")) return;
  panels.add(panel);
  panel.onDisconnect.addListener(() => panels.delete(panel));
  if (snapshot) tell(panel, { type: "job", job: snapshot });
  else chrome.storage.session.get(JOB_KEY).then((data) => {
    if (snapshot || !data[JOB_KEY]) return;
    snapshot = data[JOB_KEY];
    if (["running", "cancelling"].includes(snapshot.phase)) {
      update({ phase: "failed", status: "Chrome stopped the export. Completed files are still available." }, true);
    } else tell(panel, { type: "job", job: snapshot });
  }).catch(console.error);

  panel.onMessage.addListener((request) => {
    if (["ping", "openFolder"].includes(request.type)) requestHost(panel, request);
    if (request.type === "export") start(request, panel);
    if (request.type === "cancel" && running) {
      update({ phase: "cancelling", status: "Cancelling export…" });
      try { running.postMessage({ type: "cancel" }); } catch { /* onDisconnect reports the error */ }
    }
  });
});
