/* One media element remains the master clock, including slow and loop playback. */
const Practice = (() => {
  let first = null, last = null, enabled = false, seeking = false, frame = 0;
  function animate() {
    if (frame || !enabled || $("#audioPlayer").paused || document.hidden) return;
    frame = requestAnimationFrame(() => { frame = 0; tick(); animate(); });
  }
  const valid = () => Number.isFinite(first) && Number.isFinite(last) && last - first >= .3;
  function refresh() {
    $("#loopToggle").disabled = !valid();
    $("#loopToggle").setAttribute("aria-pressed", String(enabled));
    $("#loopToggle").textContent = enabled ? "停止循環" : "循環播放";
    $("#loopRange").textContent = `${first === null ? "A —" : `A ${first.toFixed(1)}s`} · ${last === null ? "B —" : `B ${last.toFixed(1)}s`}`;
  }
  function speed() {
    const player = $("#audioPlayer"), rate = Number($("#playbackSpeed").value);
    player.defaultPlaybackRate = rate;
    player.playbackRate = rate;
    player.preservesPitch = true;
    player.webkitPreservesPitch = true;
  }
  function range(start, end) {
    const duration = Number(state.current?.duration || $("#audioPlayer").duration || 0);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end-start < .3 || end > duration + .1) return false;
    first = Math.max(0, start); last = Math.min(duration, end); enabled = true;
    $("#practiceTools").open = true;
    $("#audioPlayer").currentTime = first;
    refresh(); animate(); return true;
  }
  function tick() {
    const player = $("#audioPlayer");
    if (!enabled || !valid() || player.paused || seeking || state.sourceLoading) return;
    if (player.currentTime >= last || player.currentTime < first - .1) {
      seeking = true; player.currentTime = first;
    }
  }
  function reset() { first = last = null; enabled = seeking = false; cancelAnimationFrame(frame); frame = 0; refresh(); }
  function bind() {
    $("#playbackSpeed").addEventListener("change", speed);
    $("#loopA").addEventListener("click", () => { first = $("#audioPlayer").currentTime; enabled = false; refresh(); });
    $("#loopB").addEventListener("click", () => {
      last = $("#audioPlayer").currentTime; enabled = false; refresh();
      if (!valid()) toast("B 點需在 A 點之後，至少間隔 0.3 秒", true);
    });
    $("#loopToggle").addEventListener("click", () => {
      enabled = !enabled && valid(); seeking = false;
      if (enabled) $("#audioPlayer").currentTime = first;
      refresh(); animate();
    });
    $("#loopClear").addEventListener("click", reset);
    $("#loopChord").addEventListener("click", () => {
      const segment = chords()[state.selected];
      if (segment) range(segment.start, segment.end);
      else toast("先點選要練習的和弦段落");
    });
    const player = $("#audioPlayer");
    player.addEventListener("play", animate);
    document.addEventListener("visibilitychange", animate);
    player.addEventListener("loadedmetadata", speed);
    player.addEventListener("seeked", () => { seeking = false; });
    player.addEventListener("ended", () => {
      if (enabled && valid() && !state.sourceLoading) {
        seeking = false; player.currentTime = first; player.play().catch(() => {});
      }
    });
    refresh(); speed();
  }
  return { bind, reset, tick, range, inspect: () => ({ first, last, enabled }) };
})();
