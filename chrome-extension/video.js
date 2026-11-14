(() => {
  if (globalThis.clipDownloaderPlayer) return;
  globalThis.clipDownloaderPlayer = true;
  let preview = null;

  function videoId() {
    const path = location.pathname.split("/");
    const id = location.pathname === "/watch" ? new URLSearchParams(location.search).get("v") :
      ["shorts", "live"].includes(path[1]) ? path[2] : null;
    return /^[\w-]{11}$/.test(id || "") ? id : null;
  }

  function player() {
    const short = document.querySelector("ytd-reel-video-renderer[is-active] video");
    return short || document.querySelector("#movie_player video.html5-main-video, video.video-stream");
  }

  function isAd(video) {
    return Boolean(video?.closest(".ad-showing, .ad-interrupting"));
  }

  function stopPreview(pause = false) {
    if (!preview) return;
    clearInterval(preview.timer);
    if (pause) preview.video.pause();
    preview = null;
  }

  function read() {
    const id = videoId();
    if (!id) return null;
    const video = player();
    const ad = isAd(video);
    const title = document.querySelector('meta[name="title"]')?.content;
    const documentTitle = document.title.replace(/\s+- YouTube(?: Music)?$/, "");
    const shortsTitle = document.querySelector("ytd-reel-video-renderer[is-active] h2")?.textContent?.trim();
    return { id, ad, title: shortsTitle || documentTitle || title || "YouTube video",
      previewing: Boolean(preview && preview.video === video && !video.paused),
      duration: !ad && Number.isFinite(video?.duration) ? video.duration : null,
      current: !ad && Number.isFinite(video?.currentTime) ? video.currentTime : null };
  }

  chrome.runtime.onMessage.addListener((request, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return;
    if (request.type === "readPlayer") {
      respond(read());
      return;
    }
    if (!["seekPlayer", "previewPlayer", "stopPreview"].includes(request.type)) return;
    const state = read();
    const video = player();
    if (!state || state.id !== request.videoId || !video) {
      respond({ error: "The video changed. Open it again before previewing." });
      return;
    }
    if (request.type === "stopPreview") {
      stopPreview(true);
      respond({});
      return;
    }
    if (!state.duration || state.ad) {
      respond({ error: "Wait for the YouTube video to load before seeking." });
      return;
    }
    if (!Number.isFinite(request.start)) {
      respond({ error: "Choose a valid point on the timeline." });
      return;
    }
    if (request.type === "previewPlayer" && (!Number.isFinite(request.end) || request.end <= request.start)) {
      respond({ error: "Choose a clip end after its start." });
      return;
    }
    stopPreview(request.type === "seekPlayer");
    video.currentTime = Math.max(0, Math.min(state.duration, request.start));
    if (request.type === "seekPlayer") {
      respond({});
      return;
    }
    const end = Math.min(state.duration, request.end);
    video.play().then(() => {
      if (videoId() !== state.id || player() !== video) {
        respond({ error: "The video changed while opening the preview." });
        return;
      }
      stopPreview();
      preview = { video, timer: setInterval(() => {
        if (videoId() !== state.id || player() !== video || isAd(video)) stopPreview();
        else if (video.currentTime >= end || video.ended) stopPreview(true);
      }, 50) };
      respond({});
    }).catch(() => respond({ error: "Start playback on YouTube, then try Preview again." }));
    return true;
  });
})();
