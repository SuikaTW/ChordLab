# ChordLab

[English](README.md) | [繁體中文](README.zh-TW.md)

ChordLab 是部署於單一伺服器的私人音樂分析工作區。它可以接收使用者上傳的音訊或支援的公開媒體網址，將音訊正規化後，透過兩條獨立流程進行分析：

- 使用 Spotify Basic Pitch 辨識音符事件並產生 MIDI，再交由本機的和弦模板與 HMM 流程分析。
- 使用 Chordino（NNLS Chroma Vamp 外掛）辨識完整混音中的和弦。
- 選用 BTC-ISMIR19 的 170 類和弦模型交叉比對 Chordino，保留原本和弦與時間邊界，只標記不同判斷；一致不等於正確。
- 可選擇使用 Demucs `htdemucs` 分離四個音軌。啟用後，Basic Pitch 與 Chordino 會分析 `other` 音軌，而瀏覽器可以獨立播放原曲、人聲、Bass、鼓與其他樂器音軌。

網頁支援多音軌同步播放與混音、分析方法比較、自動判定 Key、Capo／Play key 顯示、和弦編輯、吉他按法與各弦音符，以及 PDF、MIDI、ChordPro 和 JSON 匯出。

連續 TAB 不會退回使用完整混音。「和弦＋吉他譜」會先分離吉他，預設先試聽，再選擇是否產生吉他 MIDI／TAB；各軌 MIDI 仍是獨立選項。來源已是單把吉他時，可選純吉他模式跳過分離。譜面以估計小節排列，桌機每行兩小節、手機每行一小節；「簡潔」略去極短、極弱音符，「完整」保留更多結果。

使用者可以選擇把完成的分析公開至共享曲庫。公開分析可供搜尋，並依登入使用者的不重複瀏覽數或收藏數排行；網址與分析選項完全相同的公開結果會直接重複使用，以節省分析時間。私人分析只有擁有者與管理員能看見。

選用的對時歌詞功能使用獨立、僅以 CPU 執行的 faster-whisper 環境。啟用分軌時會優先辨識人聲軌，否則使用正規化後的完整混音。對時歌詞會顯示在播放器中，也會和同時段的 Play chord 一起加入 PDF。系統會濾除模型在片頭誤認成歌詞的短作詞／作曲字幕；歌唱辨識仍屬近似結果，可能需要人工校正。

## 吉他辨識實驗

在歌曲的「吉他六線譜」上方選擇「辨識」：原版 Basic Pitch、GAPS 音符、TabCNN 弦位、整合 TAB v2。未產生的版本按「產生 TAB」，完成後可切換比較及下載該版本 MIDI。只有歌曲擁有者／管理員能啟動；公開歌曲的其他使用者只能讀取已完成結果。各版本獨立存放，不覆蓋原版音符、和弦或個人修譜。重啟可恢復排隊；同一首歌同時只能跑一個進階分析。

GAPS 輸出音高、起音和結束時間，仍使用現有指法搜尋；TabCNN 額外提供弦位線索，可在進階設定選「參考模型弦位」或「重新配置易彈把位」。模型弦位只適用標準調弦、Capo 0、0–19 格，其他設定會退回音高配置。TabCNN 連續撥同一格可能合併，模型機率也不等於正確率。

兩段 EGSet12 初步測試：原版音高＋起音 F1 為 0.837／0.831，GAPS 為 0.984／0.969；但 GAPS 的結束時間並非兩段都較好，TabCNN 的音符辨識也未勝過原版。因此保留原版預設，兩個新模型都標為實驗。這是模型作者的公開測試集，不是獨立盲測，更不是所有歌曲的準確率。

整合 TAB v2 不合併兩份音符清單：保留 GAPS 音高、起音、延音與同音連彈；將 TabCNN 中符合音高的多個弦位候選送入整句指法搜尋。低證據不強制指定弦位；非標準調弦或 Capo 不為 0 時忽略模型弦位。延音收尾僅記錄建議，不自動裁切。HDD 保存壓縮的模型證據，供後續檢查，不公開為任意檔案下載。

EGSet01／07 的「參考弦格一致率」（80 ms 起音容差、最大一對一配對、除以所有參考音符）從 GAPS＋原指法搜尋的 54.3%／37.5%，提高到整合 v2 的 73.9%／62.5%。音高與起音完全沿用 GAPS，並沒有再提高音符辨識率；不能用此小樣本推算真實歌曲準確率。可重跑 `tools/benchmark_guitar.py` 及 `tools/evaluate_fingering.js ... model` 比較。

### 和弦 v2（實驗）

和弦頁按「分析和弦 v2（實驗）」，完成後在辨識方式中切換。自製解碼器以 CQT 高音區證據、獨立低音支持、兩個引擎的候選及前後連續性重新切段，不強制貼齊拍點或固定流行歌曲和弦進行。已有 Bass 分軌且未被隱藏時才用獨立 Bass；否則低音區只是較弱線索。只在持續且明顯的獨立低音證據下提出轉位；延伸和弦必須已有引擎候選，不憑空增加 9／11／13。

