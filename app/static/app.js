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
  tabInstrument: "guitar",
  page: "workspace",
  resultView: "chords",
  librarySort: "recent",
  libraryTimer: null,
};
const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
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
  $("#tabAnalysisDetails").prepend($("#tabEngineOption"));
  $("#tabAnalysisDetails").append($("#tabDisclaimer"));
  LocalChordReview.bind();
  TabStudio.bind();
  $("#analysisPreset").addEventListener("change", applyAnalysisPreset);
  applyAnalysisPreset();
  const methodDetails = document.createElement("details");
  methodDetails.className = "method-options";
  const methodSummary = document.createElement("summary");
  methodSummary.textContent = "辨識方式";
  methodDetails.append(methodSummary, $(".method-switch"));
  $(".method-row").append(methodDetails);
  $(".method-row").append($("#workspaceUtilities"));
  // The theme script may run before asynchronous viewer loading finishes.
  if (document.documentElement.dataset.theme === 'studio') $('#workspaceUtilitiesBody').append(methodDetails);
  $('#songPickerToggle').addEventListener('click', () => setSongPickerOpen(!document.body.classList.contains('song-picker-open'), true));
  $('#sidebarImportToggle').addEventListener('click', () => setSongPickerOpen(!document.body.classList.contains('song-picker-open'), true));
  $('#songPickerClose').addEventListener('click', () => setSongPickerOpen(false, true));
  $('#dockSizeToggle').addEventListener('click', () => {
    state.dockCompact = !document.body.classList.contains('compact-player');
    syncPlayerDock();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('song-picker-open') && document.documentElement.dataset.theme === 'studio') setSongPickerOpen(false, true);
  });
  window.addEventListener('chordlab:appearance', syncPlayerDock);
  document.addEventListener('click', event => {
    const tools = $('#workspaceUtilities');
    if (tools.open && !tools.contains(event.target) && document.documentElement.dataset.theme === 'studio') tools.open = false;
  });
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
      if (button.hasAttribute('data-new-song')) setSongPickerOpen(true, true);
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
      if (state.current) localStorage.setItem(tabStorageKey("density"), state.tabDensity);
      $$("[data-tab-density]").forEach((item) => item.classList.toggle("active", item === button));
      renderContinuousTab();
    })
  );
  $("#tabTuning").addEventListener("change", (event) => {
    if (!TabStudio.reconfigure()) return;
    state.tabTuning = event.target.value;
    if (state.current) localStorage.setItem(tabStorageKey("tuning"), state.tabTuning);
    $("#tabChordShapeOption").classList.toggle("hidden", state.tabTuning !== "standard");
    $("#tabChordShapeHint").classList.toggle("hidden", state.tabTuning !== "standard");
    renderContinuousTab();
  });
  for (const [id, key] of [["tabVoice", "voice"], ["tabPosition", "position"],["tabRole","role"]]) {
    $("#" + id).addEventListener("change", (event) => {
      if (!TabStudio.reconfigure()) {
        return;
      }
      if (state.current) localStorage.setItem(tabStorageKey(key), event.target.value);
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
  $("#buildChordV2").addEventListener("click", buildChordRefinement);
  $("#capoSelect").addEventListener("change", (event) => {
    if (state.tabInstrument !== "bass" && !TabStudio.reconfigure()) return;
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
  $("#restoreChords").addEventListener("click", restorePreviousChords);
  $("#cancelJob").addEventListener("click", async () => {
    const id = state.current?.id;
    if (!id || !confirm("確定取消這次分析？正在執行的步驟會先完成。")) return;
    try {
      await api(`/api/jobs/${id}/cancel`, { method: "POST" });
      if (state.current?.id !== id) return;
      state.current = await api(`/api/jobs/${id}?include_notes=false`);
      renderWorkspace();
      loadJobs(); loadQueueStatus();
    } catch (error) { toast(error.message, true); }
  });
  $("#logoutAll").addEventListener("click", async () => {
    if (!confirm("確定登出所有裝置？你也需要重新登入。")) return;
    try {
      await api("/api/logout-all", { method: "POST" });
      location.href = "/login";
    } catch (error) { toast(error.message, true); }
  });
  $("#timeline").addEventListener("click", (event) => {
    const button = event.target.closest("[data-segment]");
    if (button) selectSegment(Number(button.dataset.segment), true);
  });
  $("#lyricsList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-start]");
    if (button) $("#audioPlayer").currentTime = Number(button.dataset.start);
  });
  $("#followChords").checked = localStorage.getItem("followChords") !== "off";
  $("#followChords").addEventListener("change", (event) => {
    localStorage.setItem("followChords", event.target.checked ? "on" : "off");
    state.chordTouched = -Infinity;
    markPlaying();
  });
  for (const name of ["pointerdown", "touchstart", "wheel", "keydown"]) {
    $("#timeline").addEventListener(name, () => { state.chordTouched = performance.now(); }, {passive:true});
  }
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
        const suffix = link.dataset.export === "midi" ? "" : `?capo=${state.capo}&method=${encodeURIComponent(state.method)}`;
        location.href = `/api/jobs/${state.current.id}/export/${link.dataset.export}${suffix}`;
      }
    })
  );
  Practice.bind();
  $("#smoothVoicings").addEventListener("change", () => {
    currentVoicingLabel = null;
    if (state.selected >= 0) renderVoicing(playedChord(chords()[state.selected]?.chord), chords()[state.selected]?.chord);
  });
  $("#visibilityToggle").addEventListener("click", toggleVisibility);
}

