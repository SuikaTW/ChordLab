const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  jobs: [],
  jobsExpanded: false,
  current: null,
  currentPublic: false,
  viewer: null,
  method: "chordino",
  track: "original",
  tracks: [],
  volume: 1,
  audioContext: null,
  masterGain: null,
  primarySource: null,
  audioGraphFailed: false,
  sourceRequest: 0,
  sourceLoading: false,
  resumeOnLoad: false,
  mixTimer: null,
  resumeAfterMix: false,
  capo: 0,
  selected: -1,
  poller: null,
  openRequest: 0,
  tabJob: null,
  tabNotes: [],
  tabSource: "unavailable",
  tabDensity: "clean",
  page: "workspace",
  resultView: "chords",
  librarySort: "recent",
  libraryTimer: null,
};
const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const TUNING = [40, 45, 50, 55, 59, 64];
const TRACK_NAMES = {
  original: "原曲",
  harmony: "和聲伴奏",
  other: "其他樂器",
  vocals: "人聲",
  bass: "Bass",
  drums: "鼓",
  guitar: "吉他",
  piano: "鋼琴",
};
state.tabWorker = null;
state.tabCancel = null;

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(node.timer);
  node.timer = setTimeout(() => node.className = "toast", 3200);
}
function durationText(seconds) {
  if (seconds === undefined || seconds === null || !Number.isFinite(Number(seconds))) return "—";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    location.href = "/login";
    throw new Error("請重新登入");
  }
  if (!response.ok) {
    let detail = "操作失敗";
    try {
      const data = await response.json();
      detail = typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
        ? data.detail.slice(0, 2).map((error) => error.msg).join("；")
        : detail;
    } catch {}
    throw new Error(detail);
  }
  return response.headers.get("content-type")?.includes("json") ? response.json() : response;
}

async function init() {
  const savedVolume = localStorage.getItem("chordlab:volume"), parsedVolume = Number(savedVolume);
  state.volume = savedVolume !== null && Number.isFinite(parsedVolume)
    ? Math.min(1, Math.max(0, parsedVolume))
    : 1;
  $("#volumeSlider").value = String(state.volume);
  updateVolumeLabel();
  try {
    state.viewer = await api("/api/me");
    $("#adminNav").classList.toggle("hidden", !state.viewer.admin);
  } catch {}
  bindEvents();
  await Promise.all([loadJobs(), loadQueueStatus()]);
  setInterval(loadQueueStatus, 10000);
}

function bindEvents() {
  TabStudio.bind();
  $("#analysisPreset").addEventListener("change", applyAnalysisPreset);
  applyAnalysisPreset();
  const methodDetails = document.createElement("details");
  methodDetails.className = "method-options";
  const methodSummary = document.createElement("summary");
  methodSummary.textContent = "辨識方式";
  methodDetails.append(methodSummary, $(".method-switch"));
  $(".method-row").append(methodDetails);
  $("#lyricsList").addEventListener("wheel", () => state.lyricTouched = performance.now(), { passive: true });
  $("#lyricsList").addEventListener("touchstart", () => state.lyricTouched = performance.now(), {
    passive: true,
  });
  $$(".tab").forEach((button) =>
    button.addEventListener("click", () => {
      $$(".tab").forEach((x) => x.classList.toggle("active", x === button));
      const file = button.dataset.tab === "file";
      $(".source-url").classList.toggle("hidden", file);
      $(".source-file").classList.toggle("hidden", !file);
      $(".source-url input").disabled = file;
      $(".source-file input").disabled = !file;
    })
  );
  $(".source-file input").disabled = true;
  $("#dropZone input").addEventListener(
    "change",
    (event) =>
      $("#fileName").textContent = event.target.files[0]?.name || "MP3 / WAV / FLAC / M4A，最多 200 MB",
  );
  ["dragenter", "dragover"].forEach((name) =>
    $("#dropZone").addEventListener(name, (event) => {
      event.preventDefault();
      event.currentTarget.classList.add("drag");
    })
  );
  ["dragleave", "drop"].forEach((name) =>
    $("#dropZone").addEventListener(name, (event) => event.currentTarget.classList.remove("drag"))
  );
  $("#importForm").addEventListener("submit", createJob);
  $("#refreshJobs").addEventListener("click", loadJobs);
  $$("[data-page]").forEach((button) =>
    button.addEventListener("click", (event) => {
      event.preventDefault();
      setPage(button.dataset.page);
    })
  );
  $(".brand").addEventListener("click", (event) => {
    event.preventDefault();
    setPage("workspace");
  });
  $("#librarySearch").addEventListener("input", () => {
    clearTimeout(state.libraryTimer);
    state.libraryTimer = setTimeout(loadLibrary, 260);
  });
  $$("[data-library-sort]").forEach((button) =>
    button.addEventListener("click", () => {
      state.librarySort = button.dataset.librarySort;
      $$("[data-library-sort]").forEach((item) => item.classList.toggle("active", item === button));
      loadLibrary();
    })
  );
  $$("[data-result-view]").forEach((button) =>
    button.addEventListener("click", () => setResultView(button.dataset.resultView))
  );
  $$("[data-tab-density]").forEach((button) =>
    button.addEventListener("click", () => {
      if (!TabStudio.reconfigure()) return;
      state.tabDensity = button.dataset.tabDensity;
      $$("[data-tab-density]").forEach((item) => item.classList.toggle("active", item === button));
      renderContinuousTab();
    })
  );
  $("#tabTuning").addEventListener("change", (event) => {
    if (!TabStudio.reconfigure()) return;
    state.tabTuning = event.target.value;
    if (state.current) localStorage.setItem(`tab-tuning:${state.current.id}`, state.tabTuning);
    renderContinuousTab();
  });
  for (const [id, key] of [["tabVoice", "voice"], ["tabPosition", "position"]]) {
    $("#" + id).addEventListener("change", (event) => {
      if (!TabStudio.reconfigure()) {
        return;
      }
      if (state.current) localStorage.setItem(`tab-${key}:${state.current.id}`, event.target.value);
      renderContinuousTab();
    });
  }
  $("#showWeakTracks").addEventListener("change", () => {
    renderTrackSwitch();
    renderStemDownloads();
  });
  $("#separateStems").addEventListener("change", updateSeparationOptions);
  $("#guitarTabOnly").addEventListener("change", (event) => {
    if (event.target.checked) {
      $("#separateStems").checked = true;
      $('[name="separation_model"]').value = "htdemucs_6s";
    }
    updateSeparationOptions();
  });
  $("#pureGuitar").addEventListener("change", updateSeparationOptions);
  $('[name="separation_model"]').addEventListener("change", (event) => {
    if (event.target.value !== "htdemucs_6s") $("#guitarTabOnly").checked = false;
  });
  $$(".method-switch button").forEach((button) =>
    button.addEventListener("click", () => switchMethod(button.dataset.method))
  );
  $("#capoSelect").addEventListener("change", (event) => {
    if (!TabStudio.reconfigure()) return;
    state.capo = Number(event.target.value);
    if (state.current) {
      localStorage.setItem(`capo:${state.current.id}`, state.capo);
      renderCapo();
      renderTimeline();
      renderContinuousTab();
      if (state.selected >= 0) {
        renderVoicing(playedChord(chords()[state.selected]?.chord), chords()[state.selected]?.chord);
      }
    }
  });
  $("#segmentForm").addEventListener("submit", saveSegment);
  $("#deleteSegment").addEventListener("click", deleteSegment);
  $("#timeline").addEventListener("click", (event) => {
    const button = event.target.closest("[data-segment]");
    if (button) selectSegment(Number(button.dataset.segment), true);
  });
  $("#lyricsList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-start]");
    if (button) $("#audioPlayer").currentTime = Number(button.dataset.start);
  });
  const player = $("#audioPlayer");
  player.addEventListener("timeupdate", paintPlayback);
  for (const name of ["loadedmetadata", "durationchange", "play", "pause", "ended", "seeking"]) {
    player.addEventListener(name, paintPlayback);
  }
  player.addEventListener("play", animatePlayback);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      paintPlayback();
      animatePlayback();
    }
  });
  $("#playToggle").addEventListener("click", togglePlayback);
  $("#seekSlider").addEventListener("input", seekPlayback);
  $("#volumeSlider").addEventListener("input", setMixerVolume);
  $("#exportToggle").addEventListener("click", () => $("#exportOptions").classList.toggle("hidden"));
  $$("[data-export]").forEach((link) =>
    link.addEventListener("click", () => {
      if (state.current) {
        const suffix = link.dataset.export === "midi" ? "" : `?capo=${state.capo}`;
        location.href = `/api/jobs/${state.current.id}/export/${link.dataset.export}${suffix}`;
      }
    })
  );
  $("#playChord").remove();
  $("#visibilityToggle").addEventListener("click", toggleVisibility);
}