原版與已儲存修正仍保留，完成後不自動切換或更改 Key。不確定的段落標記候選，但分數不是正確率，也不代表整段每個位置都相同。v2 共用持久化佇列、帳號上限與進階分析每日額度；失敗可重試、不讓原歌曲變成失敗。原始產物存在 HDD 的 `harmony-v2.json`。受控音訊測試驗證錯誤基準、和弦切換、靜音；真實歌曲尚無人工和弦標註，因此尚不能宣稱準確率提升或取代預設。

```bash
.venv-guitar/bin/python tests/guitar_refinement_checks.py
.venv-guitar/bin/python tests/harmony_worker_checks.py
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
bin/deno test tests/tab-engine.test.js tests/tab-layout.test.js tests/chord-theory.test.js
```

安裝、權重來源／授權及評估方法見 [吉他模型說明](vendor/guitar/README.md)。音訊、測試資料與分析結果留在 HDD；模型與獨立 `.venv-guitar` 留在 SSD。既有歌曲不會自動全部重跑。

## 雙引擎和弦比對

執行 `bash scripts/install-btc.sh` 安裝獨立 CPU 環境與官方預訓練權重，重新啟動服務後，新分析會自動執行 BTC＋Chordino 比對。兩者使用同一份分析音訊。頁面上的圓點表示分歧，點選可看 BTC 候選及其占這一段的時間比例；此比例不是正確率。擁有者／管理員可確認後將整段改用候選，原始 Chordino 結果仍保留。既有歌曲不會自動重跑或覆寫人工修正；管理者可在佇列空閒時使用：

```bash
.venv/bin/python tools/backfill_chord_comparison.py --job SONG_JOB_ID
```

補分析後從「雙引擎比對」查看，不會自動改變既有歌曲所選的分析方式。設定 `CHORDLAB_BTC_ENABLED=false` 並重啟服務，可停用新工作的 BTC。BTC 失敗時仍保留原本結果。

權重固定來源版本並驗證 SHA-256；推論使用網路隔離沙箱與受限權重載入。模型支援 14 種和弦性質，不含完整 9／11／13 與轉位辨識，不會直接提升吉他音符／TAB 的準確度。模型分數未經校準；真正的準確度須以人工標註音訊評估。

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

專案使用 `bin/ffmpeg` 與 `bin/ffprobe` 進行解碼和編碼，不需要安裝系統套件。YouTube 匯入還需要 yt-dlp 的 JavaScript 執行環境；`uv sync` 會安裝 `yt-dlp-ejs`，再執行 `scripts/install-deno.sh` 安裝已固定版本並驗證 SHA-256 的 Deno。第一次進行分軌時，系統會把 `htdemucs` 模型權重下載至使用者快取。

歌詞執行環境獨立安裝於 `.venv-whisper`，預設使用 `CHORDLAB_WHISPER_MODEL` 設定的多語言 `small` 模型：

```bash
uv venv .venv-whisper --python 3.12
uv pip install --python .venv-whisper/bin/python -r requirements-whisper.txt
```

分析工作使用持久化 FIFO 佇列。`CHORDLAB_ANALYSIS_WORKERS=1` 會一次處理一首歌，後續送出的工作會顯示排隊位置。`CHORDLAB_MAX_ACTIVE_PER_USER=2` 可避免單一帳號塞滿佇列。服務重新啟動後，排隊中的工作會自動恢復。

每首歌曲的大型產物儲存在應用程式 checkout 之外。`CHORDLAB_JOBS_DIR` 用來指定工作目錄；設定 `CHORDLAB_STORAGE_MOUNT` 後，資料碟若未掛載，程式會安全地停止啟動，避免誤將資料寫入 SSD。SQLite 資料目錄仍位於 SSD 上的 `data/`。

## 吉他 TAB

完整歌曲請選「只用吉他聲音產生連續 TAB」，先分離六軌。若網址或音檔已是純吉他獨奏／獨立音軌，可改選「來源已是純吉他，直接產生 TAB」，跳過分離並保留原音；含人聲或完整樂團的來源不適合這個選項。

吉他專用轉錄設定保留較短的音符，並提高起音門檻以降低短音誤報。TAB 指法使用多個候選路徑考慮前後音符、和弦跨度與換把，同音連彈會保留為獨立事件。可選標準調弦、Drop D、DADGAD、降半音及降全音，並使用上方 Capo 設定；兩者必須符合演奏來源。調弦設定只影響連續 TAB，和弦按法圖仍使用標準調弦。

既有分析會立即使用新版指法配置，但要重新分析才會重新辨識短音。來源相同但仍使用舊吉他轉錄設定的公開分析不會自動重用。音高轉錄與弦／格數配置仍可能出錯，特別是失真、泛音、多把吉他、分軌失真與特殊奏法；合理且可彈的指法不代表原演奏者的指法。

驗證方式：