function setPage(page) {
  state.page = page === "library" ? "library" : "workspace";
  $("#workspacePage").classList.toggle("hidden", state.page !== "workspace");
  $("#libraryPage").classList.toggle("hidden", state.page !== "library");
  syncPlayerDock();
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
  if (state.resultView !== view) state.dockCompact = null;
  state.resultView = view;
  syncPlayerDock();
  $$("[data-result-view]").forEach((button) =>
    button.classList.toggle("active", button.dataset.resultView === view)
  );
  $$("[data-result-panel]").forEach((panel) =>
    panel.classList.toggle("result-hidden", panel.dataset.resultPanel !== view)
  );
  if (view === "tab") {
    loadContinuousTab();
    TabStudio.render();
  }
  paintPlayback();
  animatePlayback();
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
function setSongPickerOpen(open, navigate = false) {
  document.body.classList.toggle('song-picker-open', !!open);
  for (const id of ['songPickerToggle', 'sidebarImportToggle']) $('#'+id)?.setAttribute('aria-expanded', String(!!open));
  if (!navigate) return;
  if (open) {
    $('.left-rail').scrollIntoView({block:'start', behavior:'instant'});
    const close = $('#songPickerClose');
    if (getComputedStyle(close).display !== 'none') close.focus({preventScroll:true});
  } else {
    revealWorkspaceOnMobile();
    $('#songPickerToggle').focus({preventScroll:true});
  }
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
  Practice.tick();
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
      document.hidden || $("#audioPlayer").paused || state.page !== "workspace" || !["tab", "chords"].includes(state.resultView)
    ) return;
    if (time - (state.lastPlayPaint || 0) > 33) {
      state.lastPlayPaint = time;
      if (state.resultView === "tab") updateContinuousTab();
      else markPlaying();
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
// Decorative identity, not a fetched album cover or an inferred musical feature.
function songAccent(job) {
  let hash = 0;
  for (const char of String(job.title || job.id || '')) hash = (hash * 31 + char.codePointAt(0)) | 0;
  return ['#b19777', '#9a91a4', '#8a96a2', '#b29798', '#aba397'][Math.abs(hash) % 5];
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
      }" style="--song-accent:${songAccent(job)}" data-job="${job.id}"><span class="song-stamp studio-only" aria-hidden="true"></span><span class="job-title">${escapeHtml(job.title)}</span><span class="job-meta">${
        new Date(job.created_at * 1000).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit" })
      }${job.duration ? " · " + durationText(job.duration) : ""}${
        job.separate_stems ? " · " + (job.separation_model === "htdemucs_6s" ? "6 軌" : "4 軌") : ""
      }${job.is_public ? " · 公開" : ""}</span><span class="job-state ${job.status}">${
        job.status === "queued"
          ? `前方 ${job.ahead_count || 0} 首`
          : { working: `${job.progress}%`, done: "完成", failed: "失敗", cancelled: "已取消" }[job.status]
      }</span></button>`
    ).join("") + (state.jobs.length > 8
      ? `<button class="jobs-more" id="jobsMore">${
        state.jobsExpanded ? "收起" : "顯示其他 " + (state.jobs.length - 8) + " 首"
      }</button>`
      : "");
  $$("[data-job]").forEach((button) => {
    button.title = [".job-title", ".job-meta", ".job-state"].map(selector => button.querySelector(selector)?.textContent || "").join("\n");
    button.addEventListener("click", () => openJob(button.dataset.job, false, true));
  });
  $("#jobsMore")?.addEventListener("click", () => {
    state.jobsExpanded = !state.jobsExpanded;
    renderJobs();
  });
}

async function openJob(id, isPublic = false, reveal = false) {
  if (!TabStudio.canLeave()) return;
  state.tabInstrument = "guitar";
  state.guitarTabEngine = "basic_pitch";
  state.tabEngine = "basic_pitch";
  $("#tabEngine").value = "basic_pitch";
  $("#tabEngineOption").open = false;
  TabStudio.reset(id);
  const requestId = ++state.openRequest;
  clearTimeout(state.chordRefinementTimer);
  $("#buildChordV2").classList.add("hidden");
  clearInterval(state.poller);
  state.poller = null;
  clearMixer();
  state.tabJob = null;
  state.tabNotes = [];
  state.tabSource = "unavailable";
  state.tabCancel?.();
  state.tabRender = (state.tabRender || 0) + 1;
  TabStudio.configure(id);
  $("#showWeakTracks").checked = false;
  try {
    const job = await api(
      isPublic ? `/api/public/jobs/${id}?include_notes=false` : `/api/jobs/${id}?include_notes=false`,
    );
    if (requestId !== state.openRequest) return;
    if (job.status === "done") {
      // A saved personal score takes precedence over automatic recommendations.
      const personal = state.viewer ? await api(`/api/jobs/${id}/tab?instrument=guitar`) : {};
      if (requestId !== state.openRequest) return;
      const savedEngine = personal.document?.source_engine || (personal.document ? "basic_pitch" : null);
      const variants = job.result?.guitar_tab?.variants || {};
      const selected = savedEngine || ["event_verified", "hybrid", "gaps"].find((name) => variants[name]?.status === "done") || "basic_pitch";
      state.tabEngine = state.guitarTabEngine = selected;
      $("#tabEngine").value = selected;
    }
    state.currentPublic = isPublic;
    state.current = job;
    setSongPickerOpen(false);
    if (!isPublic) localStorage.setItem(lastJobKey(), id);
    const preferredMethod = job.result?.active_method || "chordino";
    state.method = job.result?.event_verified_chord_review?.version >= 2 && job.result?.methods?.event_verified?.length &&
      preferredMethod !== "local_review" && !job.result?.methods?.[preferredMethod]?.some(segment => segment.manual) ? "event_verified" : preferredMethod;
    state.track = job.result?.separation?.analysis_stem || "original";
    state.tracks = [state.track];
    state.capo = Math.min(11, Math.max(0, Math.round(Number(localStorage.getItem(`capo:${id}`)) || 0)));
    state.selected = -1;
    LocalChordReview.open();
    state.resultView = "chords";
    syncCurrentJob();
    renderWorkspace();
    if (job.status === "done") refreshChordRefinement(id, requestId);
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
            if (update.status === "done") refreshChordRefinement(id, requestId);
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

function syncPlayerDock() {
  const visible = state.page === "workspace" && state.current?.status === "done";
  $("#playerDock").classList.toggle("hidden", !visible);
  document.body.classList.toggle("has-player-dock", visible);
  $("#playerSongTitle").textContent = state.current?.title || "—";
  document.body.classList.toggle('has-current-song', !!state.current);
  const compact = document.documentElement.dataset.theme === 'studio' && (state.dockCompact ?? state.resultView === 'tab');
  document.body.classList.toggle('compact-player', compact);
  const size = $('#dockSizeToggle');
  size.textContent = compact ? '展開' : '收起';
  size.setAttribute('aria-pressed', String(compact));
  size.title = compact ? '展開歌名、音量與播放資訊' : '切換精簡播放器';
}

function renderWorkspace() {
  syncPlayerDock();
  $("#emptyWorkspace").classList.add("hidden");
  $("#activeWorkspace").classList.remove("hidden");
  $("#workTitle").textContent = state.current.title;
  $("#activeWorkspace").style.setProperty('--song-accent', songAccent(state.current));
  const workspace = $("#activeWorkspace");
  if (workspace.dataset.visualJob !== state.current.id) {
    workspace.dataset.visualJob = state.current.id;
    if (document.documentElement.dataset.theme === 'studio' && !document.hidden && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const heading = $(".song-heading");
      heading.getAnimations().forEach(animation => animation.cancel());
      heading.animate([{opacity:0, transform:'translateY(6px)'}, {opacity:1, transform:'translateY(0)'}], {duration:220, easing:'ease-out'});
    }
  }
  $("#workMeta").textContent =
    { queued: "排隊等候", working: "正在分析", done: "分析完成", failed: "分析失敗", cancelled: "已取消" }[state.current.status] ||
    "音樂分析";
  $("#workMessage").textContent = state.current.status === "done" ? "" : state.current.message;
  const visibility = $("#visibilityToggle");
  visibility.classList.toggle("hidden", state.current.status !== "done" || !state.current.mine);
  visibility.classList.toggle("public", !!state.current.is_public);
  visibility.textContent = state.current.is_public ? "公開分析" : "私人分析";
  const working = ["queued", "working"].includes(state.current.status);
  $("#progressPanel").classList.toggle("hidden", !working && !["failed", "cancelled"].includes(state.current.status));
  $("#cancelJob").classList.toggle("hidden", !working || !!state.current.cancel_requested || !(state.current.mine || state.viewer?.admin));
  $("#resultsPanel").classList.toggle("hidden", state.current.status !== "done");
  $("#progressText").textContent = state.current.status === "cancelled" ? "已取消"
    : state.current.status === "failed"
    ? "分析失敗"
    : state.current.status === "queued"
    ? `正在等候 · 前面還有 ${state.current.ahead_count || 0} 首`
    : state.current.message;
  $("#progressValue").textContent = state.current.status === "cancelled" ? "—"
    : state.current.status === "queued"
    ? "等候中"
    : `${state.current.progress}%`;
  $("#progressBar").style.width = state.current.status === "queued" ? "2%" : `${state.current.progress}%`;
  $("#progressHelp").textContent = state.current.status === "cancelled" ? "可以重新加入歌曲；已取消的這次分析不再占用佇列。"
    : state.current.cancel_requested ? "正在完成目前步驟，之後會停止。"
    : state.current.status === "queued"
    ? "伺服器一次分析一首；前一首完成後會自動接續，不需要留著網頁。"
    : state.current.separate_stems
    ? `這次會先用 Demucs 做${
      state.current.separation_model === "htdemucs_6s" ? "六" : "四"
    }軌分離，再執行音符、和弦與 Key 分析。`
    : "伺服器會依序完成音訊轉換、Basic Pitch 音符辨識、Chordino 和弦與 Key 分析。";
  if (state.current.status === "done") {
    let v2Button = $("[data-method='chord_v2']");
    if (!v2Button) {
      v2Button = document.createElement("button");
      v2Button.dataset.method = "chord_v2";
      v2Button.textContent = "和弦 v2（實驗）";
      v2Button.addEventListener("click", () => switchMethod("chord_v2"));
      $(".method-switch").append(v2Button);
    }
    v2Button.classList.toggle("hidden", !state.current.result.methods.chord_v2?.length);
    let crossButton = $("[data-method='cross_verified']");
    if (!crossButton) {
      crossButton = document.createElement("button");
      crossButton.dataset.method = "cross_verified";
      crossButton.textContent = "交叉校驗（實驗）";
      crossButton.addEventListener("click", () => switchMethod("cross_verified"));
      $(".method-switch").append(crossButton);
    }
    crossButton.classList.toggle("hidden", !state.current.result.methods.cross_verified?.length);
    let eventButton = $("[data-method='event_verified']");
    if (!eventButton) {
      eventButton = document.createElement("button");
      eventButton.dataset.method = "event_verified";
      eventButton.textContent = "建議版";
      eventButton.addEventListener("click", () => switchMethod("event_verified"));
      $(".method-switch").append(eventButton);
    }
    eventButton.classList.toggle("hidden", !state.current.result.methods.event_verified?.length);
    let localButton = $("[data-method='local_review']");
    if (!localButton) {
      localButton = document.createElement("button");localButton.dataset.method="local_review";localButton.textContent="局部修正版";
      localButton.addEventListener("click",()=>switchMethod("local_review"));$(".method-switch").append(localButton);
    }
    localButton.classList.toggle("hidden",!state.current.result.methods.local_review?.length);
    $("[data-method='ensemble']").classList.toggle("hidden", !state.current.result.methods.ensemble?.length);
    if (!state.current.result.methods[state.method]?.length) {
      state.method = state.current.result.methods.chordino.length ? "chordino" : "basic_pitch";
    }
    renderTrackSwitch();
    renderStemDownloads();
    renderCapo();
    renderLyrics();
    if (state.resultView === "tab") loadContinuousTab();
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
      `<article class="library-card" style="--song-accent:${songAccent(job)}"><button class="library-open" data-public-job="${job.id}"><span class="library-sleeve studio-only" aria-hidden="true"><span class="record-disc"></span></span><p class="eyebrow">${
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
  document.body.classList.toggle('music-playing', playing && !state.sourceLoading);
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
  Practice.reset();
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

function tabStorageKey(setting, id = state.current?.id) {
  return `tab-${setting}:${id}${state.tabInstrument === "bass" ? ":bass" : ""}`;
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
  const engine = state.tabEngine || "basic_pitch";
  const instrument = state.tabInstrument || "guitar";
  if (!state.current?.result || state.tabJob === `${state.current.id}:${instrument}:${engine}`) return;
  const generation = state.tabLoad = (state.tabLoad || 0) + 1;
  const jobId = state.current.id, separation = state.current.result.separation || {};
  state.tabJob = `${jobId}:${instrument}:${engine}`;
  state.tabSource = "unavailable";
  state.tabNotes = [];
  state.tabContextReview = false;
  state.tabLearnedAudit = null;
  const hasGuitar = instrument === "bass" ? (separation.midi_stems || []).includes("bass") : engine === "basic_pitch" ? (separation.midi_stems || []).includes("guitar") :
    state.current.result.guitar_tab?.variants?.[engine]?.status === "done";
  try {
    const [payload] = await Promise.all([
      hasGuitar ? api(`/api/jobs/${jobId}/notes/${instrument}?engine=${engine}`) : Promise.resolve(null),
      TabStudio.load(jobId),
    ]);
    if (generation !== state.tabLoad || state.current?.id !== jobId || (state.tabEngine || "basic_pitch") !== engine || state.tabInstrument !== instrument) return;
    state.tabNotes = payload?.notes || [];
    state.tabContextReview = Boolean(payload?.context_review);
    state.tabLearnedAudit = payload?.learned_note_audit || null;
    state.tabProfile = payload?.profile || "general";
    state.tabVerification = ["verified", "cross_verified", "event_verified"].includes(engine) ? payload?.refinement : null;
    state.tabEventReview = engine === "event_verified" ? payload?.event_review : null;
    state.tabSource = payload ? instrument : "unavailable";
  } catch (error) {
    if (generation !== state.tabLoad || state.current?.id !== jobId || (state.tabEngine || "basic_pitch") !== engine || state.tabInstrument !== instrument) return;
    state.tabJob = null;
    toast(error.message, true);
  }
  renderContinuousTab();
}

function assignTabNotes(notes) {
  state.tabCancel?.();
  return new Promise((resolve) => {
    const worker = new Worker("/static/tab-worker.js?v=12");
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
        instrument: state.tabInstrument || "guitar",
        capo: state.tabInstrument === "bass" ? 0 : state.capo,
        voice: $("#tabVoice").value,
        position: $("#tabPosition").value,
        role: $("#tabRole").value,
        contextReview: Boolean(state.tabContextReview),
        chordShapeAssist: state.tabInstrument !== "bass" && (state.tabTuning || "standard") === "standard" && $("#tabChordShapeAssist").checked,
        chordShapes: state.tabInstrument !== "bass" && $("#tabChordShapeAssist").checked ? chords().map((segment) => ({
          start: segment.start, end: segment.end, confidence: segment.confidence,
          uncertain: segment.refinement?.uncertain,
          label: playedChord(segment.chord),
        })) : [],
        useModelFingering: state.tabInstrument !== "bass" && ["tabcnn", "hybrid", "cross_verified", "event_verified"].includes(state.tabEngine) && $("#tabFingering").value === "model",
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

async function refreshChordRefinement(id, requestId = state.openRequest) {
  try {
    const info = await api(`/api/jobs/${id}/chord-refinement`);
    if (state.current?.id !== id || state.openRequest !== requestId) return;
    const button = $("#buildChordV2");
    const working = ["queued", "working"].includes(info.status);
    button.classList.toggle("hidden", info.ready || !(state.current.mine || state.viewer?.admin) || !info.available);
    button.disabled = working || !!info.busy_engine;
    button.textContent = working ? (info.status === "queued" ? "和弦 v2 排隊中…" : "和弦 v2 分析中…") :
      info.busy_engine ? "等待其他進階分析完成…" : info.status === "failed" ? "重試和弦 v2（實驗）" : "分析和弦 v2（實驗）";
    if (info.ready && !state.current.result.methods.chord_v2?.length) {
      const job = await api(`/api/jobs/${id}?include_notes=false`);
      if (state.current?.id !== id || state.openRequest !== requestId) return;
      state.current = job;
      renderWorkspace();
    }
    clearTimeout(state.chordRefinementTimer);
    if (working || info.busy_engine) state.chordRefinementTimer = setTimeout(() => refreshChordRefinement(id, requestId), 2500);
  } catch (error) {
    if (state.current?.id === id && state.openRequest === requestId) toast(error.message, true);
  }
}

async function buildChordRefinement() {
  const id = state.current?.id, requestId = state.openRequest;
  if (!id || $("#buildChordV2").disabled) return;
  $("#buildChordV2").disabled = true;
  try {
    await api(`/api/jobs/${id}/chord-refinement`, { method: "POST" });
    if (state.current?.id !== id || state.openRequest !== requestId) return;
    toast("已加入和弦 v2 分析佇列，原版不會被改動");
  } catch (error) {
    if (state.current?.id === id && state.openRequest === requestId) toast(error.message, true);
  }
  if (state.current?.id === id && state.openRequest === requestId) refreshChordRefinement(id, requestId);
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
  if ($("#tabChordShapeAssist").checked && !TabStudio.inspect().dirty) renderContinuousTab();
  if (announce) toast(`已切換到${{local_review:"局部修正版",event_verified:"建議版",cross_verified:"交叉校驗",chord_v2:"和弦 v2（實驗）",ensemble:"雙引擎比對",chordino:"原本辨識"}[method] || "音符推算"}`);
}

function needsReview(segment) {
  return segment.refinement?.uncertain || segment.comparison && !["agree", "unavailable"].includes(segment.comparison.status);
}
function chords() {
  return state.current?.result?.methods?.[state.method] || [];
}
function renderTimeline() {
  const summary = $("#comparisonSummary");
  summary.classList.toggle("hidden", !["ensemble", "chord_v2", "cross_verified", "event_verified","local_review"].includes(state.method));
  if(state.method==="local_review")summary.textContent="局部修正版 · 已確認重查結果，原版與人工段落保留。";
  if (["cross_verified", "event_verified"].includes(state.method)) {
    const info = state.current.result[state.method === "event_verified" ? "event_verified_chord_review" : "cross_chord_review"] || {};
    summary.textContent = `${state.method === "event_verified" ? "建議版" : "交叉校驗"} · ${info.split_baseline_segments ? `細分 ${info.split_baseline_segments} 個長段 · ` : ""}調整 ${info.changed_segments || 0} 段 · ${info.review_segments || 0} 段有候選；原版與 Key 保留，仍需試聽。`;
  }
  if (state.method === "chord_v2") {
    summary.textContent = "實驗版 · 分開檢查低音與和弦音，再依前後段落判斷；仍可能誤判，原版已保留。";
  }
  if (state.method === "ensemble") {
    const count = chords().filter(needsReview).length;
    summary.textContent = count ? `${count} 段有不同判斷 · 點選帶圓點的和弦查看候選` : "未標記分歧，仍可人工修正";
  }
  const list = chords(), duration = state.current.duration || 1, timeline = $("#timeline");
  timeline.innerHTML = list.map((segment, index) => {
    const played = playedChord(segment.chord);
    const review = ["ensemble", "chord_v2", "cross_verified", "event_verified","local_review"].includes(state.method) && needsReview(segment);
    return `<button class="chord-block ${
      index === state.selected ? "selected" : ""
    } ${review ? "needs-review" : ""}" ${review ? 'title="這段需要檢查，點選查看候選"' : ""} data-segment="${index}" style="width:${
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
  state.chordPlayhead = document.createElement("i");
  state.chordPlayhead.className = "chord-playhead hidden";
  state.chordPlayhead.setAttribute("aria-hidden", "true");
  timeline.append(state.chordPlayhead);
  const ruler = $("#timelineRuler"), step = duration > 600 ? 120 : duration > 240 ? 60 : 30;
  let ticks = "";
  for (let t = 0; t <= duration; t += step) {
    ticks += `<span class="ruler-tick" style="left:${t / duration * 100}%">${durationText(t)}</span>`;
  }
  ruler.innerHTML = ticks;
  markPlaying();
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
  if (index !== state.chordActive) {
    entries[state.chordActive]?.node.classList.remove("playing");
    entries[index]?.node.classList.add("playing");
    state.chordActive = index;
  }
  const head = state.chordPlayhead, active = entries[index];
  if (!head) return;
  head.classList.toggle("hidden", !active);
  if (!active || state.resultView !== "chords" || state.page !== "workspace") return;
  const timeline = $("#timeline"), width = timeline.clientWidth;
  if (!width) return;
  const fraction = Math.max(0, Math.min(1, (time - active.start) / (active.end - active.start)));
  const x = active.node.offsetLeft + fraction * active.node.offsetWidth;
  head.style.transform = `translateX(${x}px)`;
  if ($("#followChords").checked && !$("#audioPlayer").paused &&
      performance.now() - (state.chordTouched ?? -Infinity) > 5000) {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduced || x < timeline.scrollLeft + 12 || x > timeline.scrollLeft + width - 12) {
      timeline.scrollLeft = Math.max(0, x - width * .35);
    }
  }
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
  $("#restoreChords").disabled = !editable || !(state.current?.result?.chord_revisions?.[state.method] > 0);
  renderCandidates(segment, editable);
}

async function restorePreviousChords() {
  if (!state.current || !confirm("復原這個辨識方式的上一版和弦？目前版本仍保留在歷史紀錄。")) return;
  const id = state.current.id, method = state.method;
  const revision = state.current.result.chord_revisions?.[method] ?? 0;
  if (!revision) return;
  try {
    await api(`/api/jobs/${id}/chords/restore`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method, revision, restore_revision: revision - 1 }),
    });
    const latest = await api(`/api/jobs/${id}?include_notes=false`);
    if (state.current?.id !== id) return;
    state.current = latest;
    state.selected = -1;
    renderTimeline(); renderEditor(); renderVoicing(null);
    toast("已復原上一版和弦");
  } catch (error) { toast(error.message, true); }
}
function renderCandidates(segment, editable) {
  const v2 = ["chord_v2", "cross_verified", "event_verified","local_review"].includes(state.method);
  const box = $("#chordCandidates"), comparison = v2 && segment?.refinement?.uncertain ?
    { candidates: segment.refinement.alternatives } : state.method === "ensemble" ? segment?.comparison : null;
  const jobId = state.current?.id;
  box.classList.toggle("hidden", !comparison || !needsReview(segment));
  box.replaceChildren();
  if (!comparison || !needsReview(segment)) return;
  const explanation = document.createElement("p");
  explanation.textContent = ["cross_verified", "event_verified"].includes(state.method) ? "音訊或和弦辨識仍有疑點；以下是候選，不是正確率，建議試聽確認。" : v2 ? "證據接近，建議試聽。以下是此段開頭的候選，不是正確率。" :
    comparison.status === "detail" ? "根音與和弦家族相同，延伸音或低音不同。" : "BTC 對這一段有不同判斷；目前保留原本結果。";
  box.append(explanation);
  const evidence=segment.refinement?.components;
  if(evidence){
    const detail=document.createElement("small");
    detail.textContent=[["根音","root"],["候選低音","bass_target"],["三度","third"],["七度","seventh"]]
      .filter(([,key])=>evidence[key]).map(([name,key])=>name+" "+NOTE_NAMES[evidence[key].pitch_class]+
        (evidence[key].fundamental_strength>=.08 ? " 可見" : " 待確認")).join(" · ");
    box.append(detail);
  }
  for (const candidate of comparison.candidates || []) {
    const row = document.createElement("div"), text = document.createElement("span");
    text.textContent = v2 ? playedChord(candidate.chord) : `BTC ${playedChord(candidate.chord)} · 占此段 ${Math.round(candidate.share * 100)}% 時間`;
    row.append(text);
    if (editable && !["N", "X", segment.chord].includes(candidate.chord)) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "text-button"; button.textContent = "整段改用這個";
      button.addEventListener("click", async () => {
        if (state.current?.id !== jobId || chords()[state.selected] !== segment) return;
        if (!confirm(`將 ${durationText(segment.start)}–${durationText(segment.end)} 整段改為 ${candidate.chord}？`)) return;
        segment.chord = candidate.chord;
        delete segment.comparison; delete segment.refinement; segment.manual = true;
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
    const saved = await api(`/api/jobs/${state.current.id}/chords`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method: state.method, chords: chords(),
        revision: state.current.result.chord_revisions?.[state.method] ?? 0 }),
    });
    (state.current.result.chord_revisions ||= {})[state.method] = saved.revision;
    $("#saveState").textContent = "已儲存";
    toast("修正已儲存");
  } catch (error) {
    if (error.message.includes("其他分頁")) $("#saveState").textContent = "版本衝突，請重新開啟歌曲";
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
  delete segment.refinement;
  segment.manual = true;
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

let currentVoicingLabel = null, currentVoicingIndex = 0;
function renderVoicing(label, original = label) {
  const board = $("#fretboard");
  const positions = $("#voicingPositions");
  if (currentVoicingLabel !== label) {
    currentVoicingLabel = label;
    currentVoicingIndex = 0;
    if ($("#smoothVoicings").checked && state.selected >= 0) {
      const start = Math.max(0, state.selected - 4), end = Math.min(chords().length, state.selected + 5);
      const path = ChordLabVoicings.connect(chords().slice(start, end).map(segment => playedChord(segment.chord)));
      currentVoicingIndex = path[state.selected - start] ?? 0;
    }
  }
  positions.replaceChildren();
  positions.classList.add("hidden");
  if (!label) {
    $("#selectedChord").textContent = "選擇一個和弦";
    board.className = "chord-diagram empty";
    board.innerHTML = "<span>點選和弦，查看按法與不同把位。</span>";
    $("#voicingNotes").textContent = "";
    return;
  }
  $("#selectedChord").textContent = state.capo ? `${label}（原和弦 ${original}）` : label;
  const alternatives = ChordLabVoicings.positions(label);
  if (!alternatives.length) {
    board.className = "chord-diagram empty";
    board.innerHTML = label === "N" || label === "X" ?
      "<span>此段未辨識出和弦。</span>" : "<span>這個和弦暫時沒有適合的標準吉他按法。</span>";
    $("#voicingNotes").textContent = "";
    return;
  }
  currentVoicingIndex = Math.min(currentVoicingIndex, alternatives.length - 1);
  const voicing = alternatives[currentVoicingIndex];
  for (const [index, alternative] of alternatives.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = ChordLabVoicings.caption(alternative);
    button.setAttribute("aria-pressed", String(index === currentVoicingIndex));
    button.addEventListener("click", () => {
      currentVoicingIndex = index;
      renderVoicing(label, original);
      positions.children[index]?.focus({ preventScroll: true });
    });
    positions.append(button);
  }
  positions.classList.toggle("hidden", alternatives.length < 2);
  board.className = "chord-diagram";
  board.innerHTML = ChordLabVoicings.diagram(voicing) +
    '<div class="chord-diagram-legend"><span>× 不彈</span><span>○ 空弦</span><span>● 按弦</span><span>━ 橫按</span></div>';
  $("#voicingNotes").textContent =
    `${voicing.known ? "常用按法" : "替代按法（推算）"} · 標準調弦 · 左側數字為${state.capo ? `相對 Capo ${state.capo} 的` : ""}格數`;
}
document.addEventListener("DOMContentLoaded", init);
