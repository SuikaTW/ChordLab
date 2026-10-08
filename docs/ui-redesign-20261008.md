# Quiet Studio 與舊版備份

本文件記錄歷次介面試行、還原點與驗證；索引見[實驗台帳 U02／U03](experiment-ledger.zh-TW.md)。

## Practice Room / 練習優先（第五版）

新版已選歌時收起匯入表單，桌面保留最近歌曲與「＋ 新增歌曲」；手機收起整個選歌區，
直接顯示目前歌曲、Capo／Key 與和弦／TAB。
「換歌／新增」會叫回原本匯入表單與紀錄，手機可按「回到練習」或 Escape 收起。
樂庫的「新增分析」也會展開匯入區；沒有歌曲時仍直接顯示完整匯入表單。
開關選歌區不重載音訊、不換歌曲、不刪未儲存修正；真正選另一首仍保留原有離開確認。

音軌選擇、辨識方式、速度／循環與分軌下載收進「音軌／工具」，Capo／Key 仍直接可用。
控制只移動原 DOM，不複製 ID、表單或事件；切回原版會回到原位置。
選單支援 Escape 與點擊外部關閉，有限高可捲動，中等寬度保持靠右不遮側欄。
唱片封套縮小，保留歌曲識別，讓歌名和譜面優先。

TAB 新版改為同一張連續紙面，取消逐行卡片外框；字級 11 px、弦距 26 px。
flowRows 按譜面寬度和每弦起音密度安排一至四小節／行；窄畫面或密集段落維持單小節，
足夠寬且稀疏時可以同一行顯示多小節。仍可能有非常密集的單小節重疊，不宣稱解決所有擁擠情況。
音符、時間、音高、把位、技巧、已儲存版本與 MIDI／PDF 均不修改或量化。
ResizeObserver 與風格事件只重排既有音符，不重新分析／配置指法；保留未儲存編輯與目前閱讀時間區域。
每行高度與虛擬捲動同步，避免捲到後段空白；DOM 仍只繪製鄰近譜行。
調弦設定與分析細節移到譜面下方，重要警告與未儲存提示仍可見。
正在看且已完成的建議譜不重複顯示「查看建議譜」，產生、更新、失敗重試仍保留；進階版本仍可切換。

TAB 預設使用較薄播放器，播放／進度／時間仍可操作；按「展開」恢復歌名與音量。
和弦頁可手動收起，切換內容時恢復該頁預設；偏好不跨瀏覽器記錄。
始終使用同一個主播放器與音量控制，展開／收起不改音訊來源、播放時間或音量。
原版外觀與原版播放器不受精簡模式影響。

修改前標記 ui-before-practice-20261008-fe5c0b5；原始碼封存於
/mnt/sdc/backups/chordlab-ui-practice-20261008-Y8WVDBPf/before-fe5c0b5.tar.gz。
新版截圖存同目錄 screenshots/。
tests/practice_workspace_browser_smoke.py 以五種寬度測試選歌區、樂庫新增入口、工具、
真實播放中切換播放器、音量、重排與未儲存修正、原版還原、長譜末端與 DOM 數量。
所有 API 寫入均攔截；測試的音符修正只存在隔離瀏覽器記憶體，不寫使用者資料庫。
tab-layout.test.js 新增密度與寬度排版測試。Chromium 手機尺寸不等同實機 Safari 驗證。
本版 84 個 Python、34 個 Deno 測試通過；原版／新版、色彩模式、新工作流程各五種寬度，
以及和弦跟隨／局部修正各三種寬度的瀏覽器檢查通過。公開 HTTPS 新資產回應 200。

## Graphite / 對齊與動態（第四版）

去除墨綠：淺色為象牙白、近黑字，暗色為中性黑曜石與灰黑表面，香檳金僅用於
選取框、時間游標與少量重點；主要按鈕維持高對比黑／米白。歌曲裝飾色改為低彩度的
香檳、灰紫、灰藍、玫瑰灰、暖灰，唱片增加極淡反光。