function setPage(page) {
  state.page = page === "library" ? "library" : "workspace";
  $("#workspacePage").classList.toggle("hidden", state.page !== "workspace");
  $("#libraryPage").classList.toggle("hidden", state.page !== "library");
  $$(".top-nav [data-page]").forEach((button) =>
    button.classList.toggle("active", button.dataset.page === state.page)
  );
  if (state.page === "library") loadLibrary();
  else {
    paintPlayback();
    animatePlayback();
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}
function setResultView(view) {
  const target = $(`[data-result-view="${view}"]`);
  if (!target || target.classList.contains("hidden")) view = "chords";
  state.resultView = view;
  $$("[data-result-view]").forEach((button) =>
    button.classList.toggle("active", button.dataset.resultView === view)
  );
  $$("[data-result-panel]").forEach((panel) =>
    panel.classList.toggle("result-hidden", panel.dataset.resultPanel !== view)
  );
  if (view === "tab") {
    loadContinuousTab();
    TabStudio.render();
    animatePlayback();
  }
  paintPlayback();
}
function revealWorkspaceOnMobile() {
  if (!window.matchMedia("(max-width: 720px)").matches) return;
  requestAnimationFrame(() => {
    const workspace = $("#workspace"), topbar = $(".topbar");
    const top = Math.max(
      0,
      window.scrollY + workspace.getBoundingClientRect().top - topbar.getBoundingClientRect().height - 8,
    );
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    window.scrollTo({ top, behavior });
  });
}
async function loadQueueStatus() {
  if (document.hidden) return;
  try {
    const queue = await api("/api/queue");
    $("#queueStatus").textContent = queue.total
      ? `處理 ${queue.working} · 等候 ${queue.waiting}`
      : "佇列空閒";
  } catch {}
}

function applyAnalysisPreset() {
  const preset = $("#analysisPreset").value;
  $("#pureGuitar").checked = preset === "pure";
  $("#separateStems").checked = ["guitar", "stems"].includes(preset);
  $("#guitarTabOnly").checked = preset === "guitar";
  $('[name="separation_model"]').value = "htdemucs_6s";
  $('[name="stem_midi"]').checked = preset === "stems";
  $("#reviewGuitar").checked = true;
  updateSeparationOptions();
}
function paintPlayback() {
  if (document.hidden) return;
  updatePlayerControls();
  if (state.page !== "workspace") return;
  if (state.resultView === "tab") updateContinuousTab();
  else if (state.resultView === "lyrics") updateLyrics();
  else markPlaying();
}
function animatePlayback() {
  if (state.playFrame) return;
  const tick = (time) => {
    state.playFrame = null;
    if (
      document.hidden || $("#audioPlayer").paused || state.page !== "workspace" || state.resultView !== "tab"
    ) return;
    if (time - (state.lastPlayPaint || 0) > 33) {
      state.lastPlayPaint = time;
      if (state.resultView === "tab") updateContinuousTab();
    }
    state.playFrame = requestAnimationFrame(tick);
  };
  state.playFrame = requestAnimationFrame(tick);
}

function updateSeparationOptions() {
  const direct = $("#pureGuitar").checked;
  if (direct) {
    $("#separateStems").checked = false;
    $("#guitarTabOnly").checked = false;
    $('[name="stem_midi"]').checked = false;
  }
  $("#separateStems").disabled = direct;
  $("#guitarTabOnly").disabled = direct;
  $('[name="stem_midi"]').disabled = direct;
  $("#separationOptions").classList.toggle("hidden", !$("#separateStems").checked);
}

async function createJob(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  button.querySelector("span").textContent = "正在送出…";
  try {
    if (!TabStudio.canLeave()) return;
    const data = new FormData(form);
    if (!data.get("url")) data.delete("url");
    if (!data.get("file")?.name) data.delete("file");
    const job = await api("/api/jobs", { method: "POST", body: data });
    form.reset();
    form.querySelector(".analysis-options").open = false;
    applyAnalysisPreset();
    $("#fileName").textContent = "MP3 / WAV / FLAC / M4A，最多 200 MB";
    await loadJobs();
    await openJob(job.id, !!job.reused, true);
    await loadQueueStatus();
    toast(job.reused ? "找到相同的公開分析，直接為你開啟" : "已加入分析佇列");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "開始分析";
  }
}

async function loadJobs() {
  try {
    state.jobs = await api("/api/jobs");
    renderJobs();
    if (!state.current && state.jobs.length) {
      const remembered = localStorage.getItem(lastJobKey());
      const target = state.jobs.find((job) => job.id === remembered) || state.jobs.find((job) => job.mine) ||
        state.jobs[0];
      await openJob(target.id);
    }
  } catch (error) {
    toast(error.message, true);
  }
}
function lastJobKey() {
  return `chordlab:last-job:${state.viewer?.key || "device"}`;
}
function renderJobs() {
  const list = $("#jobsList");
  if (!state.jobs.length) {
    list.innerHTML = '<div class="empty-small">還沒有分析紀錄</div>';
    return;
  }
  const visible = state.jobsExpanded ? state.jobs : state.jobs.slice(0, 8);
  list.innerHTML =
    visible.map((job) =>
      `<button class="job-item ${
        !state.currentPublic && state.current?.id === job.id ? "active" : ""
      }" data-job="${job.id}"><span class="job-title">${escapeHtml(job.title)}</span><span class="job-meta">${
        new Date(job.created_at * 1000).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit" })
      }${job.duration ? " · " + durationText(job.duration) : ""}${
        job.separate_stems ? " · " + (job.separation_model === "htdemucs_6s" ? "6 軌" : "4 軌") : ""
      }${job.is_public ? " · 公開" : ""}</span><span class="job-state ${job.status}">${
        job.status === "queued"
          ? `前方 ${job.ahead_count || 0} 首`
          : { working: `${job.progress}%`, done: "完成", failed: "失敗" }[job.status]
      }</span></button>`
    ).join("") + (state.jobs.length > 8
      ? `<button class="jobs-more" id="jobsMore">${
        state.jobsExpanded ? "收起" : "顯示其他 " + (state.jobs.length - 8) + " 首"
      }</button>`
      : "");
  $$("[data-job]").forEach((button) =>
    button.addEventListener("click", () => openJob(button.dataset.job, false, true))
  );
  $("#jobsMore")?.addEventListener("click", () => {
    state.jobsExpanded = !state.jobsExpanded;
    renderJobs();
  });
}

async function openJob(id, isPublic = false, reveal = false) {
  if (!TabStudio.canLeave()) return;
  TabStudio.reset(id);
  const requestId = ++state.openRequest;
  clearInterval(state.poller);
  state.poller = null;
  clearMixer();
  state.tabJob = null;
  state.tabNotes = [];
  state.tabSource = "unavailable";
  state.tabCancel?.();
  state.tabRender = (state.tabRender || 0) + 1;
  state.tabTuning = localStorage.getItem(`tab-tuning:${id}`) || "standard";
  if (!ChordLabTab.TUNINGS[state.tabTuning]) state.tabTuning = "standard";
  $("#tabTuning").value = state.tabTuning;
  $("#showWeakTracks").checked = false;
  for (const [control, key] of [["tabVoice", "voice"], ["tabPosition", "position"]]) {
    const select = $("#" + control), saved = localStorage.getItem(`tab-${key}:${id}`);
    select.value = [...select.options].some((option) => option.value === saved)
      ? saved
      : select.options[0].value;
  }
  try {
    const job = await api(
      isPublic ? `/api/public/jobs/${id}?include_notes=false` : `/api/jobs/${id}?include_notes=false`,
    );
    if (requestId !== state.openRequest) return;
    state.currentPublic = isPublic;
    state.current = job;
    if (!isPublic) localStorage.setItem(lastJobKey(), id);
    state.method = job.result?.active_method || "chordino";
    state.track = job.result?.separation?.analysis_stem || "original";
    state.tracks = [state.track];
    state.capo = Math.min(11, Math.max(0, Math.round(Number(localStorage.getItem(`capo:${id}`)) || 0)));
    state.selected = -1;
    state.resultView = "chords";
    syncCurrentJob();
    renderWorkspace();
    setResultView("chords");
    setPage("workspace");
    if (reveal) revealWorkspaceOnMobile();
    if (["queued", "working"].includes(job.status)) {
      let polling = false;
      const poller = setInterval(async () => {
        if (polling || document.hidden) return;
        polling = true;
        try {
          const update = await api(`/api/jobs/${id}?include_notes=false`);
          if (requestId !== state.openRequest) {
            clearInterval(poller);
            return;
          }
          state.current = update;
          syncCurrentJob();
          renderWorkspace();
          loadQueueStatus();
          if (!["queued", "working"].includes(update.status)) {
            clearInterval(poller);
            if (state.poller === poller) state.poller = null;
            state.track = update.result?.separation?.analysis_stem || "original";
            state.tracks = [state.track];
            renderWorkspace();
            await loadJobs();
          }
        } catch (error) {
          clearInterval(poller);
          if (state.poller === poller) state.poller = null;
          if (requestId === state.openRequest) toast(error.message, true);
        } finally {
          polling = false;
        }
      }, 1800);
      state.poller = poller;
    }
  } catch (error) {
    if (requestId === state.openRequest) toast(error.message, true);
  }
}
function syncCurrentJob() {
  if (state.currentPublic) {
    renderJobs();
    return;
  }
  const index = state.jobs.findIndex((job) => job.id === state.current.id);
  const summary = { ...state.current };
  delete summary.result;
  if (index >= 0) state.jobs[index] = summary;
  else state.jobs.unshift(summary);
  renderJobs();
}

function renderWorkspace() {
  $("#emptyWorkspace").classList.add("hidden");
  $("#activeWorkspace").classList.remove("hidden");
  $("#workTitle").textContent = state.current.title;
  $("#workMeta").textContent =
    { queued: "排隊等候", working: "正在分析", done: "分析完成", failed: "分析失敗" }[state.current.status] ||
    "音樂分析";
  $("#workMessage").textContent = state.current.status === "done" ? "" : state.current.message;
  const visibility = $("#visibilityToggle");
  visibility.classList.toggle("hidden", state.current.status !== "done" || !state.current.mine);
  visibility.classList.toggle("public", !!state.current.is_public);
  visibility.textContent = state.current.is_public ? "公開分析" : "私人分析";
  const working = ["queued", "working"].includes(state.current.status);
  $("#progressPanel").classList.toggle("hidden", !working && state.current.status !== "failed");
  $("#resultsPanel").classList.toggle("hidden", state.current.status !== "done");
  $("#progressText").textContent = state.current.status === "failed"
    ? "分析失敗"
    : state.current.status === "queued"
    ? `正在等候 · 前面還有 ${state.current.ahead_count || 0} 首`
    : state.current.message;
  $("#progressValue").textContent = state.current.status === "queued"
    ? "等候中"
    : `${state.current.progress}%`;
  $("#progressBar").style.width = state.current.status === "queued" ? "2%" : `${state.current.progress}%`;
  $("#progressHelp").textContent = state.current.status === "queued"
    ? "伺服器一次分析一首；前一首完成後會自動接續，不需要留著網頁。"
    : state.current.separate_stems
    ? `這次會先用 Demucs 做${
      state.current.separation_model === "htdemucs_6s" ? "六" : "四"
    }軌分離，再執行音符、和弦與 Key 分析。`
    : "伺服器會依序完成音訊轉換、Basic Pitch 音符辨識、Chordino 和弦與 Key 分析。";
  if (state.current.status === "done") {
    $("[data-method='ensemble']").classList.toggle("hidden", !state.current.result.methods.ensemble?.length);
    if (!state.current.result.methods[state.method]?.length) {
      state.method = state.current.result.methods.chordino.length ? "chordino" : "basic_pitch";
    }
    renderTrackSwitch();
    renderStemDownloads();
    renderCapo();
    renderLyrics();
    if (state.resultView === "tab") loadContinuousTab();
    $("#durationStat").textContent = durationText(state.current.duration);
    $("#notesStat").textContent = `${state.current.note_count || 0} notes`;
    switchMethod(state.method, false);
  }
}

async function toggleVisibility() {
  if (!state.current?.mine || state.current.status !== "done") return;
  const next = !state.current.is_public;
  try {
    const result = await api(`/api/jobs/${state.current.id}/visibility`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_public: next }),
    });
    state.current.is_public = result.is_public;
    renderWorkspace();
    await loadJobs();
    toast(next ? "已加入公開樂庫" : "已改回私人分析");
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadLibrary() {
  const grid = $("#libraryGrid");
  state.libraryController?.abort();
  const controller = new AbortController();
  state.libraryController = controller;
  if (!grid.children.length) grid.innerHTML = '<div class="library-empty">正在讀取公開分析…</div>';
  grid.setAttribute("aria-busy", "true");
  try {
    const search = encodeURIComponent($("#librarySearch").value.trim()),
      jobs = await api(`/api/public/jobs?sort=${state.librarySort}&search=${search}`, {
        signal: controller.signal,
      });
    if (state.libraryController !== controller) return;
    $("#librarySummary").textContent = search
      ? `找到 ${jobs.length} 筆公開分析`
      : `目前有 ${jobs.length} 筆公開分析`;
    if (!jobs.length) {
      grid.innerHTML =
        '<div class="library-empty">找不到符合的公開分析。你可以新增分析，完成後選擇公開。</div>';
      return;
    }
    grid.innerHTML = jobs.map((job) =>
      `<article class="library-card"><button class="library-open" data-public-job="${job.id}"><p class="eyebrow">${
        job.separate_stems
          ? (job.separation_model === "htdemucs_6s" ? "6-STEM ANALYSIS" : "4-STEM ANALYSIS")
          : "CHORD ANALYSIS"
      }</p><h2>${escapeHtml(job.title)}</h2><div class="library-card-meta"><span>${
        durationText(job.duration)
      }</span><span>${job.note_count || 0} notes</span>${
        job.transcribe_lyrics ? "<span>對時歌詞</span>" : ""
      }</div></button><div class="library-card-stats"><span>瀏覽 ${job.view_count}</span><span>收藏 ${job.favorite_count}</span><button class="library-favorite ${
        job.is_favorite ? "active" : ""
      }" data-favorite="${job.id}" aria-label="${job.is_favorite ? "取消收藏" : "收藏"}">${
        job.is_favorite ? "♥ 已收藏" : "♡ 收藏"
      }</button></div></article>`
    ).join("");
    $$("[data-public-job]").forEach((button) =>
      button.addEventListener("click", () => openJob(button.dataset.publicJob, true, true))
    );
    $$("[data-favorite]").forEach((button) =>
      button.addEventListener("click", () => toggleFavorite(button.dataset.favorite))
    );
  } catch (error) {
    if (error.name === "AbortError" || state.libraryController !== controller) return;
    grid.innerHTML = `<div class="library-empty">${escapeHtml(error.message)}</div>`;
  } finally {
    if (state.libraryController === controller) grid.setAttribute("aria-busy", "false");
  }
}
async function toggleFavorite(id) {
  try {
    await api(`/api/public/jobs/${id}/favorite`, { method: "POST" });
    await loadLibrary();
  } catch (error) {
    toast(error.message, true);
  }
}

