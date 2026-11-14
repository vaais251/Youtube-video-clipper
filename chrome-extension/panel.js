import { clock, parseTime, filenameError, bound } from "./timeline.js";

const $ = (id) => document.getElementById(id);
const track = $("timeline");
const startHandle = $("start-handle");
const endHandle = $("end-handle");
const startField = $("start-time");
const endField = $("end-time");
const nameField = $("clip-name");
const download = $("download");
let tabId = null;
let video = null;
let duration = 0;
let position = 0;
let selection = { start: 0, end: 0 };
let view = { start: 0, span: 0 };
let clips = [];
let editing = null;
let drag = null;
let port = null;
let helperReady = false;
let hostConnected = false;
let job = null;
let starting = false;
let previewing = false;
let polling = false;

function error(id, message = "") {
  const field = $(id);
  field.textContent = message;
  field.hidden = !message;
}

function controls() {
  const busy = starting || ["running", "cancelling"].includes(job?.phase);
  $("full").disabled = !duration;
  $("folder").disabled = !hostConnected;
  download.disabled = !helperReady || !duration || busy || !(clips.length || $("full").checked);
  const count = clips.length + Number($("full").checked);
  download.textContent = count ? `Download ${count} ${count === 1 ? "MP4" : "MP4s"}` : "Download MP4s";
}

function list(id, entries) {
  $(id).replaceChildren(...entries.map((entry) => {
    const item = document.createElement("li");
    item.textContent = entry;
    return item;
  }));
}

function showJob(value) {
  job = value;
  starting = false;
  $("activity").hidden = !value;
  if (value) {
    $("job-status").textContent = `${value.title ? `${value.title} · ` : ""}${value.status}`;
    $("job-progress").hidden = !["running", "cancelling"].includes(value.phase);
    $("cancel").hidden = $("job-progress").hidden;
    $("cancel").disabled = value.phase === "cancelling";
    const percent = value.status.match(/(\d+(?:\.\d+)?)%\s*$/);
    if (percent) {
      $("job-progress").max = 100;
      $("job-progress").value = bound(Number(percent[1]), 0, 100);
    } else $("job-progress").removeAttribute("value");
    list("job-files", value.files);
    list("job-warnings", value.warnings);
  }
  controls();
}

function request(message) {
  if (!port) {
    connect();
    if (!port) return false;
  }
  try { port.postMessage(message); return true; }
  catch { error("notice", "Chrome lost the connection. Reconnect and try again."); return false; }
}

function health(response) {
  hostConnected = Boolean(response.output && !response.error);
  const missing = response.missing || [];
  helperReady = hostConnected && missing.length === 0;
  const status = $("connection");
  status.textContent = helperReady ? "Helper ready" : "Setup needed";
  status.classList.toggle("ready", helperReady);
  $("helper").hidden = helperReady;
  $("helper-message").textContent = response.error ||
    (missing.length ? `Missing ${missing.join(", ")}. Open Start Downloader.cmd and click Set up tools, then reconnect.` : "");
  if (response.output) $("folder").title = response.output;
  controls();
}

function connect() {
  try { port = chrome.runtime.connect({ name: "clip-panel" }); }
  catch { health({ error: "Could not connect to the Chrome extension. Reload it from chrome://extensions." }); return; }
  port.onDisconnect.addListener(() => {
    void chrome.runtime.lastError;
    port = null;
    if (starting) {
      starting = false;
      error("notice", "Chrome disconnected before the export started.");
    }
    health({ error: "Chrome disconnected. Reconnect to check the export and helper." });
  });
  port.onMessage.addListener((message) => {
    if (message.type === "health") health(message);
    if (message.type === "job") showJob(message.job);
    if (message.type === "folder" && message.error) error("notice", message.error);
    if (message.type === "notice") {
      starting = false;
      error("notice", message.error);
      controls();
    }
  });
  request({ type: "ping" });
}

function playerCommand(type, data = {}) {
  if (!video || tabId === null) return;
  return chrome.tabs.sendMessage(tabId, { type, videoId: video.id, ...data }).then((reply) => {
    if (reply?.error) error("editor-error", reply.error);
    return reply;
  }).catch(() => {
    error("editor-error", "The YouTube player is unavailable. Return to the video and try again.");
  });
}

