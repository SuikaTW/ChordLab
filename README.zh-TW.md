# ChordLab

[English](README.md) | [繁體中文](README.zh-TW.md)

ChordLab 是部署於單一伺服器的私人音樂分析工作區。它可以接收使用者上傳的音訊或支援的公開媒體網址，將音訊正規化後，透過兩條獨立流程進行分析：

- 使用 Spotify Basic Pitch 辨識音符事件並產生 MIDI，再交由本機的和弦模板與 HMM 流程分析。
- 使用 Chordino（NNLS Chroma Vamp 外掛）辨識完整混音中的和弦。
- 可選擇使用 Demucs `htdemucs` 分離四個音軌。啟用後，Basic Pitch 與 Chordino 會分析 `other` 音軌，而瀏覽器可以獨立播放原曲、人聲、Bass、鼓與其他樂器音軌。

網頁支援多音軌同步播放與混音、分析方法比較、自動判定 Key、Capo／Play key 顯示、和弦編輯、吉他按法與各弦音符，以及 PDF、MIDI、ChordPro 和 JSON 匯出。

連續 TAB 不會退回使用完整混音。勾選「只用吉他聲音產生連續 TAB」後，系統會啟用實驗性的 Demucs 六軌模型，並且只轉錄分離後的吉他音軌。六軌分析一定會產生 TAB 所需的吉他 MIDI；「另外產生所有音軌 MIDI」仍是獨立選項。網頁將 TAB 切成桌機每 12 秒、手機每 8 秒一行，預設「清楚」模式會略去較弱、過短的偵測音符，也可切回「完整」查看全部結果。

使用者可以選擇把完成的分析公開至共享曲庫。公開分析可供搜尋，並依登入使用者的不重複瀏覽數或收藏數排行；網址與分析選項完全相同的公開結果會直接重複使用，以節省分析時間。私人分析只有擁有者與管理員能看見。

選用的對時歌詞功能使用獨立、僅以 CPU 執行的 faster-whisper 環境。啟用分軌時會優先辨識人聲軌，否則使用正規化後的完整混音。對時歌詞會顯示在播放器中，也會和同時段的 Play chord 一起加入 PDF。系統會濾除模型在片頭誤認成歌詞的短作詞／作曲字幕；歌唱辨識仍屬近似結果，可能需要人工校正。

## 服務管理

使用者層服務只監聽 `127.0.0.1:8788`。外部連線應經過 HTTPS 驗證／反向代理，應用程式本身也會要求使用 `.env` 中設定的帳號登入。

```bash
systemctl --user status chordlab
journalctl --user -u chordlab -f
curl http://127.0.0.1:8788/healthz
```

`chordlab-tunnel.service` 會持續執行 Cloudflare Named Tunnel，公開網址為：

```text
https://chord.suika.page
```

TLS 由 Cloudflare 公開邊緣節點終止。應用程式會把 Cloudflare 的 HTTP 請求重新導向 HTTPS，並在 HTTPS 回應中送出一年期 HSTS 政策；本機 loopback HTTP 仍可用於健康檢查。

在 `.env` 修改密碼與簽章密鑰後，重新啟動服務：

```bash
chmod 600 .env
systemctl --user restart chordlab
```

`/healthz` 是不需要登入、只回報存活狀態的最小端點。包含分析引擎細節的 `/api/health` 必須登入後才能存取。

## 管理與開放陌生人使用

管理員可開啟 `https://chord.suika.page/admin`，查看伺服器、佇列及儲存空間狀態，管理使用者權限與停權、審核公開分析、查看工作失敗的內部錯誤、永久刪除完成／失敗工作，以及檢查管理操作紀錄。本機密碼帳號與 `GOOGLE_ADMIN_EMAILS` 中的信箱是由設定檔指定的管理員；現有管理員也能將已登入過的其他 Google 帳號設為資料庫管理員。

公開使用時，非管理員預設在滾動的 24 小時內最多建立五個新分析（`CHORDLAB_DAILY_JOB_LIMIT`），並且仍受同時進行工作數限制。直接重複使用完全相同的公開分析不會消耗新的分析額度。登入工作階段預設為七天（`CHORDLAB_SESSION_DAYS`）。`CHORDLAB_APP_HOSTS` 用來限制允許的 HTTP Host。

應用程式會強制送出安全標頭、驗證會改變狀態之瀏覽器請求的同源性、使用私密 Cookie、立即套用帳號停權、只允許擁有者編輯、檢查網址連接埠與登入資訊，並且只向管理員顯示內部錯誤。仍建議在 Cloudflare 端啟用 Rate Limiting／WAF；應用程式層防護不能取代作業系統更新與不受信任媒體解碼器的隔離。

## Google 登入

在 Google Cloud 建立類型為「網頁應用程式」的 OAuth 2.0 用戶端，並登記以下完全相同的已授權重新導向 URI：

```text
https://chord.suika.page/auth/google/callback
```