參考 [Linear 2026 的介面更新](https://linear.app/now/behind-the-latest-design-refresh)：
讓導航退居背景、邊框不搶注意力，以層次而非飽和彩色區分功能。
[Black Cream 案例](https://www.undreamstudio.com/projects/black-cream/)：借鑑黑白編排與克制的動態；
它是概念作品，不宣稱得獎，也沒有複製其素材或程式。

新 tab-alignment.css 只修正兩種風格共用的幾何：
舊版線在每列頂端，弦名置中，數字靠 -11 / -10 px 負位移貼線；
現在線、弦名、數字、延音共用每列 50% 中心線。
小字弦序改為弦名旁邊，節拍格與游標由第一條到最後一條弦，休止記號置中。
保留原本行高與虛擬捲動計算，不改音符、把位、辨識結果、MIDI 或 PDF。
style.css 仍未修改。tests/tab_geometry.py 量測可見行、弦名、按鈕與延音中心誤差 < 1 px，
並檢查音符框不跨出其行；兩種風格與淺／暗色的五種寬度測試共用此斷言。

新版動態：200 ms 內容切換與細節展開、160 ms 小選單淡入、按壓縮放、
僅桌面精準指標的卡片輕抬。歌曲標題使用 220 ms 動態且只在歌曲 ID 變更時啟用，
佇列輪詢不會反覆播放；動畫不作用於主播放器或 TAB 行。
播放中的唱片保持慢速旋轉，減少動態偏好會停用上述動畫及位移回饋。
沒有新增套件、JS 捲動攔截、背景影音或昂貴的動態模糊。

修改前 Git 標記 ui-before-graphite-20261008-7dc7e1c；完整原始碼封存於
/mnt/sdc/backups/chordlab-ui-graphite-20261008-3otTJM80/before-7dc7e1c.tar.gz。
新版截圖存同目錄 screenshots/。舊標記與原版開關仍保留。
本版驗證：84 個 Python、31 個 Deno 測試通過；新版／原版與淺／暗色各五種視窗寬度
通過幾何、播放、偏好與版面檢查；局部修正與和弦跟隨各三種寬度通過。
桌面 hover 與減少動態停用檢查通過，未做實體 iPhone／Safari 測試。

## Listening Room / 暗色模式（第三版）

頁首半黑半白圓形按鈕 → 顯示模式，可選「跟隨系統／淺色／暗色」。
預設跟隨系統，瀏覽器以 chordlab:color-mode 保留選擇；系統外觀變更會即時更新。
原版保持原有淺色外觀；返回新版時恢復原先模式。
色彩切換不重建音訊、不重新合併音軌，也不改折疊面板、編輯或播放狀態。

新增 listening-room.css：暖白／石墨底、鼠尾草綠操作重點、唱片封套式歌曲識別。
唱片與封套全部由 CSS 繪製，不是下載封面，也不代表分析出的曲風或音訊特徵。
同歌名具有一致的裝飾色，工作台、歌曲紀錄與樂庫共用。
僅當主播放器播放時，工作台的唱片緩慢旋轉；暫停即停止，減少動態偏好會停用。
沒有新增外部素材、JS 套件、音訊分析迴圈或網路請求。

設計研究：

- [Electronic Materials Office / Awwwards](https://www.awwwards.com/sites/electronic-materials-office)：Typography / Minimal 類別與黑、珊瑚、白的配色，Honorable Mention。
- [Perpetuum / Awwwards](https://www.awwwards.com/sites/perpetuum-inc)：淺／暗色方向與有辨識度的色彩，Honorable Mention。
- [teenage engineering 官方](https://teenage.engineering/)：音樂硬體的觸感與工具識別，轉譯為原創 CSS 唱片裝飾。
- [Ableton Live 官方](https://www.ableton.com/en/live/)：參考音樂工具資訊分層的方向。

借鑑方向，未複製圖片、品牌或程式碼；部分獎項單頁工具無法開啟，獎項資訊取自搜尋摘要。

本次修改前的全部已追蹤原始碼：
/mnt/sdc/backups/chordlab-ui-before-dark-20261008-wBfEoQkl/source-a25066f.tar.gz。
Git 標記 ui-before-dark-20261008-a25066f，完整保留上版暖白前的 Quiet Studio。
回退第三版必須成組還原 index.html、theme.js、app.js，避免 HTML 與 DOM 移動邏輯版本不一致；
listening-room.css 是額外視覺層，不需要改資料庫或音訊。

新增 tests/color_mode_browser_smoke.py：五種視窗寬度驗證三種色彩偏好、OS 即時變更、
持久化、原版切回、外觀控制不重疊、暗色表單／TAB／修正視窗／播放器背景、
主要按鈕與排序的 4.5:1 文字對比、真實播放不被色彩切換中斷，以及減少動態偏好。
所有使用者資料寫入 API 均攔截；僅讀取現有分析，不觸發重分析。
截圖存於上述 HDD 備份目錄 screenshots/。Chromium 測試不等同實機 Safari。
本版驗證：84 個 Python 回歸測試、31 個 Deno 測試通過；新版／原版與色彩模式各五種寬度，
和弦跟隨及局部修正各三種寬度的瀏覽器檢查通過。公開 HTTPS 新 CSS 回應 200，服務維持運行。

## 使用

頁首「版面 → 新版／原版」只切換樣式，偏好保留在此瀏覽器。
不重載頁面，不重建播放器，不改歌曲、和弦、TAB、分析模型或資料庫。
兩種風格都有固定底部播放器，手機原版會避開底部導覽列。
沒有完成的歌曲及公開樂庫不顯示播放器；切回工作台會恢復。

原有 style.css 未修改；studio.css 為依 html[data-theme] 啟用的視覺層。
theme.js 負責風格切換，以及新版說明區塊的預設折疊；player-dock.css 是兩種風格共用的播放器配置。
音訊仍只有一個 audioPlayer；不複製、不重新合併音軌。
2026-10-08 第二版使用自架 Manrope 與 Noto Sans TC 字型、CSS、原有 SVG，沒有新增前端套件、遠端字型請求、圖片、追蹤碼或背景影片。
字型取自 Google Fonts 的官方 WOFF2 切片，原檔未修改，OFL 授權及逐檔 SHA-256 保留於 app/static/fonts/。
107 個切片總共約 4.1 MB 是打包容量，不是每位訪客的下載量；依實際出現的字元按需載入，使用 font-display: swap。
CSS 使用專用家族別名，原版不會被新字型取代。

第二版加大操作字級、降低卡片框線密度；完成紀錄以歌名為主，其他資訊移到工具提示。
和弦統計與 TAB 校驗說明預設折疊，錯誤、排隊、配置中的狀態及未儲存修改仍保留。
練習與分軌下載整合到「練習／下載」；和弦時間軸提前，重查與分析說明移到譜下方。
切回原版時，練習、下載及和弦說明會回到原位置，不重新建構控制或音訊。
不編輯時收起無法使用的儲存／復原按鈕；自己的私人版本仍會顯示來源標記。
第一版新版風格另存於 Git 標記 ui-studio-v1-20261008-cc9197f，HDD 封存於
/mnt/sdc/backups/chordlab-ui-typography-20261008-bVh01oXD/studio-v1-cc9197f.tar.gz。

## 參考

- [Alphamark 的設計案例](https://www.behance.net/gallery/178314909/Alphamark)：四欄格線、規律垂直節奏與字級層次。只借鑑設計原則，沒有複製素材或程式。
- [Awwwards 極簡獲獎作品列表](https://www.awwwards.com/websites/minimal/?ads=1&page=40)：列有 Alphamark、Form Studio 等 SOTD 作品。
- [Alphamark 官方網站](https://alphamark.design/)：閱讀內容層次與導覽。某些獎項單頁及 Behance 詳細頁會擋工具存取，研究來源包含可存取的官方首頁、獎項列表與搜尋摘要。

這是 ChordLab 自行設計的操作介面，不宣稱它獲獎。

## 備份與完整回復

- 原版 Git commit：f086101a2ab435b4449ec028bb074313995cbe14。
- 永久標記：ui-classic-20261008-f086101。
- 本機 HDD：/mnt/sdc/backups/chordlab-ui-classic-20261008-YpBXsIqd/。
- classic-source-f086101.tar.gz 封存該 commit 的全部已追蹤程式；另外存 index.html、style.css、app.js。
- style.css 的 SHA-256：512ae3369eb89011e0152ba73fbd19d2a26d44b4c26abc87e044fec7471d045c。
- 封存只含程式，不含登入憑證、使用者資料庫、歌曲或音訊；歌曲仍使用既有 HDD 備份。

若只是不喜歡新版，用風格選單即可退回，保留固定播放器。
若要連播放器改動都完整退回，先保留目前未提交修改，再從此標記還原
app/static/index.html、app/static/style.css、app/static/app.js 三個檔案。
不需重置其他程式、刪除歌曲或回復資料庫。

## 驗證

tests/studio_browser_smoke.py 在 1440、1024、768、390、320 px 檢查兩種風格、
固定播放器可見可點、沒有水平溢出、切換不重建音訊、實際播放／暫停／音量、
偏好持久化與樂庫切換；只讀歌曲，寫入 API 全部攔截。
tests/chord_follow_browser_smoke.py 與 tests/local_review_browser_smoke.py 保護時間軸跟隨與局部校驗。
桌面與手機寬度截圖存於 HDD 備份的 screenshots/，不是公開網站資產。
手機寬度檢查使用 Chromium，不等同實體 iPhone／Safari 測試。