function availableTracks() {
  const separation = state.current?.result?.separation || {};
  return $("#showWeakTracks").checked
    ? (separation.all_stems || separation.stems || ["original"])
    : (separation.stems || ["original"]);
}
function renderTrackSwitch() {
  const separation = state.current.result?.separation || {},
    separated = separation.enabled,
    available = availableTracks(),
    switcher = $("#trackSwitch"),
    weak = (separation.all_stems || separation.stems || []).filter((track) =>
      separation.activity?.[track]?.active === false
    );
  $("#weakTrackOption").classList.toggle("hidden", !weak.length);
  $("#weakTrackCount").textContent = `（${weak.length} 軌預設隱藏，僅依聲音強度判斷）`;
  $("#trackRow").classList.toggle("hidden", !separated);
  state.tracks = state.tracks.filter((track) => available.includes(track));
  if (!state.tracks.length) {
    state.tracks = [available.includes(separation.analysis_stem) ? separation.analysis_stem : available[0]];
  }
  if (!state.tracks.includes(state.track)) state.track = state.tracks[0];
  const key = state.current.id + ":" + available.join(",");
  if (switcher.dataset.trackJob !== key) {
    switcher.dataset.trackJob = key;
    switcher.innerHTML = available.map((track) =>
      `<button type="button" data-track="${track}">${TRACK_NAMES[track] || track}</button>`
    ).join("");
    switcher.querySelectorAll("[data-track]").forEach((button) =>
      button.addEventListener("click", () => switchTrack(button.dataset.track))
    );
  }
  updateTrackControls();
  syncMixer();
}
function updateTrackControls() {
  const oneSelected = state.tracks.length === 1;
  $("#trackSwitch").querySelectorAll("[data-track]").forEach((button) => {
    const selected = state.tracks.includes(button.dataset.track), locked = selected && oneSelected;
    button.classList.toggle("active", selected);
    button.classList.toggle("locked", locked);
    button.disabled = locked;
    button.setAttribute("aria-pressed", String(selected));
    button.textContent = TRACK_NAMES[button.dataset.track] || button.dataset.track;
    button.title = locked ? "至少保留一個音軌" : selected ? "從混音移除" : "加入混音";
  });
  $("#analysisTrackLabel").textContent = state.tracks.length > 1
    ? `已選 ${state.tracks.length} 軌 · 合併為單一同步音訊播放`
    : "已選 1 軌 · 點選其他音軌可加入混音";
}
function switchTrack(track) {
  const available = availableTracks();
  if (!available.includes(track)) return;
  const selected = state.tracks.includes(track);
  if (selected && state.tracks.length === 1) return;
  if (selected) state.tracks = state.tracks.filter((item) => item !== track);
  else state.tracks.push(track);
  if (!state.tracks.includes(state.track)) state.track = state.tracks[0];
  updateTrackControls();
  scheduleMixerSync();
  toast(`${selected ? "移除" : "加入"}混音：${TRACK_NAMES[track] || track}`);
}