接著將 `GOOGLE_OAUTH_FILE` 設為 Google 下載的 client-secret JSON 絕對路徑，或直接設定 `GOOGLE_CLIENT_ID` 與 `GOOGLE_CLIENT_SECRET`。`GOOGLE_ALLOWED_EMAILS` 是選用的逗號分隔登入白名單；留空時，任何通過驗證的 Google 帳號都能登入。`GOOGLE_ADMIN_EMAILS` 列出的帳號可以查看所有使用者的分析，其他 Google 使用者只能看見自己的工作。修改後請重新啟動 `chordlab.service`。本機密碼登入仍保留作為管理員備援方式。

## Demucs 執行環境

Demucs 與網頁及轉錄環境分開安裝於 `.venv-demucs`。標準模型會建立四個音軌；選用的實驗性 `htdemucs_6s` 模型還會分離吉他與鋼琴。詳細分軌工作會將吉他、鋼琴與其餘伴奏重新混合成 `harmony` 音軌，用於和弦與 Key 分析。這台伺服器使用僅限 CPU 的 PyTorch，並以循序佇列限制資源用量。重建環境的指令如下：

```bash
uv venv .venv-demucs --python 3.12
uv pip install --python .venv-demucs/bin/python -r requirements-demucs.txt
```

專案使用 `bin/ffmpeg` 與 `bin/ffprobe` 進行解碼和編碼，不需要安裝系統套件。第一次進行分軌時，系統會把 `htdemucs` 模型權重下載至使用者快取。

歌詞執行環境獨立安裝於 `.venv-whisper`，預設使用 `CHORDLAB_WHISPER_MODEL` 設定的多語言 `small` 模型：

```bash
uv venv .venv-whisper --python 3.12
uv pip install --python .venv-whisper/bin/python -r requirements-whisper.txt
```

分析工作使用持久化 FIFO 佇列。`CHORDLAB_ANALYSIS_WORKERS=1` 會一次處理一首歌，後續送出的工作會顯示排隊位置。`CHORDLAB_MAX_ACTIVE_PER_USER=2` 可避免單一帳號塞滿佇列。服務重新啟動後，排隊中的工作會自動恢復。

每首歌曲的大型產物儲存在應用程式 checkout 之外。`CHORDLAB_JOBS_DIR` 用來指定工作目錄；設定 `CHORDLAB_STORAGE_MOUNT` 後，資料碟若未掛載，程式會安全地停止啟動，避免誤將資料寫入 SSD。SQLite 資料目錄仍位於 SSD 上的 `data/`。

## 限制與安全性

- 網址匯入只允許設定好的公開媒體網域，並會攔截解析到私人或保留 IP 位址的網址。
- 上傳檔不只檢查副檔名：系統會攔截程式／網頁檔頭，再於 Bubblewrap 隔離沙箱內以 `ffprobe` 確認實際容器與音訊軌。檔案存放於非公開目錄、使用伺服器產生的檔名，且永遠不會當成程式執行。
- 播放清單已停用；分析工作會循序處理；上傳限制預設為 200 MB／20 分鐘。
- 系統不會下載 Spotify 音樂連結。請只上傳或處理你有權使用的音訊。
- 音樂分析屬於機率推測。獨立樂器音軌通常能得到較乾淨的 Basic Pitch MIDI；完整混音則通常建議先查看 Chordino 結果。
- 音源分離可減少其他聲音遮蔽，但分離產生的假音偶爾也會降低辨識準確度。因此此功能為選用，讓同一來源可以比較分軌前後的結果。
- 所有瀏覽器選擇兩軌以上時，伺服器都會先將所選音軌合成單一 AAC 串流再播放，避免多個播放器的起始延遲、漂移與斷音。連續點選音軌會短暫合併成一次請求；組合第一次播放時建立快取，之後直接重用，每首歌最多保留 64 種同步混音組合。
- 各軌 MIDI 使用 Basic Pitch 處理有音高的音軌，包括人聲、Bass、伴奏、吉他與鋼琴。鼓只保留音訊軌，因為有音高音符轉錄模型並不是鼓事件辨識模型。
- 六音源模型仍屬實驗功能。Demucs 上游特別提醒，鋼琴音軌可能包含明顯串音與假音。
- Key 是根據和弦軌的時長權重推算；歌曲若有轉調或和弦辨識過少，結果應只作為起點。
- 連續 TAB 使用連貫性啟發式方法，把偵測到的音高配置至標準調弦的吉他六弦。它是可彈奏的估算，不代表原演奏者實際使用的弦、琴格或演奏技巧。

## 授權與致謝

- Basic Pitch：Spotify AB，Apache-2.0。
- NNLS Chroma／Chordino：Matthias Mauch 與 Chris Cannam；由官方 Vamp 外掛發行來源下載，並固定檢查碼。
- Demucs：Meta Research，MIT License。
- faster-whisper：SYSTRAN，MIT License；Whisper 模型權重源自 OpenAI Whisper 專案。
- Noto Sans TC：Google，SIL Open Font License 1.1；隨附授權位於 `vendor/fonts/OFL.txt`。
- 不需要 root 權限、固定檢查碼的 Chordino 安裝方式參考 bkl2000 的 MIT 授權 ChordFlask 專案。
