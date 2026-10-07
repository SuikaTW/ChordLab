/* Personal TAB editing and windowed rendering. Audio remains the master clock. */
const TabStudio = (() => {
  const isBass = () => state.tabInstrument === "bass";
  const instrument = () => isBass() ? "bass" : "guitar";
  const capo = () => isBass() ? 0 : state.capo;
  const tuning = () => ChordLabTab.TUNINGS[state.tabTuning].midi;
  const studio = () => document.documentElement.dataset.theme === 'studio';
  const rowHeight = () => studio() ? 202 - (6 - tuning().length) * 26 : 230 - (6 - tuning().length) * 29;
  const rowGap = () => studio() ? 6 : 11;
  let layoutRowHeight = 230, layoutWidth = 0, resizeFrame = 0;
  const taskPath = (id, engine) => `/api/jobs/${id}/${isBass() ? "bass-analysis" : "guitar-analysis" + (engine === "basic_pitch" ? "" : `?engine=${engine}`)}`;
  let jobId = null,
    notes = [],
    rows = [],
    revision = 0,
    dirty = false,
    saving = false,
    undo = [],
    editIndex = null;
  let signature = "",
    loadedDocument = null,
    savedDocument = null,
    diagnostics = {},
    rhythm = {},
    windowStart = -1,
    activeRow = -1;
  let scrollFrame = 0, taskTimer = null, manualScrollAt = 0, session = 0, editSerial = 0, verificationSerial = 0, assigning = 0;
  const copy = (list) => list.map((note) => ({ ...note }));
  const context = () => ({
    instrument: instrument(),
    tuning: state.tabTuning || "standard",
    capo: capo(),
    voice: $("#tabVoice").value,
    position: $("#tabPosition").value,
    density: state.tabDensity,
    role: $("#tabRole").value,
    source_engine: state.tabEngine || "basic_pitch",
    fingering_mode: $("#tabFingering").value,
  });
  const key = () => JSON.stringify(context());

  function bind() {
    $("#revokeReference").addEventListener("click", async () => {
      const id = jobId, expected = session;
      try {
        await api(`/api/jobs/${id}/tab-reference?instrument=${instrument()}`,{method:"DELETE"});
        if (jobId !== id || session !== expected) return;
        $("#confirmReference").checked = false;
        $("#referenceExport").classList.add("hidden");
        $("#revokeReference").classList.add("hidden");
        toast("已撤回校驗資料；你的譜面保留");
      } catch (error) {
        if (jobId === id && session === expected) toast(error.message,true);
      }
    });
    $("#playVerification").addEventListener("click", async () => {
      if (!jobId || isBass() || !["verified", "cross_verified", "event_verified"].includes(state.tabEngine)) return;
      const id = jobId, player = $("#verificationPlayer"), main = $("#audioPlayer");
      const engine = state.tabEngine;
      const request = ++verificationSerial;
      const time = main.currentTime;
      main.pause();
      state.resumeOnLoad = state.resumeAfterMix = false;
      $("#guitarPreviewPlayer").pause();
      player.pause();
      player.src = `/api/jobs/${id}/verification-preview?engine=${engine}`;
      player.volume = state.volume;
      player.defaultPlaybackRate = player.playbackRate = Number($("#playbackSpeed").value);
      player.preservesPitch = player.webkitPreservesPitch = true;
      player.addEventListener("loadedmetadata", () => {
        if (jobId !== id || state.tabEngine !== engine || request !== verificationSerial) return;
        player.currentTime = Math.min(time, player.duration || time);
        player.play().catch(() => toast("請按合成預覽的播放鍵"));
      }, { once: true });
      player.addEventListener("error", () => {
        if (jobId === id && request === verificationSerial) toast("合成預覽載入失敗，請稍後重試", true);
      }, { once: true });
      player.load();
    });
    $("#audioPlayer").addEventListener("play", () => $("#verificationPlayer").pause());
    $("#verificationPlayer").addEventListener("play", () => {
      $("#audioPlayer").pause(); $("#guitarPreviewPlayer").pause();
      state.resumeOnLoad = state.resumeAfterMix = false;
    });
    $("#guitarPreviewPlayer").addEventListener("play", () => $("#verificationPlayer").pause());
    $("#tabInstrument").addEventListener("change", async () => {
      const previous = instrument();
      if (!canLeave()) {
        $("#tabInstrument").value = previous;
        return;
      }
      if (previous === "guitar") state.guitarTabEngine = state.tabEngine || "basic_pitch";
      state.tabInstrument = $("#tabInstrument").value;
      state.tabEngine = isBass() ? "basic_pitch" : state.guitarTabEngine || "basic_pitch";
      $("#tabEngine").value = state.tabEngine;
      state.tabCancel?.();
      state.tabRender = (state.tabRender || 0) + 1;
      reset(jobId);
      configure(jobId);
      state.tabJob = null;
      state.tabSource = "unavailable";
      state.tabNotes = [];
      await loadContinuousTab();
    });
    async function chooseEngine(engine) {
      const previous = state.tabEngine || "basic_pitch";
      if (!canLeave()) {
        $("#tabEngine").value = previous;
        return false;
      }
      state.tabEngine = engine;
      $("#tabEngine").value = engine;
      state.tabCancel?.();
      state.tabRender = (state.tabRender || 0) + 1;
      reset(jobId);
      state.tabJob = null;
      state.tabSource = "unavailable";
      state.tabNotes = [];
      await loadContinuousTab();
      return true;
    }
    $("#tabEngine").addEventListener("change", () => chooseEngine($("#tabEngine").value));
    $("#recommendedTab").addEventListener("click", async () => {
      const id=jobId;
      try {
        if (state.tabEngine !== "event_verified" && !await chooseEngine("event_verified")) return;
        if (jobId !== id || isBass()) return;
        const task=await api(taskPath(id,"event_verified"));
        if (jobId !== id || state.tabEngine !== "event_verified") return;
        if (task.status !== "done") await generate();
      } catch (error) {
        if (jobId === id) toast(error.message,true);
      }
    });
    $("#tabFingering").addEventListener("change", () => {
      if (!reconfigure()) return;
      signature = "";
      render();
    });
    $("#continuousTab").addEventListener("click", (event) => {
      const button = event.target.closest("[data-note-index]");
      if (!button) return;
      const note = notes.find((n) => n.index === Number(button.dataset.noteIndex));
      if (!note) return;
      if ($("#tabEditMode").checked) openEditor(note);
      else {
        $("#audioPlayer").currentTime = note.start;
        updatePlayerControls();
        update();
      }
    });
    $("#tabFlowViewport").addEventListener("scroll", () => {
      if (!scrollFrame) {
        scrollFrame = requestAnimationFrame(() => {
          scrollFrame = 0;
          drawWindow();
          update();
        });
      }
    }, { passive: true });
    const scheduleLayout = () => {
      if (resizeFrame) return;
      resizeFrame = requestAnimationFrame(() => {resizeFrame = 0; relayout();});
    };
    new ResizeObserver(() => {
      const width = $('#tabFlowViewport').clientWidth;
      if (width > 0 && Math.abs(width - layoutWidth) > 1) scheduleLayout();
    }).observe($('#tabFlowViewport'));
    window.addEventListener('chordlab:appearance', scheduleLayout);
    for (const event of ["wheel", "touchstart", "pointerdown"]) {
      $("#tabFlowViewport").addEventListener(event, () => {
        manualScrollAt = performance.now();
      }, { passive: true });
    }
    $("#tabNoteForm").addEventListener("submit", applyEdit);
    $("#tabCloseDialog").addEventListener("click", () => $("#tabNoteDialog").close());
    $("#tabDeleteNote").addEventListener("click", () => {
      remember();
      notes = notes.filter((n) => n.index !== editIndex);
      dirty = true;
      $("#tabNoteDialog").close();
      rebuild();
    });
    $("#tabEditString").addEventListener("change", () => {
      const note = notes.find((n) => n.index === editIndex);
      if (!note) return;
      const base = tuning()[Number($("#tabEditString").value)] + capo();
      $("#tabEditFret").value = String(Math.min(24 - capo(), Math.max(0, note.midi - base)));
      pitchLabel();
    });
    $("#tabEditFret").addEventListener("input", pitchLabel);
    $("#tabSave").addEventListener("click", save);
    $("#tabUndo").addEventListener("click", () => {
      if (!undo.length) return;
      editSerial++;
      loadedDocument = null;
      notes = undo.pop();
      dirty = true;
      rebuild();
    });
    $("#tabOriginal").addEventListener("click", () => {
      if (dirty && !confirm("捨棄尚未儲存的修正，回到原始譜？")) return;
      editSerial++;
      if (!dirty && !loadedDocument && savedDocument) {
        applyDocument(savedDocument);
        undo = [];
        rebuild();
        return;
      }
      loadedDocument = null;
      signature = "";
      dirty = false;
      undo = [];
      render();
    });
    for (const id of ["tabBpm", "tabMeter", "tabOffset"]) {
      $("#" + id).addEventListener("change", () => {
        if (!$("#tabBpm").checkValidity() || !$("#tabOffset").checkValidity()) return;
        rhythm = {
          bpm: Number($("#tabBpm").value),
          meter: Number($("#tabMeter").value),
          offset: Number($("#tabOffset").value),
          manual: true,
        };
        editSerial++;
        dirty = notes.length > 0;
        rebuild();
      });
    }
    $("#tabAutoRhythm").addEventListener("click", () => {
      setRhythm();
      editSerial++;
      dirty = notes.length > 0;
      rebuild();
    });
    $("#guitarPreview").addEventListener("click", preview);
    $("#guitarPreviewPlayer").addEventListener("play", () => $("#audioPlayer").pause());
    $("#audioPlayer").addEventListener("play", () => $("#guitarPreviewPlayer").pause());
    $("#generateGuitarTab").addEventListener("click", generate);
    window.addEventListener("beforeunload", (event) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
    window.matchMedia("(max-width: 720px)").addEventListener("change", () => {
      if (rows.length) rebuild();
    });
  }

  function canLeave() {
    return !dirty || confirm("尚有未儲存的 TAB 修正，確定離開？");
  }
  function configure(id) {
    $("#confirmReference").checked = false;
    $("#referenceExport").classList.add("hidden");
    $("#revokeReference").classList.add("hidden");
    $("#tabInstrument").value = instrument();
    $("#tabEngineOption").classList.toggle("hidden", isBass());
    $("#recommendedTab").classList.toggle("hidden", isBass());
    $("#recommendedTab").dataset.currentReady = 'false';
    const select = $("#tabTuning");
    select.replaceChildren();
    for (const [name, definition] of Object.entries(ChordLabTab.TUNINGS)) {
      if ((definition.instrument === "bass") !== isBass()) continue;
      const option = document.createElement("option");
      option.value = name;
      option.textContent = definition.label;
      select.append(option);
    }
    const saved = localStorage.getItem(tabStorageKey("tuning", id));
    state.tabTuning = [...select.options].some((option) => option.value === saved) ? saved : isBass() ? "bass_standard" : "standard";
    select.value = state.tabTuning;
    for (const [control, setting] of [["tabVoice", "voice"], ["tabPosition", "position"],["tabRole","role"]]) {
      const node = $("#" + control), value = localStorage.getItem(tabStorageKey(setting, id));
      node.value = [...node.options].some((option) => option.value === value) ? value : node.options[0].value;
    }
    state.tabDensity = localStorage.getItem(tabStorageKey("density", id)) === "full" ? "full" : "clean";
    $$("[data-tab-density]").forEach((button) => button.classList.toggle("active", button.dataset.tabDensity === state.tabDensity));
    $("#guitarPreview").textContent = isBass() ? "試聽 Bass" : "試聽吉他";
    $("#tabFingeringOptions").classList.toggle("hidden", isBass() || !["tabcnn", "hybrid", "cross_verified", "event_verified"].includes(state.tabEngine));
    updateInstrumentControls();
  }
  function updateInstrumentControls() {
    $("#tabTitle").textContent = isBass() ? `Bass ${tuning().length === 5 ? "五" : "四"}線譜` : "吉他六線譜";
    $("#tabDisclaimer").textContent = isBass() ? "弦／格數是推算；Bass 不使用吉他 Capo。修正與吉他譜分開儲存。" :
      "弦／格數是推算；數字相對 Capo。編輯只儲存到你的帳號。";
    const select = $("#tabEditString");
    select.replaceChildren();
    for (let string = tuning().length - 1; string >= 0; string--) {
      const option = document.createElement("option");
      option.value = String(string);
      option.textContent = `第 ${tuning().length - string} 弦 · ${NOTE_NAMES[tuning()[string] % 12]}`;
      select.append(option);
    }
  }
  function reconfigure() {
    if (!dirty || confirm("重新配置指法會捨棄尚未儲存的修正，確定繼續？")) return true;
    if (signature) {
      const previous = JSON.parse(signature);
      state.tabTuning = previous.tuning;
      if (!isBass()) state.capo = previous.capo;
      state.tabDensity = previous.density;
      $("#tabTuning").value = previous.tuning;
      if (!isBass()) $("#capoSelect").value = String(previous.capo);
      $("#tabVoice").value = previous.voice;
      $("#tabPosition").value = previous.position;
      $("#tabRole").value = previous.role || "auto";
      $("#tabFingering").value = previous.fingering_mode || "model";
      $$("[data-tab-density]").forEach((button) =>
        button.classList.toggle("active", button.dataset.tabDensity === previous.density)
      );
    }
    return false;
  }
  function reset(id) {
    assigning = 0;
    $("#continuousTab").removeAttribute("aria-busy");
    session++;
    clearTimeout(taskTimer);
    taskTimer = null;
    jobId = id;
    notes = [];
    rows = [];
    revision = 0;
    dirty = false;
    saving = false;
    undo = [];
    signature = "";
    loadedDocument = null;
    savedDocument = null;
    diagnostics = {};
    windowStart = -1;
    activeRow = -1;
    manualScrollAt = 0;
    editSerial = 0;
    $("#tabNoteDialog").close();
    $("#tabEditMode").checked = false;
    $("#guitarPreviewPlayer").pause();
    $("#guitarPreviewPlayer").removeAttribute("src");
    $("#guitarPreviewPlayer").load();
    $("#guitarPreviewPanel").classList.add("hidden");
    $("#continuousTab").replaceChildren();
    $("#tabFlowViewport").scrollTop = 0;
    $("#tabWarnings").classList.add("hidden");
    $("#verificationSummary").classList.add("hidden");
    $("#verificationPreviewPanel").classList.add("hidden");
    $("#eventReviewPanel").classList.add("hidden");
    verificationSerial++;
    $("#verificationPlayer").pause();
    $("#verificationPlayer").removeAttribute("src");
    $("#verificationPlayer").load();
    state.tabVerification = null;
    state.tabEventReview = null;
    $("#tabNoteSummary").textContent = "";
    $("#tabSource").textContent = "";
    $("#tabEngineMidi").classList.add("hidden");
    $("#tabEngineMidi").removeAttribute("href");
    $("#tabFingeringOptions").classList.toggle("hidden", isBass() || !["tabcnn", "hybrid", "cross_verified", "event_verified"].includes(state.tabEngine));
    controls();
    $("#generateGuitarTab").classList.add("hidden");
    $("#recommendedTab").disabled = false;
    $("#guitarPreview").classList.add("hidden");
  }
  function setRhythm(saved) {
    const detected = state.current?.result?.rhythm || {};
    rhythm = saved ? { ...saved } : { bpm: detected.bpm || 120, meter: 4, offset: 0, manual: false };
    $("#tabBpm").value = String(rhythm.bpm);
    $("#tabMeter").value = String(rhythm.meter);
    $("#tabOffset").value = String(rhythm.offset);
  }
  async function load(id) {
    const expectedSession = session;
    const engine = state.tabEngine || "basic_pitch";
    setRhythm();
    const [personal, task] = await Promise.all([
      api(`/api/jobs/${id}/tab?instrument=${instrument()}`),
      api(taskPath(id, engine)),
    ]);
    if (jobId !== id || expectedSession !== session) return;
    revision = personal.revision;
    $("#referenceExport").classList.toggle("hidden", !personal.reference_confirmed);
    $("#revokeReference").classList.toggle("hidden", !personal.reference_confirmed);
    $("#referenceExport").href = `/api/jobs/${id}/tab-reference?instrument=${instrument()}`;
    savedDocument = personal.document && (personal.document.instrument || "guitar") === instrument() &&
      (personal.document.source_engine || "basic_pitch") === engine ? personal.document : null;
    $("#confirmReference").checked = !!personal.reference_confirmed && !!savedDocument;
    if (savedDocument) applyDocument(savedDocument);
    taskControls(task.status, task);
    if (["queued", "working"].includes(task.status) || task.busy_engine) pollTask(id, engine);
    render();
  }
  function applyDocument(document) {
    loadedDocument = document;
    notes = copy(document.notes);
    state.tabTuning = document.tuning;
    if (!isBass()) state.capo = document.capo;
    state.tabDensity = document.density;
    $("#tabTuning").value = state.tabTuning;
    $("#tabVoice").value = document.voice;
    $("#tabPosition").value = document.position;
    $("#tabRole").value = document.role || "auto";
    $("#tabFingering").value = document.fingering_mode || "model";
    updateInstrumentControls();
    $$("[data-tab-density]").forEach((button) =>
      button.classList.toggle("active", button.dataset.tabDensity === state.tabDensity)
    );
    setRhythm(document.rhythm);
    signature = key();
    renderCapo();
    renderTimeline();
  }
  function taskControls(status, task = {}) {
    const result = state.current?.result,
      source = !isBass() && (state.current?.pure_guitar || result?.guitar_tab?.source === "original"),
      has = source || (result?.separation?.all_stems || result?.separation?.stems || []).includes(instrument());
    $("#guitarPreview").classList.toggle("hidden", !has);
    const button = $("#generateGuitarTab"),
      pending = has && (["pending", "queued", "working", "failed", "unavailable"].includes(status));
    button.classList.toggle("hidden", !pending || !state.current?.mine && !state.viewer?.admin || state.tabEngine === "event_verified" && !isBass());
    const engine = state.tabEngine || "basic_pitch";
    const unavailable = isBass() ? task.available === false : task.variants?.find((variant) => variant.engine === engine)?.available === false;
    button.disabled = ["queued", "working"].includes(status) || !!task.busy_engine || unavailable;
    button.textContent =
      { pending: "產生 TAB", queued: "TAB 排隊中", working: "正在轉譜…", failed: "重試 TAB" }[status] ||
      "產生 TAB";
    if (unavailable) button.textContent = "目前無法轉錄";
    else if (task.busy_engine && task.busy_engine !== engine) button.textContent = "等待另一版本完成";
    for (const variant of task.variants || []) {
      const option = [...$("#tabEngine").options].find((option) => option.value === variant.engine);
      if (option) option.disabled = !variant.available && !variant.ready;
    }
    const recommended=task.variants?.find((variant) => variant.engine === "event_verified");
    const primary=$("#recommendedTab");
    const selected=engine === "event_verified" && !isBass();
    primary.dataset.currentReady = String(selected && status === 'done' && !recommended?.stale);
    primary.classList.toggle("hidden", isBass() || !has || !state.current?.mine && !state.viewer?.admin && !recommended?.ready);
    primary.disabled=!!task.busy_engine || selected && ["queued","working"].includes(status) || recommended?.available === false;
    primary.textContent=selected && status === "working" ? "統整模型中…" : selected && status === "queued" ? "建議譜排隊中" :
      recommended?.stale ? "更新建議譜" : recommended?.ready || selected && status === "done" ? "查看建議譜" : "產生建議譜";
    const download = $("#tabEngineMidi");
    download.classList.toggle("hidden", status !== "done");
    if (status === "done") download.href = isBass() ? `/api/jobs/${jobId}/export/midi/bass` : `/api/jobs/${jobId}/guitar-midi/${engine}`;
    else download.removeAttribute("href");
  }
  async function generate() {
    const id = jobId;
    const engine = state.tabEngine || "basic_pitch";
    const expectedSession = session;
    $("#generateGuitarTab").disabled = true;
    try {
      const result = await api(taskPath(id, engine), { method: "POST" });
      if (jobId !== id || session !== expectedSession || (state.tabEngine || "basic_pitch") !== engine) return;
      taskControls(result.status);
      pollTask(id, engine);
      loadQueueStatus();
    } catch (error) {
      if (jobId === id && session === expectedSession && (state.tabEngine || "basic_pitch") === engine) {
        $("#generateGuitarTab").disabled = false;
        toast(error.message, true);
      }
    }
  }
  function pollTask(id, engine = state.tabEngine || "basic_pitch") {
    const expectedSession = session;
    const current = () => jobId === id && session === expectedSession && (state.tabEngine || "basic_pitch") === engine;
    clearTimeout(taskTimer);
    taskTimer = setTimeout(async () => {
      if (!current()) return;
      if (document.hidden) {
        pollTask(id, engine);
        return;
      }
      try {
        const task = await api(taskPath(id, engine));
        if (!current()) return;
        taskControls(task.status, task);
        if (["queued", "working"].includes(task.status) || task.busy_engine) {
          pollTask(id, engine);
          return;
        }
        if (task.status === "done") {
          // Another refinement may finish while this version is being edited.
          // Background polling must never reload over unsaved personal changes.
          if (dirty || saving) {
            loadQueueStatus();
            return;
          }
          const refreshed = await api(`/api/jobs/${id}?include_notes=false`);
          if (!current() || dirty || saving) return;
          state.current = refreshed;
          $("[data-method='cross_verified']")?.classList.toggle("hidden", !refreshed.result?.methods?.cross_verified?.length);
          $("[data-method='event_verified']")?.classList.toggle("hidden", !refreshed.result?.methods?.event_verified?.length);
          state.tabJob = null;
          await loadContinuousTab();
          renderStemDownloads();
          loadQueueStatus();
        }
      } catch (error) {
        if (current()) {
          toast(error.message, true);
          pollTask(id, engine);
        }
      }
    }, 2500);
  }
  async function preview() {
    if (!jobId) return;
    const id = jobId, player = $("#guitarPreviewPlayer"), main = $("#audioPlayer");
    state.resumeOnLoad = false;
    state.resumeAfterMix = false;
    main.pause();
    $("#guitarPreviewPanel").classList.remove("hidden");
    player.src = `/api/jobs/${id}/guitar-preview?start=${Math.floor(main.currentTime || 0)}&track=${instrument()}`;
    player.volume = state.volume;
    try {
      await player.play();
    } catch {
      if (jobId === id) toast("試聽尚未準備好，請按片段播放鍵再試", true);
    }
  }

  async function render() {
    if (!state.current?.result || jobId !== state.current.id) return;
    $("#fullTabPanel").classList.remove("hidden");
    if (state.resultView !== "tab" || state.page !== "workspace") return;
    if (state.tabSource !== instrument() && !loadedDocument) {
      $("#continuousTab").innerHTML =
        isBass() ? '<div class="tab-unavailable"><b>尚未產生 Bass 譜</b><span>有 Bass 分軌時，可先試聽再按「產生 TAB」。沒有 Bass 軌的歌曲需要重新選擇分軌分析。</span></div>' :
        `<div class="tab-unavailable"><b>尚未產生吉他譜</b><span>${state.current.pure_guitar || state.current.result.guitar_tab?.source === "original" ? "可直接從純吉他原音產生 TAB；若轉錄失敗，請按上方按鈕重試。" : "先試聽吉他音軌，再選「產生 TAB」。沒有吉他軌時，請重新選擇吉他分析。"}</span></div>`;
      return;
    }
    if (signature === key()) {
      state.tabCancel?.();
      state.tabRender = (state.tabRender || 0) + 1;
      rebuild();
      return;
    }
    if (loadedDocument && signature !== key()) {
      loadedDocument = null;
      toast("設定已變更，改用自動配置；已儲存版本仍保留");
    }
    const generation = state.tabRender = (state.tabRender || 0) + 1, id = jobId, expectedKey = key();
    const expectedEdit = editSerial;
    assigning = generation;
    $("#continuousTab").setAttribute("aria-busy","true");
    controls();
    $("#tabNoteSummary").textContent = "配置指法…";
    let result;
    try { result = await assignTabNotes(state.tabNotes || []); }
    finally {
      if(assigning===generation){assigning=0;$("#continuousTab").removeAttribute("aria-busy");controls();}
    }
    if (!result || generation !== state.tabRender || jobId !== id || key() !== expectedKey || editSerial !== expectedEdit) return;
    notes = copy(result.notes).filter((n) => n.start < state.current.duration).map((n) => ({
      ...n,
      end: Math.min(n.end, state.current.duration),
    }));
    diagnostics = result.diagnostics || {};
    diagnostics.omittedNotes = result.omittedCount || 0;
    signature = key();
    undo = [];
    dirty = false;
    rebuild();
  }
  function rebuild() {
    if (!state.current?.result || jobId !== state.current.id) return;
    updateInstrumentControls();
    if (!notes.length) {
      rows = [];
      windowStart = -1;
      $("#continuousTab").innerHTML =
        '<div class="tab-unavailable"><b>目前沒有音符</b><span>可試聽音軌、調整設定，或用復原／原始譜找回刪除的音。</span></div>';
      $("#tabNoteSummary").textContent = "0 音";
      controls();
      return;
    }
    const measures = ChordLabLayout.bars(state.current.duration, rhythm, state.current.result.rhythm);
    const viewport = $("#tabFlowViewport");
    layoutWidth = viewport.clientWidth;
    layoutRowHeight = rowHeight();
    rows = studio() ? ChordLabLayout.flowRows(measures, notes, Math.max(100, layoutWidth - 52)) :
      ChordLabLayout.rows(measures, window.matchMedia("(max-width: 720px)").matches ? 1 : 2);
    for (const note of notes) {
      const first = Math.max(0, ChordLabLayout.locate(rows, note.start));
      for (let i = first; i < rows.length && rows[i].start < note.end; i++) rows[i].notes.push(note);
    }
    windowStart = -1;
    activeRow = -1;
    drawWindow();
    update();
    controls();
    $("#tabNoteSummary").textContent = `${notes.length} 音 · ${
      rows.reduce((n, row) => n + row.measures.length, 0)
    } 小節${rhythm.manual ? "" : "（估計）"}`;
    $("#tabSource").textContent = loadedDocument
      ? "我的版本"
      : isBass() ? "Bass 分離軌"
      : state.tabEngine === "gaps" ? "GAPS · 實驗"
      : state.tabEngine === "tabcnn" ? "TabCNN · 實驗"
      : state.tabEngine === "hybrid" ? "整合 v2 · 實驗"
      : state.tabEngine === "verified" ? "音訊校驗 · 實驗"
      : state.tabEngine === "cross_verified" ? "交叉校驗 · 實驗"
      : state.tabEngine === "event_verified" ? "建議譜 · 尚需核對"
      : state.current.pure_guitar || state.current.result.guitar_tab?.source === "original"
      ? "純吉他"
      : "吉他分離軌";
    $("#tabSource").classList.toggle("personal", !!loadedDocument);
    $("#tabTitle").title = $("#tabSource").textContent;
    const warning = [];
    const verified = state.tabVerification, summary = $("#verificationSummary");
    summary.classList.toggle("hidden", isBass() || !["verified", "cross_verified", "event_verified"].includes(state.tabEngine) || !verified);
    $("#verificationPreviewPanel").classList.toggle("hidden", isBass() || !["verified", "cross_verified", "event_verified"].includes(state.tabEngine) || !verified);
    if (verified) summary.textContent = `校驗 ${verified.reviewed_notes} 音 · 調整 ${verified.changed_notes} 音 · ${verified.uncertain_notes} 音仍有疑點。${verified.calibrated_pitches ? `使用 ${verified.calibrated_pitches} 個私人校準音高。` : ""}音頻相似度不是正確率；原版與你的修正保留。`;
    if (verified?.version === 2) summary.textContent = `${verified.independent_models.length} 個音符模型 · ${verified.chord_sources.length} 種和弦證據 · ${verified.conflict_notes} 處交叉疑點 · 調整 ${verified.changed_notes} 音。和弦只作提示，原版保留；相似度不等於正確率。`;
    const events = state.tabEventReview;
    if (state.tabEngine === "event_verified" && events) summary.textContent += ` 補 ${events.added_notes} 音 · 起音 ${events.adjusted_onsets}／音長 ${events.adjusted_offsets || 0}／重撥 ${events.retrigger_splits || 0} 處修正 · ${events.review_candidates} 處待確認${events.original_mix_checked ? " · 已回查原曲" : ""}。`;
    const eventBox = $("#eventReviewCandidates");
    eventBox.replaceChildren();
    const reviewItems = state.tabEngine === "event_verified" && events ? [
      ...(events.suggestions || []).slice(0, 12).map((item) => ({ start: item.start, label: item.kind === "possible_retrigger" ? "疑似重新撥弦" : item.kind === "uncertain_addition" ? "補音證據不足" : "疑似假音" })),
      ...(events.repeat_evidence?.examples || []).slice(0, 4).flatMap((item) => item.occurrences.slice(0, 3).map((start) => ({ start, label: "重複樂句" }))),
    ] : [];
    $("#eventReviewPanel").classList.toggle("hidden", isBass() || !reviewItems.length);
    for (const item of reviewItems) {
      const button = document.createElement("button"), id = jobId;
      button.type = "button";
      button.className = "text-button";
      button.textContent = `${item.label} · ${durationText(item.start)}`;
      button.addEventListener("click", () => {
        if (jobId !== id) return;
        $("#verificationPlayer").pause();
        $("#audioPlayer").currentTime = Math.max(0, item.start - .2);
      });
      eventBox.append(button);
    }
    if (isBass() && diagnostics.omittedNotes) warning.push(`${diagnostics.omittedNotes} 音無法配置到目前弦格，可試 Drop D／五弦或檢查誤音`);
    const rhythmWarning = !rhythm.manual && !state.current.result.rhythm?.bpm
      ? `尚無拍點分析，暫以 ${rhythm.bpm} BPM 排版，可手動調整。`
      : "";
    if (diagnostics.crowdedOnsets) warning.push(`${diagnostics.crowdedOnsets} 處超過 ${tuning().length} 音`);
    if (diagnostics.wideShapes) warning.push(`${diagnostics.wideShapes} 處跨度過大`);
    if (diagnostics.rapidShifts) warning.push(`${diagnostics.rapidShifts} 處快速跳把位`);
    const node = $("#tabWarnings");
    node.classList.toggle("hidden", !warning.length && !rhythmWarning);
    node.textContent = rhythmWarning +
      (warning.length ? ` ${warning.join("、")}：可能有多聲部或誤判；請試聽或篩選高／低音。` : "");
  }
  function rowMarkup(row, index) {
    const width = row.end - row.start, position = (t) => (t - row.start) / width * 100;
    const boundaries = row.measures.slice(1).map((bar) =>
      `<i class="tab-barline" style="left:${position(bar.start)}%"></i>`
    ).join("");
    const beats = row.measures.flatMap((bar) => bar.beats).map((t) =>
      `<i class="tab-beat" style="left:${position(t)}%"></i>`
    ).join("");
    const rests = ChordLabLayout.rests(row.notes, row.start, row.end, 30 / rhythm.bpm).map((gap) =>
      `<span class="tab-rest" style="left:${position((gap.start + gap.end) / 2)}%" title="休止 ${
        (gap.end - gap.start).toFixed(2)
      } 秒">休</span>`
    ).join("");
    const strings = Array.from({ length: tuning().length }, (_, i) => tuning().length - 1 - i).map((string) => {
      const events = row.notes.filter((note) => note.string === string);
      const tails = events.map((note) => {
        const left = position(Math.max(row.start, note.start)), right = position(Math.min(row.end, note.end));
        return `<i class="tab-sustain" style="left:${left}%;width:${right - left}%" title="延音"></i>`;
      }).join("");
      const starts = events.filter((note) => note.start >= row.start && note.start < row.end).map((note) =>
        `<button data-note-index="${note.index}" data-tab-start="${note.start}" class="${
          note.suspicious ? "suspect " : ""
        }${note.edited ? "edited" : ""}" style="left:${
          Math.min(98, Math.max(2, position(note.start)))
        }%" title="${note.start.toFixed(2)}s · 第 ${tuning().length - string} 弦 · ${note.fret} 格${({slide:' · 人工確認滑音',hammer_on:' · 人工確認擊弦',pull_off:' · 人工確認勾弦'}[note.technique]) || ''}">${({slide:'s',hammer_on:'h',pull_off:'p'}[note.technique]) || ''}${note.fret}</button>`
      ).join("");
      return `<div class="tab-system-row"><b>${
        NOTE_NAMES[tuning()[string] % 12]
      }<small>${tuning().length - string}</small></b><div class="tab-system-string">${tails}${starts}</div></div>`;
    }).join("");
    return `<section class="tab-system" style="--tab-system-height:${rowHeight() - rowGap()}px" data-tab-system="${index}"><header><span>小節 ${
      row.measures[0].number || "前奏"
    }${
      row.measures.length > 1 ? "–" + row.measures[row.measures.length - 1].number : ""
    }</span><i></i><span>${
      durationText(row.start)
    }</span></header><div class="tab-system-body">${strings}<div class="tab-rhythm-grid">${beats}${boundaries}${rests}</div><div class="tab-system-playhead"></div></div></section>`;
  }
  function drawWindow() {
    if (state.resultView !== "tab" || !rows.length) return;
    const viewport = $("#tabFlowViewport"),
      start = Math.max(0, Math.floor(viewport.scrollTop / rowHeight()) - 2);
    const end = Math.min(rows.length, start + Math.ceil((viewport.clientHeight || 500) / rowHeight()) + 5);
    if (start === windowStart) return;
    windowStart = start;
    $("#continuousTab").innerHTML = `<div class="tab-spacer" style="height:${start * rowHeight()}px"></div>${
      rows.slice(start, end).map((row, i) => rowMarkup(row, start + i)).join("")
    }<div class="tab-spacer" style="height:${(rows.length - end) * rowHeight()}px"></div>`;
    activeRow = -1;
  }
  function update() {
    if (state.resultView !== "tab" || state.page !== "workspace" || !rows.length) return;
    const player = $("#audioPlayer"),
      index = Math.max(0, Math.min(rows.length - 1, ChordLabLayout.locate(rows, player.currentTime)));
    if (!player.paused && $("#tabFollow").checked && performance.now() - manualScrollAt > 5000) {
      const viewport = $("#tabFlowViewport"), top = index * rowHeight();
      if (top < viewport.scrollTop || top + rowHeight() > viewport.scrollTop + viewport.clientHeight) {
        viewport.scrollTop = Math.max(0, top - rowHeight());
        drawWindow();
      }
    }
    if (activeRow !== index) {
      $("#continuousTab .playing")?.classList.remove("playing");
      $(`[data-tab-system="${index}"]`)?.classList.add("playing");
      activeRow = index;
    }
    const head = $(`[data-tab-system="${index}"] .tab-system-playhead`);
    if (head) {
      const row = rows[index],
        ratio = Math.min(1, Math.max(0, (player.currentTime - row.start) / (row.end - row.start)));
      head.style.left = `calc(28px + ${ratio * 100}% - ${ratio * 28}px)`;
    }
  }
  function controls() {
    $("#tabSave").disabled = !dirty || saving || !!assigning;
    $("#tabUndo").disabled = !undo.length || !!assigning;
    $("#tabOriginal").disabled = state.tabSource !== instrument() && !savedDocument;
    $("#tabOriginal").textContent = !loadedDocument && !dirty && savedDocument ? "我的版本" : "原始譜";
    $("#tabEditMode").disabled = !notes.length || !!assigning;
    $("#tabSaveStatus").textContent = saving ? "儲存中…" : dirty ? "未儲存" : revision ? "已儲存" : "";
  }
  function relayout() {
    if (!notes.length || state.resultView !== 'tab' || state.page !== 'workspace' || !$('#tabFlowViewport').clientWidth) return;
    const viewport = $('#tabFlowViewport');
    const anchor = rows[Math.min(rows.length - 1, Math.floor(viewport.scrollTop / layoutRowHeight))]?.start || 0;
    rebuild();
    viewport.scrollTop = Math.max(0, ChordLabLayout.locate(rows, anchor)) * rowHeight();
    windowStart = -1;
    drawWindow(); update();
  }
  function remember() {
    editSerial++;
    undo.push(copy(notes));
    if (undo.length > 20) undo.shift();
    loadedDocument = null;
  }
  function openEditor(note) {
    if(assigning)return toast("正在配置指法，請稍候");
    editIndex = note.index;
    $("#tabEditString").value = String(note.string);
    $("#tabEditFret").max = String(24 - capo());
    $("#tabEditFret").value = String(note.fret);
    $("#tabEditTechnique").value = note.technique || "none";
    $("#tabEditTechnique").disabled = isBass();
    $("#tabEditInfo").textContent = `${note.start.toFixed(2)} 秒 · 改弦時會優先保留音高`;
    pitchLabel();
    $("#tabNoteDialog").showModal();
  }
  function pitchLabel() {
    const midi = tuning()[Number($("#tabEditString").value)] + capo() +
      Number($("#tabEditFret").value);
    $("#tabEditPitch").textContent = `音高 ${NOTE_NAMES[(midi + 120) % 12]}${
      Math.floor(midi / 12) - 1
    }（改格數會改音高）`;
  }
  function applyEdit(event) {
    event.preventDefault();
    const note = notes.find((n) => n.index === editIndex);
    if (!note) return;
    const string = Number($("#tabEditString").value), fret = Number($("#tabEditFret").value);
    if (!Number.isInteger(string) || string < 0 || string >= tuning().length || !Number.isInteger(fret) || fret < 0 || fret + capo() > 24) return;
    if (
      notes.some((n) =>
        n.index !== note.index && n.string === string && n.start < note.end && n.end > note.start
      )
    ) {
      toast("這條弦此時已有另一個音；請改弦，或先刪除衝突音", true);
      return;
    }
    remember();
    note.string = string;
    note.fret = fret;
    note.midi = tuning()[string] + capo() + fret;
    note.edited = true;
    note.suspicious = false;
    note.technique = isBass() ? "none" : $("#tabEditTechnique").value;
    dirty = true;
    $("#tabNoteDialog").close();
    rebuild();
  }
  async function save() {
    if (!dirty || saving) return;
    const id = jobId, expectedSession = session, expectedEdit = editSerial, expectedContext = key();
    saving = true;
    controls();
    const document = { revision, notes: copy(notes), ...context(), rhythm: { ...rhythm } };
    try {
      const confirmed = $("#confirmReference").checked;
      const result = await api(`/api/jobs/${id}/tab?instrument=${instrument()}&confirmed_reference=${confirmed}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(document),
      });
      if (jobId !== id || session !== expectedSession) return;
      revision = result.revision;
      savedDocument = result.document;
      $("#referenceExport").classList.toggle("hidden", !result.reference_confirmed);
      $("#revokeReference").classList.toggle("hidden", !result.reference_confirmed);
      $("#referenceExport").href = `/api/jobs/${id}/tab-reference?instrument=${instrument()}`;
      if (editSerial === expectedEdit && key() === expectedContext) {
        loadedDocument = result.document;
        dirty = false;
      }
      toast(result.reference_confirmed ? "已儲存，手動修正加入私人校驗資料" : "已儲存到你的帳號");
    } catch (error) {
      if (jobId === id && session === expectedSession) toast(error.message, true);
    } finally {
      if (jobId === id && session === expectedSession) {
        saving = false;
        controls();
      }
    }
  }
  return {
    bind,
    configure,
    reset,
    load,
    render,
    update,
    canLeave,
    reconfigure,
    relayout,
    inspect: () => ({
      count: notes.length,
      rowCount: rows.length,
      dirty,
      revision,
      layoutHeight:layoutRowHeight,
      maxBarsPerRow:Math.max(0,...rows.map(row => row.measures.length)),
      renderedRows: $$("[data-tab-system]").length,
    }),
  };
})();