function scheduleMixerSync() {
  const player = $("#audioPlayer");
  state.resumeAfterMix = state.resumeAfterMix || state.resumeOnLoad || (!player.paused && !!player.src);
  state.resumeOnLoad = false;
  state.sourceRequest++;
  player.pause();
  state.sourceLoading = true;
  $("#analysisTrackLabel").textContent = state.tracks.length > 1
    ? `已選 ${state.tracks.length} 軌 · 準備同步混音…`
    : "正在切換音軌…";
  updatePlayerControls();
  clearTimeout(state.mixTimer);
  state.mixTimer = setTimeout(() => {
    state.mixTimer = null;
    const resume = state.resumeAfterMix;
    state.resumeAfterMix = false;
    syncMixer(resume);
  }, 320);
}

function updatePlayerControls() {
  const player = $("#audioPlayer"),
    slider = $("#seekSlider"),
    duration = Number.isFinite(player.duration) ? player.duration : Number(state.current?.duration || 0),
    current = Number.isFinite(player.currentTime) ? player.currentTime : 0;
  slider.max = String(Math.max(0, duration));
  if (document.activeElement !== slider) slider.value = String(Math.min(current, duration || current));
  $("#playerTime").textContent = `${durationText(current)} / ${durationText(duration)}`;
  const toggle = $("#playToggle"), playing = !player.paused && !player.ended;
  toggle.textContent = state.sourceLoading ? "…" : playing ? "❚❚" : "▶";
  toggle.setAttribute("aria-label", state.sourceLoading ? "正在準備音訊" : playing ? "暫停" : "播放");
  toggle.classList.toggle("playing", playing);
  toggle.disabled = state.sourceLoading;
}
function updateVolumeLabel() {
  $("#volumeValue").textContent = `${Math.round(state.volume * 100)}%`;
}
function ensureAudioGraph() {
  if (state.audioGraphFailed) return false;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return false;
  try {
    if (!state.audioContext) {
      state.audioContext = new AudioContextClass();
      state.masterGain = state.audioContext.createGain();
      state.masterGain.connect(state.audioContext.destination);
    }
    if (!state.primarySource) {
      state.primarySource = state.audioContext.createMediaElementSource($("#audioPlayer"));
      state.primarySource.connect(state.masterGain);
    }
    syncMixerSettings();
    return true;
  } catch {
    state.audioGraphFailed = true;
    return false;
  }
}
function setMixerVolume(event) {
  state.volume = Math.min(1, Math.max(0, Number(event.target.value)));
  localStorage.setItem("chordlab:volume", String(state.volume));
  updateVolumeLabel();
  if (ensureAudioGraph() && state.audioContext.state === "suspended") {
    state.audioContext.resume().catch(() => {});
  }
  syncMixerSettings();
}
async function togglePlayback() {
  const player = $("#audioPlayer");
  if (state.sourceLoading || !state.current || state.current.status !== "done") return;
  if (!player.paused) {
    player.pause();
    return;
  }
  try {
    if (ensureAudioGraph() && state.audioContext.state === "suspended") await state.audioContext.resume();
    await player.play();
  } catch {
    toast("音訊載入失敗，請重新整理後再試", true);
  }
}
function seekPlayback(event) {
  const player = $("#audioPlayer"), target = Number(event.target.value);
  if (Number.isFinite(target)) player.currentTime = target;
  updatePlayerControls();
}
function clearMixer() {
  const player = $("#audioPlayer");
  clearTimeout(state.mixTimer);
  state.mixTimer = null;
  state.resumeAfterMix = false;
  state.resumeOnLoad = false;
  state.sourceRequest++;
  state.sourceLoading = false;
  if (player) {
    player.pause();
    player.removeAttribute("src");
    player.load();
    delete player.dataset.source;
  }
  state.tracks = [];
  updatePlayerControls();
}
function loadPrimarySource(expected, sourceKey, time, resume, isSynchronizedMix) {
  const player = $("#audioPlayer"), requestId = ++state.sourceRequest;
  state.sourceLoading = true;
  state.resumeOnLoad = resume;
  player.pause();
  player.src = expected;
  player.dataset.source = sourceKey;
  updatePlayerControls();
  if (isSynchronizedMix) toast("正在合併所選音軌，第一次需要稍候");
  player.addEventListener("loadedmetadata", () => {
    if (requestId !== state.sourceRequest) return;
    const shouldResume = resume && state.resumeOnLoad;
    player.currentTime = Math.min(time, player.duration || time);
    state.sourceLoading = false;
    state.resumeOnLoad = false;
    updateTrackControls();
    updatePlayerControls();
    if (shouldResume) player.play().catch(() => toast("同步混音已準備好，請按播放鍵"));
  }, { once: true });
  player.addEventListener("error", () => {
    if (requestId !== state.sourceRequest) return;
    state.sourceLoading = false;
    state.resumeOnLoad = false;
    updateTrackControls();
    updatePlayerControls();
    toast("音訊載入失敗，請稍後再試", true);
  }, { once: true });
  player.load();
}
function syncMixer(resumeOverride = false) {
  if (!state.current || state.current.status !== "done") return;
  const player = $("#audioPlayer"),
    time = Number.isFinite(player.currentTime) ? player.currentTime : 0,
    playing = resumeOverride || (!player.paused && !!player.src),
    available = availableTracks(),
    selected = available.filter((track) => state.tracks.includes(track)),
    synchronizedMix = selected.length > 1,
    sourceKey = synchronizedMix ? `mix:${selected.join(",")}` : `track:${state.track}`,
    expected = synchronizedMix
      ? `/api/jobs/${state.current.id}/audio-mix?tracks=${encodeURIComponent(selected.join(","))}`
      : `/api/jobs/${state.current.id}/audio-stream/${state.track}`;
  if (player.dataset.source !== sourceKey) {
    loadPrimarySource(expected, sourceKey, time, playing, synchronizedMix);
  } else {
    state.sourceLoading = false;
    updateTrackControls();
    updatePlayerControls();
    if (playing) player.play().catch(() => toast("音訊已準備好，請按播放鍵"));
  }
  syncMixerSettings();
}
function syncMixerSettings() {
  const player = $("#audioPlayer"), graph = !!state.primarySource;
  if (state.masterGain) state.masterGain.gain.setValueAtTime(state.volume, state.audioContext.currentTime);
  player.volume = graph ? 1 : state.volume;
}

