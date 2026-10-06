/* Personal TAB editing and windowed rendering. Audio remains the master clock. */
const TabStudio = (() => {
  const ROW_HEIGHT = 230;
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
  let scrollFrame = 0, taskTimer = null, manualScrollAt = 0, session = 0, editSerial = 0;
  const copy = (list) => list.map((note) => ({ ...note }));
  const context = () => ({
    tuning: state.tabTuning || "standard",
    capo: state.capo,
    voice: $("#tabVoice").value,
    position: $("#tabPosition").value,
    density: state.tabDensity,
    source_engine: state.tabEngine || "basic_pitch",
    fingering_mode: $("#tabFingering").value,
  });
  const key = () => JSON.stringify(context());

  function bind() {
    $("#tabEngine").addEventListener("change", async () => {
      const previous = state.tabEngine || "basic_pitch";
      if (!canLeave()) {
        $("#tabEngine").value = previous;
        return;
      }
      state.tabEngine = $("#tabEngine").value;
      state.tabCancel?.();
      state.tabRender = (state.tabRender || 0) + 1;
      reset(jobId);
      state.tabJob = null;
      state.tabSource = "unavailable";
      state.tabNotes = [];
      await loadContinuousTab();
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
      const base = ChordLabTab.TUNINGS[state.tabTuning].midi[Number($("#tabEditString").value)] + state.capo;
      $("#tabEditFret").value = String(Math.min(24 - state.capo, Math.max(0, note.midi - base)));
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
  function reconfigure() {
    if (!dirty || confirm("重新配置指法會捨棄尚未儲存的修正，確定繼續？")) return true;
    if (signature) {
      const previous = JSON.parse(signature);
      state.tabTuning = previous.tuning;
      state.capo = previous.capo;
      state.tabDensity = previous.density;
      $("#tabTuning").value = previous.tuning;
      $("#capoSelect").value = String(previous.capo);
      $("#tabVoice").value = previous.voice;
      $("#tabPosition").value = previous.position;
      $("#tabFingering").value = previous.fingering_mode || "model";
      $$("[data-tab-density]").forEach((button) =>
        button.classList.toggle("active", button.dataset.tabDensity === previous.density)
      );
    }
    return false;
  }
  function reset(id) {
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
    $("#tabNoteSummary").textContent = "";
    $("#tabSource").textContent = "";
    $("#tabEngineMidi").classList.add("hidden");
    $("#tabEngineMidi").removeAttribute("href");
    $("#tabFingeringOptions").classList.toggle("hidden", state.tabEngine !== "tabcnn");
    controls();
    $("#generateGuitarTab").classList.add("hidden");
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
      api(`/api/jobs/${id}/tab`),
      api(`/api/jobs/${id}/guitar-analysis${engine === "basic_pitch" ? "" : `?engine=${engine}`}`),
    ]);
    if (jobId !== id || expectedSession !== session) return;
    revision = personal.revision;
    savedDocument = personal.document && (personal.document.source_engine || "basic_pitch") === engine ? personal.document : null;
    if (savedDocument) applyDocument(savedDocument);
    taskControls(task.status, task);
    if (["queued", "working"].includes(task.status) || task.busy_engine) pollTask(id, engine);
    render();
  }
  function applyDocument(document) {
    loadedDocument = document;
    notes = copy(document.notes);
    state.tabTuning = document.tuning;
    state.capo = document.capo;
    state.tabDensity = document.density;
    $("#tabTuning").value = state.tabTuning;
    $("#tabVoice").value = document.voice;
    $("#tabPosition").value = document.position;
    $("#tabFingering").value = document.fingering_mode || "model";
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
      source = state.current?.pure_guitar || result?.guitar_tab?.source === "original",
      has = source || (result?.separation?.all_stems || result?.separation?.stems || []).includes("guitar");
    $("#guitarPreview").classList.toggle("hidden", !has);
    const button = $("#generateGuitarTab"),
      pending = has && (["pending", "queued", "working", "failed", "unavailable"].includes(status));
    button.classList.toggle("hidden", !pending || !state.current?.mine && !state.viewer?.admin);
    const engine = state.tabEngine || "basic_pitch";
    const unavailable = task.variants?.find((variant) => variant.engine === engine)?.available === false;
    button.disabled = ["queued", "working"].includes(status) || !!task.busy_engine || unavailable;
    button.textContent =
      { pending: "產生 TAB", queued: "TAB 排隊中", working: "正在轉譜…", failed: "重試 TAB" }[status] ||
      "產生 TAB";
    if (unavailable) button.textContent = "引擎尚未安裝";
    else if (task.busy_engine && task.busy_engine !== engine) button.textContent = "等待另一版本完成";
    for (const variant of task.variants || []) {
      const option = [...$("#tabEngine").options].find((option) => option.value === variant.engine);
      if (option) option.disabled = !variant.available && !variant.ready;
    }
    const download = $("#tabEngineMidi");
    download.classList.toggle("hidden", status !== "done");
    if (status === "done") download.href = `/api/jobs/${jobId}/guitar-midi/${engine}`;
    else download.removeAttribute("href");
  }
  async function generate() {
    const id = jobId;
    const engine = state.tabEngine || "basic_pitch";
    $("#generateGuitarTab").disabled = true;
    try {
      const result = await api(`/api/jobs/${id}/guitar-analysis${engine === "basic_pitch" ? "" : `?engine=${engine}`}`, { method: "POST" });
      if (jobId !== id || (state.tabEngine || "basic_pitch") !== engine) return;
      taskControls(result.status);
      pollTask(id, engine);
      loadQueueStatus();
    } catch (error) {
      if (jobId === id && (state.tabEngine || "basic_pitch") === engine) {
        $("#generateGuitarTab").disabled = false;
        toast(error.message, true);
      }
    }
  }
  function pollTask(id, engine = state.tabEngine || "basic_pitch") {
    clearTimeout(taskTimer);
    taskTimer = setTimeout(async () => {
      if (jobId !== id || (state.tabEngine || "basic_pitch") !== engine) return;
      if (document.hidden) {
        pollTask(id, engine);
        return;
      }
      try {
        const task = await api(`/api/jobs/${id}/guitar-analysis${engine === "basic_pitch" ? "" : `?engine=${engine}`}`);
        if (jobId !== id || (state.tabEngine || "basic_pitch") !== engine) return;
        taskControls(task.status, task);
        if (["queued", "working"].includes(task.status) || task.busy_engine) {
          pollTask(id, engine);
          return;
        }
        if (task.status === "done") {
          const current = await api(`/api/jobs/${id}?include_notes=false`);
          if (jobId !== id || (state.tabEngine || "basic_pitch") !== engine) return;
          state.current = current;
          state.tabJob = null;
          await loadContinuousTab();
          renderStemDownloads();
          loadQueueStatus();
        }
      } catch (error) {
        if (jobId === id && (state.tabEngine || "basic_pitch") === engine) {
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
    player.src = `/api/jobs/${id}/guitar-preview?start=${Math.floor(main.currentTime || 0)}`;
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
    if (state.tabSource !== "guitar" && !loadedDocument) {
      $("#continuousTab").innerHTML =
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
    $("#tabNoteSummary").textContent = "配置指法…";
    const result = await assignTabNotes(state.tabNotes || []);
    if (!result || generation !== state.tabRender || jobId !== id || key() !== expectedKey) return;
    notes = copy(result.notes).filter((n) => n.start < state.current.duration).map((n) => ({
      ...n,
      end: Math.min(n.end, state.current.duration),
    }));
    diagnostics = result.diagnostics || {};
    signature = key();
    undo = [];
    dirty = false;
    rebuild();
  }
  function rebuild() {
    if (!state.current?.result || jobId !== state.current.id) return;
    if (!notes.length) {
      rows = [];
      windowStart = -1;
      $("#continuousTab").innerHTML =
        '<div class="tab-unavailable"><b>目前沒有音符</b><span>可試聽吉他、調整設定，或用復原／原始譜找回刪除的音。</span></div>';
      $("#tabNoteSummary").textContent = "0 音";
      controls();
      return;
    }
    const measures = ChordLabLayout.bars(state.current.duration, rhythm, state.current.result.rhythm);
    rows = ChordLabLayout.rows(measures, window.matchMedia("(max-width: 720px)").matches ? 1 : 2);
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
      : state.tabEngine === "gaps" ? "GAPS · 實驗"
      : state.tabEngine === "tabcnn" ? "TabCNN · 實驗"
      : state.current.pure_guitar || state.current.result.guitar_tab?.source === "original"
      ? "純吉他"
      : "吉他分離軌";
    const warning = [];
    const rhythmWarning = !rhythm.manual && !state.current.result.rhythm?.bpm
      ? `尚無拍點分析，暫以 ${rhythm.bpm} BPM 排版，可手動調整。`
      : "";
    if (diagnostics.crowdedOnsets) warning.push(`${diagnostics.crowdedOnsets} 處超過六音`);
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
    const strings = [5, 4, 3, 2, 1, 0].map((string) => {
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
        }%" title="${note.start.toFixed(2)}s · 第 ${6 - string} 弦 · ${note.fret} 格">${note.fret}</button>`
      ).join("");
      return `<div class="tab-system-row"><b>${
        NOTE_NAMES[ChordLabTab.TUNINGS[state.tabTuning].midi[string] % 12]
      }<small>${6 - string}</small></b><div class="tab-system-string">${tails}${starts}</div></div>`;
    }).join("");
    return `<section class="tab-system" data-tab-system="${index}"><header><span>小節 ${
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
      start = Math.max(0, Math.floor(viewport.scrollTop / ROW_HEIGHT) - 2);
    const end = Math.min(rows.length, start + Math.ceil((viewport.clientHeight || 500) / ROW_HEIGHT) + 5);
    if (start === windowStart) return;
    windowStart = start;
    $("#continuousTab").innerHTML = `<div class="tab-spacer" style="height:${start * ROW_HEIGHT}px"></div>${
      rows.slice(start, end).map((row, i) => rowMarkup(row, start + i)).join("")
    }<div class="tab-spacer" style="height:${(rows.length - end) * ROW_HEIGHT}px"></div>`;
    activeRow = -1;
  }
  function update() {
    if (state.resultView !== "tab" || state.page !== "workspace" || !rows.length) return;
    const player = $("#audioPlayer"),
      index = Math.max(0, Math.min(rows.length - 1, ChordLabLayout.locate(rows, player.currentTime)));
    if (!player.paused && $("#tabFollow").checked && performance.now() - manualScrollAt > 5000) {
      const viewport = $("#tabFlowViewport"), top = index * ROW_HEIGHT;
      if (top < viewport.scrollTop || top + ROW_HEIGHT > viewport.scrollTop + viewport.clientHeight) {
        viewport.scrollTop = Math.max(0, top - ROW_HEIGHT);
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
    $("#tabSave").disabled = !dirty || saving;
    $("#tabUndo").disabled = !undo.length;
    $("#tabOriginal").disabled = state.tabSource !== "guitar" && !savedDocument;
    $("#tabOriginal").textContent = !loadedDocument && !dirty && savedDocument ? "我的版本" : "原始譜";
    $("#tabEditMode").disabled = !notes.length;
    $("#tabSaveStatus").textContent = saving ? "儲存中…" : dirty ? "未儲存" : revision ? "已儲存" : "";
  }
  function remember() {
    editSerial++;
    undo.push(copy(notes));
    if (undo.length > 20) undo.shift();
    loadedDocument = null;
  }
  function openEditor(note) {
    editIndex = note.index;
    $("#tabEditString").value = String(note.string);
    $("#tabEditFret").max = String(24 - state.capo);
    $("#tabEditFret").value = String(note.fret);
    $("#tabEditInfo").textContent = `${note.start.toFixed(2)} 秒 · 改弦時會優先保留音高`;
    pitchLabel();
    $("#tabNoteDialog").showModal();
  }
  function pitchLabel() {
    const midi = ChordLabTab.TUNINGS[state.tabTuning].midi[Number($("#tabEditString").value)] + state.capo +
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
    if (!Number.isInteger(fret) || fret < 0 || fret + state.capo > 24) return;
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
    note.midi = ChordLabTab.TUNINGS[state.tabTuning].midi[string] + state.capo + fret;
    note.edited = true;
    note.suspicious = false;
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
      const result = await api(`/api/jobs/${id}/tab`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(document),
      });
      if (jobId !== id || session !== expectedSession) return;
      revision = result.revision;
      savedDocument = result.document;
      if (editSerial === expectedEdit && key() === expectedContext) {
        loadedDocument = result.document;
        dirty = false;
      }
      toast("已儲存到你的帳號");
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
    reset,
    load,
    render,
    update,
    canLeave,
    reconfigure,
    inspect: () => ({
      count: notes.length,
      rowCount: rows.length,
      dirty,
      revision,
      renderedRows: $$("[data-tab-system]").length,
    }),
  };
})();
