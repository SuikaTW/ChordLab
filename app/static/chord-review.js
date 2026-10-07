/* Local proposals are previewed first. No automatic raw/manual chord writes. */
const LocalChordReview = (() => {
  let timer, jobId, generation = 0, proposal;
  const active = () => state.current?.id === jobId && (state.current.mine || state.viewer?.admin);
  function loop(start, end) {
    if (Practice.range(start,end)) toast("已設定循環範圍，可按播放試聽");
  }
  function render(info) {
    proposal = info;
    const busy = ["queued", "working"].includes(info.status);
    $("#reviewChords").disabled = busy;
    $("#applyChordReview").classList.toggle("hidden", info.status !== "done");
    $("#localChordReviewStatus").textContent = ({queued:"重查排隊中…",working:"正在密集檢查這一段…",
      failed:"重查失敗，可以重試。",stale:"原資料已修改，請重新檢查。",applied:"已另存局部修正版；原版保留。",pending:"選取 0.5～90 秒，確認後才套用。"}[info.status]) ||
      ("重查完成：調整 "+(info.summary?.changed_segments || 0)+" 段。以下仍是候選，不是標準答案。");
    const box = $("#localChordReviewCandidates"); box.replaceChildren();
    if (info.status !== "done") return;
    const {start,end} = info.request;
    const audition = document.createElement("button"); audition.type="button"; audition.className="text-button";
    audition.textContent="循環試聽重查範圍"; audition.onclick=()=>loop(start,end); box.append(audition);
    for (const segment of info.chords.filter(s=>s.start<end&&s.end>start).slice(0,80)) {
      const row=document.createElement("div"), text=document.createElement("span");
      const center=(Math.max(start,segment.start)+Math.min(end,segment.end))/2;
      const before=state.current.result.methods[info.method]?.find(s=>s.start<=center&&s.end>center)?.chord;
      const original=before!==segment.chord ? before : null;
      text.textContent=durationText(segment.start)+"–"+durationText(segment.end)+" · "+
        (original ? playedChord(original)+" → " : "")+playedChord(segment.chord)+(segment.manual ? " · 人工保留" : "");
      const button=document.createElement("button");button.type="button";button.className="text-button";button.textContent="試聽";
      button.onclick=()=>loop(Math.max(start,segment.start),Math.min(end,segment.end));row.append(text,button);box.append(row);
    }
  }
  async function refresh(id = jobId, current = generation) {
    clearTimeout(timer);
    try {
      const info=await api("/api/jobs/"+id+"/chord-review");
      if (current!==generation || !active()) return;
      render(info);
      if (["queued","working"].includes(info.status)) timer=setTimeout(()=>refresh(id,current),2500);
    } catch(error) {if(current===generation&&active()) $("#localChordReviewStatus").textContent=error.message;}
  }
  function open() {
    clearTimeout(timer);generation++;jobId=state.current?.id;proposal=null;
    const visible=active();$("#localChordReviewPanel").classList.toggle("hidden",!visible);
    $("#localChordReviewCandidates").replaceChildren();$("#applyChordReview").classList.add("hidden");
    if (!visible) return;
    const duration=state.current.duration||0;
    $("#reviewStart").value=0;$("#reviewEnd").value=Math.min(20,duration);
    $("#reviewEnd").max=duration;$("#reviewStart").max=duration;
    refresh();
  }
  function bind() {
    $("#reviewSelectedChord").onclick=()=>{
      const s=chords()[state.selected];if(!s)return toast("先點選一段和弦");
      $("#reviewStart").value=s.start.toFixed(2);$("#reviewEnd").value=Math.min(s.end,s.start+90).toFixed(2);
    };
    $("#nextChordDoubt").onclick=()=>{
      const entries=chords(),start=Math.max(-1,state.selected);
      let index=-1;
      for(let n=1;n<=entries.length;n++){const i=(start+n)%entries.length;if(needsReview(entries[i])){index=i;break;}}
      if(index<0)return toast("目前沒有標記的疑點");
      $$("#timeline .chord-block")[index]?.click();
      $("#reviewSelectedChord").click();loop(entries[index].start,entries[index].end);
    };
    $("#reviewChords").onclick=async()=>{
      const id=jobId,current=generation,method=state.method;
      const start=Number($("#reviewStart").value),end=Number($("#reviewEnd").value);
      if(!active()||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end-start<.5||end-start>90||end>(state.current.duration||0)+.02)
        return toast("請選取歌曲內 0.5～90 秒的範圍",true);
      $("#reviewChords").disabled=true;
      try {
        const info=await api("/api/jobs/"+id+"/chord-review",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({start,end,method})});
        if(current===generation&&active()){render(info);refresh(id,current);}
      } catch(error){if(current===generation&&active()){toast(error.message,true);$("#reviewChords").disabled=false;}}
    };
    $("#applyChordReview").onclick=async()=>{
      if(!active()||proposal?.status!=="done"||!confirm("將重查結果另存為局部修正版？原版與人工段落會保留。"))return;
      const id=jobId,current=generation;$("#applyChordReview").disabled=true;
      try {
        await api("/api/jobs/"+id+"/chord-review/apply",{method:"POST"});
        if(current!==generation||!active())return;
        const updated=await api("/api/jobs/"+id+"?include_notes=false");
        if(current!==generation||!active())return;
        state.current=updated;state.method="local_review";state.selected=-1;
        renderWorkspace();renderTimeline();renderEditor();render({status:"applied"});
      } catch(error){if(current===generation&&active())toast(error.message,true);}
      finally{$("#applyChordReview").disabled=false;}
    };
  }
  return {bind,open};
})();