function renderStemDownloads() {
  const separation = state.current.result?.separation || {},
    panel = $("#stemDownloadsPanel"),
    box = $("#stemDownloads");
  if (!separation.enabled && !(separation.midi_stems || []).length) {
    panel.classList.add("hidden");
    panel.open = false;
    return;
  }
  const audio = availableTracks().map((track) =>
    `<a href="/api/jobs/${state.current.id}/audio/${track}" download>${TRACK_NAMES[track] || track} WAV</a>`
  ).join("");
  const midi = (separation.midi_stems || []).filter((track) =>
    $("#showWeakTracks").checked || separation.activity?.[track]?.active !== false
  ).map((track) =>
    `<a href="/api/jobs/${state.current.id}/export/midi/${track}">${TRACK_NAMES[track] || track} MIDI</a>`
  ).join("");
  box.innerHTML = `${audio}${midi || "<small>這次沒有產生分軌 MIDI</small>"}`;
  panel.classList.remove("hidden");
}

function transposeChord(label, semitones) {
  if (!label || label === "N") return label;
  const match = label.match(/^([A-G])([#b]?)([^/]*)(?:\/([A-G])([#b]?))?$/);
  if (!match) return label;
  const roots = {
    C: 0,
    "C#": 1,
    Db: 1,
    D: 2,
    "D#": 3,
    Eb: 3,
    E: 4,
    F: 5,
    "F#": 6,
    Gb: 6,
    G: 7,
    "G#": 8,
    Ab: 8,
    A: 9,
    "A#": 10,
    Bb: 10,
    B: 11,
  };
  const root = roots[match[1] + match[2]];
  if (root === undefined) return label;
  const names = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
  let result = names[(root + semitones + 120) % 12] + match[3];
  if (match[4]) result += "/" + names[(roots[match[4] + match[5]] + semitones + 120) % 12];
  return result;
}
function playedChord(label) {
  return transposeChord(label, -state.capo);
}
function renderCapo() {
  const key = state.current?.result?.key;
  $("#capoSelect").value = String(state.capo);
  $("#keyStat").textContent = key ? `原 Key ${key.tonic} ${key.mode}` : "原 Key 無法判定";
  $("#playKeyStat").textContent = key
    ? `Play key ${NOTE_NAMES[(key.pitch_class - state.capo + 120) % 12]} ${key.mode}`
    : "Play key —";
}

async function loadContinuousTab() {
  if (!state.current?.result || state.tabJob === state.current.id) return;
  const jobId = state.current.id, separation = state.current.result.separation || {};
  state.tabJob = jobId;
  state.tabSource = "unavailable";
  const hasGuitar = (separation.midi_stems || []).includes("guitar");
  try {
    const [payload] = await Promise.all([
      hasGuitar ? api(`/api/jobs/${jobId}/notes/guitar`) : Promise.resolve(null),
      TabStudio.load(jobId),
    ]);
    if (state.current?.id !== jobId) return;
    state.tabNotes = payload?.notes || [];
    state.tabProfile = payload?.profile || "general";
    state.tabSource = payload ? "guitar" : "unavailable";
  } catch (error) {
    if (state.current?.id !== jobId) return;
    state.tabJob = null;
    toast(error.message, true);
  }
  renderContinuousTab();
}

function assignTabNotes(notes) {
  state.tabCancel?.();
  return new Promise((resolve) => {
    const worker = new Worker("/static/tab-worker.js?v=4");
    state.tabWorker = worker;
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      worker.onmessage = null;
      worker.onerror = null;
      worker.terminate();
      if (state.tabWorker === worker) {
        state.tabWorker = null;
        state.tabCancel = null;
      }
      resolve(result);
    };
    state.tabCancel = () => finish(null);
    worker.onmessage = (event) => {
      if (settled || state.tabWorker !== worker) return;
      if (event.data.error) toast(event.data.error, true);
      finish(event.data.result || null);
    };
    worker.onerror = (event) => {
      if (settled || state.tabWorker !== worker) return;
      event.preventDefault();
      console.error("TAB worker:", event.message);
      toast("指法配置失敗，請重新整理頁面", true);
      finish(null);
    };
    worker.postMessage({
      notes,
      options: {
        density: state.tabDensity,
        tuning: state.tabTuning || "standard",
        capo: state.capo,
        voice: $("#tabVoice").value,
        position: $("#tabPosition").value,
      },
    });
  });
}

function renderContinuousTab() {
  return TabStudio.render();
}
function updateContinuousTab() {
  TabStudio.update();
}

function renderLyrics() {
  const panel = $("#lyricsPanel"),
    tab = $("#lyricsResultTab"),
    lyrics = state.current?.result?.lyrics,
    segments = lyrics?.segments || [];
  state.lyricActive = -1;
  state.lyricTouched = 0;
  state.lyricEntries = [];
  if (!segments.length) {
    panel.classList.add("hidden");
    tab.classList.add("hidden");
    if (state.resultView === "lyrics") setResultView("chords");
    return;
  }
  panel.classList.remove("hidden");
  tab.classList.remove("hidden");
  setResultView(state.resultView);
  $("#lyricsLanguage").textContent = (lyrics.language || "").toUpperCase();
  $("#lyricsList").innerHTML = segments.map((segment, index) =>
    `<button data-lyric="${index}" data-start="${segment.start}" data-end="${segment.end}"><time>${
      durationText(segment.start)
    }</time><span>${escapeHtml(segment.text)}</span></button>`
  ).join("");
  state.lyricEntries = $$("[data-lyric]").map((node) => ({
    start: Number(node.dataset.start),
    end: Number(node.dataset.end),
    node,
  })).sort((a, b) => a.start - b.start);
  updateLyrics();
}
function updateLyrics() {
  if (state.resultView !== "lyrics" || state.page !== "workspace") return;
  const time = $("#audioPlayer").currentTime,
    entries = state.lyricEntries || [],
    candidate = ChordLabLayout.locate(entries, time),
    index = candidate >= 0 && time < entries[candidate].end ? candidate : -1;
  if (index === state.lyricActive) return;
  entries[state.lyricActive]?.node.classList.remove("active");
  const active = entries[index]?.node;
  active?.classList.add("active");
  state.lyricActive = index;
  if (active && !$("#audioPlayer").paused && performance.now() - (state.lyricTouched || 0) > 5000) {
    const list = $("#lyricsList"), top = active.offsetTop - list.offsetTop;
    if (top < list.scrollTop || top + active.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTo({
        top: Math.max(0, top - list.clientHeight * .38),
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
    }
  }
}

function switchMethod(method, announce = true) {
  if (!state.current?.result) return;
  if (!state.current.result.methods[method]?.length) {
    toast("這首歌沒有這種分析結果", true);
    return;
  }
  state.method = method;
  state.current.result.active_method = method;
  state.selected = -1;
  $$(".method-switch button").forEach((button) =>
    button.classList.toggle("active", button.dataset.method === method)
  );
  renderTimeline();
  renderEditor();
  if (announce) toast(`已切換到${method === "ensemble" ? "雙引擎比對" : method === "chordino" ? "原本辨識" : "音符推算"}`);
}

function needsReview(segment) {
  return segment.comparison && !["agree", "unavailable"].includes(segment.comparison.status);
}
function chords() {
  return state.current?.result?.methods?.[state.method] || [];
}
function renderTimeline() {
  const summary = $("#comparisonSummary");
  summary.classList.toggle("hidden", state.method !== "ensemble");
  if (state.method === "ensemble") {
    const count = chords().filter(needsReview).length;
    summary.textContent = count ? `${count} 段有不同判斷 · 點選帶圓點的和弦查看候選` : "未標記分歧，仍可人工修正";
  }
  const list = chords(), duration = state.current.duration || 1, timeline = $("#timeline");
  timeline.innerHTML = list.map((segment, index) => {
    const played = playedChord(segment.chord);
    const review = state.method === "ensemble" && needsReview(segment);
    return `<button class="chord-block ${
      index === state.selected ? "selected" : ""
    } ${review ? "needs-review" : ""}" ${review ? 'title="兩個引擎有不同判斷，點選查看"' : ""} data-segment="${index}" style="width:${
      Math.max(62, (segment.end - segment.start) / duration * 1300)
    }px"><b>${escapeHtml(played)}</b>${state.capo ? `<em>原 ${escapeHtml(segment.chord)}</em>` : ""}<small>${
      durationText(segment.start)
    }</small></button>`;
  }).join("");
  state.chordNodes = $$("[data-segment]");
  state.chordEntries = state.chordNodes.map((node, index) => ({
    start: Number(list[index].start),
    end: Number(list[index].end),
    node,
  })).sort((a, b) => a.start - b.start);
  state.chordActive = -1;
  const ruler = $("#timelineRuler"), step = duration > 600 ? 120 : duration > 240 ? 60 : 30;
  let ticks = "";
  for (let t = 0; t <= duration; t += step) {
    ticks += `<span class="ruler-tick" style="left:${t / duration * 100}%">${durationText(t)}</span>`;
  }
  ruler.innerHTML = ticks;
}
function selectSegment(index, seek = false) {
  state.chordNodes?.[state.selected]?.classList.remove("selected");
  state.selected = index;
  state.chordNodes?.[index]?.classList.add("selected");
  renderEditor();
  const original = chords()[index]?.chord;
  renderVoicing(playedChord(original), original);
  if (seek) $("#audioPlayer").currentTime = chords()[index].start;
}
function markPlaying() {
  const entries = state.chordEntries || [],
    time = $("#audioPlayer").currentTime,
    candidate = ChordLabLayout.locate(entries, time),
    index = candidate >= 0 && time < entries[candidate].end ? candidate : -1;
  if (index === state.chordActive) return;
  entries[state.chordActive]?.node.classList.remove("playing");
  entries[index]?.node.classList.add("playing");
  state.chordActive = index;
}
function renderEditor() {
  const segment = chords()[state.selected];
  const editable = state.current?.mine || state.viewer?.admin;
  $("#editorEmpty").classList.toggle("hidden", !!segment);
  $("#segmentForm").classList.toggle("hidden", !segment || !editable);
  if (segment) {
    $("#chordInput").value = segment.chord;
    $("#startInput").value = segment.start;
    $("#endInput").value = segment.end;
  }
  $("#saveState").textContent = "尚未修改";
  renderCandidates(segment, editable);
}
function renderCandidates(segment, editable) {
  const box = $("#chordCandidates"), comparison = state.method === "ensemble" ? segment?.comparison : null;
  const jobId = state.current?.id;
  box.classList.toggle("hidden", !comparison || !needsReview(segment));
  box.replaceChildren();
  if (!comparison || !needsReview(segment)) return;
  const explanation = document.createElement("p");
  explanation.textContent = comparison.status === "detail" ? "根音與和弦家族相同，延伸音或低音不同。" : "BTC 對這一段有不同判斷；目前保留原本結果。";
  box.append(explanation);
  for (const candidate of comparison.candidates || []) {
    const row = document.createElement("div"), text = document.createElement("span");
    text.textContent = `BTC ${playedChord(candidate.chord)} · 占此段 ${Math.round(candidate.share * 100)}% 時間`;
    row.append(text);
    if (editable && !["N", "X", segment.chord].includes(candidate.chord)) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "text-button"; button.textContent = "整段改用這個";
      button.addEventListener("click", async () => {
        if (state.current?.id !== jobId || chords()[state.selected] !== segment) return;
        if (!confirm(`將 ${durationText(segment.start)}–${durationText(segment.end)} 整段改為 ${candidate.chord}？`)) return;
        segment.chord = candidate.chord;
        delete segment.comparison; segment.manual = true;
        renderTimeline(); renderEditor(); renderVoicing(playedChord(segment.chord), segment.chord);
        await persist();
      });
      row.append(button);
    }
    box.append(row);
  }
}
async function persist() {
  try {
    await api(`/api/jobs/${state.current.id}/chords`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method: state.method, chords: chords() }),
    });
    $("#saveState").textContent = "已儲存";
    toast("修正已儲存");
  } catch (error) {
    toast(error.message, true);
  }
}
async function saveSegment(event) {
  event.preventDefault();
  const segment = chords()[state.selected];
  segment.chord = $("#chordInput").value.trim() || "N";
  segment.start = Number($("#startInput").value);
  segment.end = Number($("#endInput").value);
  delete segment.comparison;
  renderTimeline();
  renderCandidates(segment, state.current?.mine || state.viewer?.admin);
  renderVoicing(playedChord(segment.chord), segment.chord);
  await persist();
}
async function deleteSegment() {
  if (state.selected < 0) return;
  chords().splice(state.selected, 1);
  state.selected = -1;
  renderTimeline();
  renderEditor();
  renderVoicing(null);
  await persist();
}

