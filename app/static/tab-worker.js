importScripts("/static/tab-engine.js?v=5");
self.onmessage = (event) => {
  try {
    self.postMessage({ result: ChordLabTab.assign(event.data.notes, event.data.options) });
  } catch {
    self.postMessage({ error: "無法配置吉他指法，請重新開啟這首歌" });
  }
};
