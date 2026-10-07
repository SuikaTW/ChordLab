# Quiet Studio 與舊版備份

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