function storageKey(id) { return `clipDraft:${id}`; }

function storeDraft() {
  if (!video || !duration) return;
  const key = storageKey(video.id);
  const draft = { clips, full: $("full").checked, quality: $("quality").value };
  chrome.storage.local.set({ [key]: draft }).catch(() => {
    error("notice", "Chrome could not save your clip list. Keep the panel open until you export it.");
  });
}

function renderQueue() {
  $("queue-count").textContent = clips.length;
  $("queue-empty").hidden = !!clips.length;
  $("queue-list").replaceChildren(...clips.map((clip, index) => {
    const item = document.createElement("li");
    item.classList.toggle("editing", editing === index);
    const edit = document.createElement("button");
    edit.className = "clip-info";
    edit.type = "button";
    edit.textContent = clip.name || `Clip ${index + 1}`;
    edit.title = "Edit this clip";
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = `${clock(clip.start)} – ${clock(clip.end)} · ${clock(clip.end - clip.start)} long`;
    edit.append(time);
    edit.onclick = () => {
      editing = index;
      selection = { start: clip.start, end: clip.end };
      nameField.value = clip.name;
      if (selection.start < view.start || selection.end > view.start + view.span) {
        view.span = Math.min(duration, Math.max(view.span, selection.end - selection.start));
        center((selection.start + selection.end) / 2);
      }
      error("editor-error");
      renderQueue();
      renderEditor(true);
      nameField.focus();
    };
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${clip.name || `clip ${index + 1}`}`);
    remove.onclick = () => {
      clips = clips.filter((_, offset) => index !== offset);
      if (editing === index) resetEditor();
      else if (editing !== null && editing > index) editing -= 1;
      storeDraft();
      renderQueue();
      renderEditor();
      controls();
    };
    item.append(edit, remove);
    return item;
  }));
}

function left(time) { return (time - view.start) / view.span * 100; }

function drawInterval(element, start, end) {
  const first = Math.max(start, view.start);
  const last = Math.min(end, view.start + view.span);
  element.hidden = last < first;
  element.style.left = `${left(first)}%`;
  element.style.width = `${100 * Math.max(0, last - first) / view.span}%`;
}

function drawPlayhead() {
  if (!duration) return;
  $("playhead").hidden = position < view.start || position > view.start + view.span;
  $("playhead").style.left = `${left(position)}%`;
  $("playhead-time").textContent = clock(position, false);
}

function renderEditor(force = false) {
  if (!duration) return;
  $("length").textContent = clock(selection.end - selection.start);
  if (force || document.activeElement !== startField) startField.value = clock(selection.start);
  if (force || document.activeElement !== endField) endField.value = clock(selection.end);
  $("commit").textContent = editing === null ? "Add clip" : "Save changes";
  $("discard").hidden = editing === null;
  drawInterval($("selected-range"), selection.start, selection.end);
  $("saved-ranges").replaceChildren(...clips.map((clip) => {
    const marker = document.createElement("i");
    drawInterval(marker, clip.start, clip.end);
    return marker;
  }));
  for (const [handle, edge] of [[startHandle, "start"], [endHandle, "end"]]) {
    const value = selection[edge];
    const percentage = left(value);
    handle.hidden = percentage < 0 || percentage > 100;
    handle.style.left = `${percentage}%`;
    handle.setAttribute("aria-valuemax", edge === "start" ? selection.end : duration);
    handle.setAttribute("aria-valuemin", edge === "start" ? 0 : selection.start);
    handle.setAttribute("aria-valuenow", value);
    handle.setAttribute("aria-valuetext", clock(value));
  }
  $("ruler").replaceChildren(...[0, .25, .5, .75, 1].map((fraction) => {
    const mark = document.createElement("span");
    mark.textContent = clock(Math.round(view.start + fraction * view.span), view.span < 7000);
    return mark;
  }));
  $("pan-field").hidden = view.span >= duration;
  $("pan").max = duration - view.span;
  $("pan").value = view.start;
  $("zoom-in").disabled = view.span <= 2000;
  $("zoom-out").disabled = view.span >= duration;
  $("zoom-reset").disabled = view.span >= duration;
  drawPlayhead();
}

function center(time) { view.start = bound(Math.round(time - view.span / 2), 0, duration - view.span); }

function resetEditor() {
  editing = null;
  nameField.value = "";
  const start = Math.min(position, Math.max(0, duration - Math.min(5000, duration)));
  selection = { start, end: Math.min(duration, start + 5000) };
}

function setSelection(edge, value, shiftOther = false) {
  const maximum = duration;
  value = bound(value, 0, maximum);
  if (edge === "start") {
    if (shiftOther && value >= selection.end) selection.end = Math.min(maximum, value + 5000);
    selection.start = Math.min(value, selection.end - 1);
  } else {
    if (shiftOther && value <= selection.start) selection.start = Math.max(0, value - 5000);
    selection.end = Math.max(value, selection.start + 1);
  }
  error("editor-error");
  renderEditor(true);
}

function readFields() {
  const start = parseTime(startField.value);
  const end = parseTime(endField.value);
  if (start === null || end === null || start >= end || end > duration) {
    error("editor-error", "Enter a start before the end. Both times must be within the video.");
    return false;
  }
  selection = { start, end };
  error("editor-error");
  renderEditor(true);
  return true;
}

function commitClip() {
  if (!readFields()) return;
  const name = nameField.value.trim();
  const invalid = filenameError(name);
  if (invalid) { error("editor-error", invalid); nameField.focus(); return; }
  const clip = { ...selection, name };
  if (editing === null) clips = [...clips, clip];
  else clips = clips.map((item, index) => index === editing ? clip : item);
  editing = null;
  nameField.value = "";
  storeDraft();
  renderQueue();
  renderEditor(true);
  controls();
}

function pointerTime(event) {
  const rect = track.getBoundingClientRect();
  const portion = bound((event.clientX - rect.left) / rect.width, 0, 1);
  return Math.round(view.start + portion * view.span);
}

track.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || !duration || drag) return;
  const edge = event.target === startHandle ? "start" : event.target === endHandle ? "end" : null;
  drag = { edge, x: event.clientX, at: pointerTime(event), id: event.pointerId };
  track.setPointerCapture(event.pointerId);
});
track.addEventListener("pointermove", (event) => {
  if (drag?.id !== event.pointerId) return;
  const at = pointerTime(event);
  if (drag.edge) setSelection(drag.edge, at);
  else if (drag.moved || Math.abs(event.clientX - drag.x) >= 4) {
    drag.moved = true;
    selection = { start: Math.min(at, drag.at, duration - 1), end: Math.max(at, drag.at) };
    selection.end = Math.max(selection.end, selection.start + 1);
    error("editor-error");
    renderEditor(true);
  }
});
track.addEventListener("pointerup", (event) => {
  if (drag?.id !== event.pointerId) return;
  if (!drag.edge && !drag.moved) playerCommand("seekPlayer", { start: pointerTime(event) / 1000 });
  drag = null;
});
track.addEventListener("lostpointercapture", () => { drag = null; });

for (const [handle, edge] of [[startHandle, "start"], [endHandle, "end"]]) {
  handle.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 1000 : 100;
    const actions = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step };
    if (!Object.hasOwn(actions, event.key)) return;
    event.preventDefault();
    setSelection(edge, selection[edge] + actions[event.key]);
    if (selection[edge] < view.start || selection[edge] > view.start + view.span) {
      center(selection[edge]);
      renderEditor();
      handle.focus();
    }
  });
}

function zoom(multiplier) {
  const pivot = position >= view.start && position <= view.start + view.span ? position : (selection.start + selection.end) / 2;
  view.span = bound(Math.round(view.span * multiplier), Math.min(2000, duration), duration);
  center(pivot);
  renderEditor();
}

$("zoom-in").onclick = () => zoom(.5);
$("zoom-out").onclick = () => zoom(2);
$("zoom-reset").onclick = () => { view = { start: 0, span: duration }; renderEditor(); };
$("current").onclick = () => { center(position); renderEditor(); };
$("pan").oninput = (event) => { view.start = Number(event.target.value); renderEditor(); };
$("mark-start").onclick = () => setSelection("start", position, true);
$("mark-end").onclick = () => setSelection("end", position, true);
$("commit").onclick = commitClip;
$("discard").onclick = () => { resetEditor(); error("editor-error"); renderQueue(); renderEditor(true); };
$("preview").onclick = async () => {
  if (previewing) {
    await playerCommand("stopPreview");
    previewing = false;
  } else if (readFields()) {
    const reply = await playerCommand("previewPlayer", { start: selection.start / 1000, end: selection.end / 1000 });
    previewing = !!reply && !reply.error;
  }
  $("preview").textContent = previewing ? "Stop preview" : "Play selection";
};
nameField.onkeydown = (event) => { if (event.key === "Enter") commitClip(); };
$("full").onchange = () => { storeDraft(); controls(); };
$("quality").onchange = storeDraft;
$("reconnect").onclick = () => {
  error("notice");
  $("connection").textContent = "Checking helper";
  if (port) request({ type: "ping" });
  else connect();
};
$("folder").onclick = () => request({ type: "openFolder" });
$("cancel").onclick = () => request({ type: "cancel" });
download.onclick = () => {
  if (!video || download.disabled) return;
  if (editing !== null) { error("notice", "Save or cancel the clip edit before downloading."); return; }
  error("notice");
  starting = request({ type: "export", videoId: video.id, title: video.title, clips,
    quality: $("quality").value, includeFull: $("full").checked });
  controls();
};

async function getPlayer(tab) {
  if (!tab?.id || !/^https:\/\/(www|m|music)\.youtube\.com\//.test(tab.url || "")) return null;
  try { return await chrome.tabs.sendMessage(tab.id, { type: "readPlayer" }); }
  catch {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["video.js"] });
      return await chrome.tabs.sendMessage(tab.id, { type: "readPlayer" });
    } catch { return null; }
  }
}

async function watch() {
  if (polling) return;
  polling = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const current = await getPlayer(tab);
    const freshDuration = Math.floor((current?.duration || 0) * 1000);
    const changed = current?.id !== video?.id || tab?.id !== tabId;
    if (changed) {
      video = current;
      tabId = tab?.id ?? null;
      duration = 0;
      drag = null;
      previewing = false;
      clips = [];
      $("full").checked = false;
      error("editor-error");
      if (current) {
        const key = storageKey(current.id);
        const saved = (await chrome.storage.local.get(key))[key];
        clips = saved?.clips || [];
        $("full").checked = !!saved?.full;
        $("quality").value = saved?.quality || "Up to 1080p";
      }
    }
    if (current && freshDuration && (!duration || changed)) {
      duration = freshDuration;
      position = bound(Math.round((current.current || 0) * 1000), 0, duration);
      view = { start: 0, span: duration };
      resetEditor();
      renderQueue();
      renderEditor(true);
    }
    if (current) {
      video = current;
      if (current.current !== null && !current.ad) position = bound(Math.round(current.current * 1000), 0, duration);
      previewing = Boolean(current.previewing);
      $("preview").textContent = previewing ? "Stop preview" : "Play selection";
      drawPlayhead();
    }
    $("editor").hidden = !duration;
    $("queue").hidden = !duration;
    $("mark-start").disabled = !freshDuration;
    $("mark-end").disabled = !freshDuration;
    $("preview").disabled = !freshDuration;
    $("video-title").textContent = current?.title || "Open a YouTube video";
    $("video-note").textContent = !current ? "Switch to a video or Short in this Chrome window to start clipping." :
      current.ad ? "The timeline will sync after the ad." : duration ? `${clock(duration, false)} total` :
      "Waiting for a video with a fixed duration. Start playback or open the finished replay.";
    controls();
  } catch {
    error("notice", "The active YouTube video could not be read. Reopen the panel and try again.");
  } finally {
    polling = false;
  }
}

connect();
watch();
chrome.tabs.onActivated.addListener(watch);
chrome.tabs.onUpdated.addListener((_, change) => { if (change.url || change.status === "complete") watch(); });
setInterval(watch, 400);