```bash
bin/deno test tests/tab-engine.test.js
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
# 載入與 chordlab.service 相同的環境變數後比較短音訊；不修改既有歌曲
.venv/bin/python tools/evaluate_guitar_tab.py --audio /absolute/path/to/guitar.wav
```

評估工具的合成音訊具有已知音符答案，可量測起音／音高配對；真實歌曲若沒有人工對照譜，只能比較輸出的變化，不能從音符數量推算準確率。

## 限制與安全性

### 練習工作台、私人 TAB 與效能

- 匯入先選用途：和弦＋吉他譜、只看和弦、純吉他錄音、分軌 MIDI。細項收在進階選項；移除合成和弦試播、一般頁面的引擎狀態和重複的長說明。
- 「先試聽，再產生 TAB」預設啟用。六軌分離及主分析完成後，先聽 20 秒吉他片段，再由擁有者或管理員加入 TAB 轉錄佇列；也可關閉此選項直接轉錄。純吉他來源仍直接轉錄。
- TAB 可改弦／格數、刪除、復原最多 20 次、比較原始自動配置與自己的版本。修正存在 SQLite `user_tabs`，以歌曲與登入身分為索引，不改公開歌曲或其他人的譜。跨分頁同版本儲存會回應 409，不靜默覆寫。
- 自動拍點使用 librosa；小節預設每四拍，**不自動辨識強拍、拍號或原譜的節奏記號**。可手動改 BPM、每小節拍數、第一拍位置。顯示休止區間及延音線，不量化／移動原始音符。安靜或自由速度片段辨識不到拍點時，暫以 120 BPM 排版並提示修正。
- 超過六音、跨度過大、快速跳把位只表示需要檢查，不是多把吉他的可靠分類。聲部篩選仍不能真正分離木吉他與電吉他。
- 長 TAB 僅建立可見行附近的 DOM；離開 TAB 不更新其播放游標。和弦與歌詞以二分搜尋定位，只切換目前項目的樣式；手動滑動歌詞或譜面時暫停跟隨五秒，TAB 也可關閉跟隨。
- 一般歌曲檢視以 `include_notes=false` 減少初始 JSON；點開 TAB 才下載吉他音符。原本完整的 API 回應仍維持預設相容。
- 下載預備池最多兩個同時下載、八筆預備紀錄；容量滿時仍可正常排入分析佇列。重型分析與 TAB 轉錄共用原分析佇列；TAB 工作存在 `guitar_tasks`，重啟可恢復，並計入帳號的同時工作上限。
- 試聽／混音使用獨立兩執行緒、最多八筆短工作；容量滿回應 429，已完成的快取仍直接播放。取消 HTTP 請求不會提前釋放正在處理的容量。重型子程序限制數學函式庫執行緒，減少擠占互動操作。
- 單軌播放也使用 AAC 串流快取，降低手機傳輸量；分析及 WAV 下載仍使用原本的無損音軌，不以壓縮播放檔重新分析。

既有歌曲可在佇列空閒時補拍點，不重新分離或轉錄：

```bash
# 使用與服務相同的 CHORDLAB_JOBS_DIR、CHORDLAB_STORAGE_MOUNT
.venv/bin/python tools/backfill_rhythm.py --all
```

辨識準確度評估也支援人工參考音符：

```bash
.venv/bin/python tools/evaluate_guitar_tab.py --audio /absolute/guitar.wav \
  --start 20 --seconds 25 --reference /absolute/reference.json --tuning standard --capo 0
```

`reference.json` 是音符陣列，如 `[{"start":0.5,"midi":64,"string":5,"fret":0}]`。時間相對於裁切片段；`string` 用 0 表示最低第六弦、5 表示最高第一弦。弦／格數可省略。工具分開報告音高／起音配對、顯示 TAB 的配對，以及與人工參考弦格的一致率；一致率不代表那是唯一正確的指法。合成音訊的高分不代表真實歌曲也有相同準確度。

### 弱音軌與多把吉他

分軌後以 0.25 秒窗口比較音軌與原曲的 RMS 強度，預設隱藏近乎靜音、極弱的輸出，播放器與 WAV／MIDI 下載清單一致。短暫出現但明顯的聲音會保留；辨識失敗則保留音軌。這不是樂器存在與否的分類器，明顯串音仍可能被保留。原始分軌不刪除，可勾選「顯示弱音軌」查看；新分析只轉錄保留音軌的 MIDI。

TAB 新增「同時起音只取最高音／最低音」及偏好把位（相對 Capo），選項依歌曲儲存在瀏覽器。聲部篩選只處理相距 25 毫秒內的起音，不能把電吉他／木吉他或兩位演奏者真正分離，異步重疊仍可能混雜。偏好把位是指法搜尋的軟性偏好，不會為了限制把位丟棄必須超出範圍的音。最可靠的輸入仍是單把吉他獨立錄音。

既有分析可使用服務相同的環境變數執行 `.venv/bin/python tools/backfill_stem_activity.py` 更新弱音軌資訊；不刪除檔案、不修改 MIDI／和弦，並避免覆蓋同步編輯中的資料。

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