function parseChord(label) {
  return ChordLabTheory.parseChord(label);
}
const voicingCache = new Map();
function findVoicing(label) {
  if (voicingCache.has(label)) return voicingCache.get(label);
  const result = computeVoicing(label);
  if (voicingCache.size >= 96) voicingCache.delete(voicingCache.keys().next().value);
  voicingCache.set(label, result);
  return result;
}
function computeVoicing(label) {
  const parsed = parseChord(label);
  if (!parsed) return null;
  let best = null;
  for (let base = 0; base <= 9; base++) {
    const choices = TUNING.map((note) => {
      const values = [-1];
      for (let fret = 0; fret <= 12; fret++) {
        if (parsed.tones.includes((note + fret) % 12) && (fret === 0 || (fret >= base && fret <= base + 4))) {
          values.push(fret);
        }
      }
      return values.slice(0, 5);
    });
    const walk = (index, shape) => {
      if (index === 6) {
        const played = shape.filter((x) => x >= 0);
        if (played.length < 4) return;
        const pcs = new Set(
          shape.map((fret, i) => fret < 0 ? null : (TUNING[i] + fret) % 12).filter((x) => x !== null),
        );
        if (!parsed.tones.every((tone) => pcs.has(tone)) || !pcs.has(parsed.root)) return;
        const fretted = played.filter((x) => x > 0),
          span = fretted.length ? Math.max(...fretted) - Math.min(...fretted) : 0;
        if (span > 4) return;
        const bass = shape.findIndex((x) => x >= 0), bassPc = (TUNING[bass] + shape[bass]) % 12;
        if (parsed.bass !== undefined && bassPc !== parsed.bass) return;
        const score = shape.filter((x) => x < 0).length * 2 + span * 1.5 + played.reduce((a, b) =>
              a + b, 0) * .12 +
          (bassPc === parsed.root ? 0 : 2);
        if (!best || score < best.score) best = { shape: [...shape], score, parsed };
        return;
      }
      for (const fret of choices[index]) walk(index + 1, [...shape, fret]);
    };
    walk(0, []);
  }
  return best;
}
function renderVoicing(label, original = label) {
  const board = $("#fretboard");
  if (!label) {
    $("#selectedChord").textContent = "選擇一個和弦";
    board.className = "tablature empty";
    board.innerHTML = "<span>點一下時間軸上的和弦，這裡會顯示橫向六線譜、格數與音名。</span>";
    $("#voicingNotes").textContent = "";
    return;
  }
  $("#selectedChord").textContent = state.capo ? `${label}（原和弦 ${original}）` : label;
  const voicing = findVoicing(label);
  if (!voicing) {
    board.className = "tablature empty";
    board.innerHTML = "<span>這個標記暫時無法產生標準吉他按法，可直接修改名稱。</span>";
    $("#voicingNotes").textContent = "";
    return;
  }
  const rows = voicing.shape.map((fret, index) => ({
    fret,
    index,
    string: ["E", "A", "D", "G", "B", "e"][index],
    number: [6, 5, 4, 3, 2, 1][index],
    note: fret < 0 ? "×" : NOTE_NAMES[(TUNING[index] + fret) % 12],
  })).reverse();
  board.className = "tablature";
  board.innerHTML = rows.map((row) =>
    `<div class="tab-string"><span class="tab-string-name">${row.string}</span><span class="tab-line"><i class="tab-fret ${
      row.fret < 0 ? "muted" : row.fret === 0 ? "open" : ""
    }">${row.fret < 0 ? "×" : row.fret}</i></span><span class="tab-note">${
      row.fret < 0 ? "—" : row.note
    }</span></div>`
  ).join("");
  $("#voicingNotes").textContent =
    `Capo ${state.capo}；六線譜由上到下是高音 e、B、G、D、A、低音 E。數字是相對於 Capo 的格數，0 是空弦，× 是不彈。`;
}
document.addEventListener("DOMContentLoaded", init);
