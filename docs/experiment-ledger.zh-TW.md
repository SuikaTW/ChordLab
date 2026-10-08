# ChordLab 實驗台帳

這份台帳於 2026-10-08 依既有 README、專題文件、已追蹤的評測 JSON、HDD 原始報告及 Git 紀錄回溯建立。它收錄**目前能追溯的歷次實驗與試行**，不把沒有留下數據的歷史改動補寫成「已證明有效」。新實驗應追加紀錄，不覆蓋舊結果；演算法、參數、資料集或評分方式變動時建立新編號。

「已採用」指功能保留或目前使用，**不等於已證明辨識更準**。「選用」表示使用者可明確啟用；「未啟用」表示實驗程式／資料保留，但不作為預設。音高／起音 F1、音長 F1、TAB 弦格一致率、和弦時間一致率不能互相比成同一指標。GuitarSet／EGSet 的資料可能與模型訓練重疊，以下數字不是獨立盲測或新歌曲的預期準確率。

## 辨識與譜面

| 編號／時間 | 嘗試與可核對結果 | 決定 | 證據 |
| --- | --- | --- | --- |
| R01 · 10/06 | Basic Pitch 音符／MIDI、Chordino 和弦作為初始基準；早期沒有完整人工對照評分。 | 保留基準 | [初始版本](../README.zh-TW.md)、Git `5ea4f33` |
| R02 · 10/06–07 | Demucs 四軌、選用六軌及純吉他來源；分軌可減少遮蔽，也可能帶入串音／假音，當時沒有同錄音、人工對照的獨立分軌準確率。 | 選用 | [README：分軌與限制](../README.zh-TW.md)、Git `423e746`／`c65418c` |
| R03 · 10/07 | BTC 170 類與 Chordino 比對，標出歧見，不將「兩模型一致」視作正確；BTC 不含所有延伸和弦／轉位，當時無獨立真歌證據可取代 Chordino。 | 選用比對 | [README：雙引擎](../README.zh-TW.md)、Git `d6d45e7` |
| R04 · 10/07 | GAPS、TabCNN：兩段 EGSet12 的 Basic Pitch 音高＋起音 F1 為 0.837／0.831，GAPS 為 0.984／0.969；TabCNN 音符辨識未勝原版，音長也不是兩段都較好。 | 各版保留、標實驗 | [模型來源與評估](../vendor/guitar/README.md)、[README：吉他辨識](../README.zh-TW.md)、Git `335f487` |
| R05 · 10/07 | 整合 TAB v2：沿用 GAPS 音高與時間，TabCNN 只提供弦格候選。EGSet01／07 參考弦格一致率由 54.3%／37.5% 變為 73.9%／62.5%；**音符辨識率沒有因此提高**。 | 保留獨立實驗版 | [模型說明](../vendor/guitar/README.md)、Git `c65418c` |
| R06 · 10/07 | 和弦 v2：CQT、高低音、Bass 情境與候選連續性；受控音訊測試通過，但當時缺可代表真歌的人工和弦評分，不能宣稱勝過 Chordino。 | 選用、不取代基準 | [README：和弦 v2](../README.zh-TW.md)、Git `c65418c` |
| R07 · 10/07 | Bass TAB：獨立四／五弦、低八度、Drop D 與較短音設定；測到功能與音高／調弦約束，**尚無人工 Bass 譜準確率**。 | 選用 | [README：Bass TAB](../README.zh-TW.md)、Git `6b91305` |
| R08 · 10/07 | 音訊重合成校驗、私人確認音色樣本：合成音訊與保守防護測試；自動結果不當訓練標籤。當時沒有獨立真歌改善數值。 | 選用校驗 | [README：音訊校驗](../README.zh-TW.md)、`tools/benchmark_verification.py`、Git `84e0904` |
| R09 · 10/07 | 獨立模型交叉校驗：音符模型家族去重，和弦僅作弱線索，回查原音；合成錯音測試不是公開歌曲準確率。 | 選用版本 | [README：交叉校驗](../README.zh-TW.md)、`tools/benchmark_cross_verification.py`、Git `1a104a8` |
| R10 · 10/07–08 | TAB 開弦豁免、延音／移把成本、技法與連續搜尋、和弦圖不同把位：改善可演奏性的規則與測試；缺單獨的真實錄音消融評分。 | 已採用規則；不宣稱原指法 | [README：TAB](../README.zh-TW.md)、Git `a40b8f5`／`8997a29`／`03b007f` |
| R11 · 10/08 | 建議譜事件校驗，在跨曲風 GuitarSet 12 段的音高＋起音 micro-F1 約 0.8994→0.8997；回歸組 0.9368→0.9360，仍有錯補音。和弦完整標籤時間一致率 Chordino／建議版同為 0.3716。 | 保留建議版，不能宣稱全面提升 | [固定結果 JSON](../benchmarks/evaluation-20261008.json)、Git `03b007f`／`dc050fe` |
| R12 · 10/08 | 兩種衍生壓力案例（軟失真、程序鼓），只完成預備八例中的兩例；**不是真實電吉他或樂團**，不能算獨立樣本。 | 保留診斷，不作發布證據 | [固定結果 JSON](../benchmarks/evaluation-20261008.json)、[來源登錄](../benchmarks/reference_sources.json)、Git `dc050fe` |
| R13 · 10/08 | 長和弦內部聲學切點、局部重查與 revision 6；可預覽並由人確認，對照集的和弦分數未顯示改善。 | 局部重查可用；不自動取代原版 | [README：主動疑點](../README.zh-TW.md)、[固定結果 JSON](../benchmarks/evaluation-20261008.json)、Git `03b007f` |
| R14 · 10/08 | 五項情境實驗：全面細修和弦邊界在回歸組 F1 0.3457→0.2222；快速音符＋指法的音高／起音 F1 0.899718→0.899487；重複樂句只提示回聽，不自動補音。288 段合成音訓練的錯音提示在真實錄音精確率約 0.138。 | 邊界／快速音符／訓練模型未設預設；回聽提示保留 | [五項詳細紀錄](recognition-experiments-20261008.zh-TW.md)、Git `4d2be41` |
| R15 · 10/08 | 和弦指型輔助 TAB：模型弦位的開發組 0.9068→0.9060、回歸組持平；不參考模型弦位的開發組 0.7244→0.7940、回歸組 0.5031→0.4688。強化權重反而讓整體 0.9114→0.9057。音高不變。 | 只提供明確開關，預設關閉 | [指型實驗紀錄](chord-shape-tab-experiment-20261008.zh-TW.md)、Git `40fbc5b` |
| R16 · 10/08 | Klangio 刷弦模型可行性調查：公開分類只有 24 種大／小三和弦，沒有同錄音評測或導入權重；不能當作已驗證改進。 | 未導入 | [五項紀錄末段](recognition-experiments-20261008.zh-TW.md) |

R04／R05 的兩段 EGSet 與 R11–R15 的 12 段 GuitarSet **不是同一個比較**。R11 的音高 F1 與 R15 的弦格一致率也不是同一指標。R14 的和弦切點測試與 R15 的強權重測試均是保留下來的失敗實驗；不要從台帳刪掉。

## 網頁、播放與操作試行

| 編號／時間 | 試行、觀察與證據 | 結論 |
| --- | --- | --- |
| U01 · 10/06 | 手機選歌、音軌勾選、iPhone 多軌播放與音量；曾發生第二軌斷續、不同步，改為伺服器先合成單一串流。Git `9cda3a0` 至 `e1f31c5`；[README：播放](../README.zh-TW.md)。 | 已採用修復；無公開延遲／音質量測，不能稱為辨識實驗。 |
| U02 · 10/06–08 | 原版 → Quiet Studio → 字體 → Listening Room 暗色 → Graphite → Practice Room。各版的 Git 標記、HDD 原始碼封存、截圖及瀏覽器驗證見[完整 UI 試行與還原紀錄](ui-redesign-20261008.md)。 | 保留可回復版本；瀏覽器冒煙測試不是使用者研究，也不是實機 Safari 保證。 |
| U03 · 10/07–08 | 和弦圖不同把位、跟播放移動的時間軸、固定播放器、TAB 幾何及小螢幕重排。Git `99d9591`／`f086101`／`fe5c0b5`／`990c245`；[UI 紀錄](ui-redesign-20261008.md)。 | 保留功能與畫面測試，沒有主張較高的音訊辨識準確率。 |

## 原始結果放在哪裡

- Git 追蹤、可公開核對的摘要：`benchmarks/evaluation-20261008.json`、`benchmarks/reference_sources.json`、本台帳與三份專題實驗文件。
- HDD 保留錄音／標註／逐首預測及有雜湊的完整報告：`/mnt/sdb/chordlab/benchmarks/reference-corpus/`、`reference-diverse-20261008-h3mmb6jz/`、`reference-stress-20261008/`。R11 的跨曲風基準檔是 `reference-diverse-20261008-h3mmb6jz/report-9f878163a8b6-f15536f5cc64.json`。
- R14／R15 的成對比較與合成訓練結果：`/mnt/sdb/chordlab/benchmarks/note-plausibility-20261008-v1/`，包含 `context-comparison.json`、`real-audit.json`、`chord-shape-assist-comparison.json`、`chord-shape-assist-playable-comparison.json`、`chord-shape-assist-strong-comparison.json`。HDD 內容不放上 GitHub，以免公開音訊、標註或私人資料。
- UI 封存位置與 Git 標記在[UI 紀錄](ui-redesign-20261008.md)；Git commit／tag 可追溯程式，但 commit 本身不等於實驗成功證據。

## 以後每次怎麼記

新實驗在此台帳追加一列，數據較多時另建 `docs/<主題>-experiment-YYYYMMDD.zh-TW.md`。一筆完整紀錄至少寫：

1. 編號／日期、問題與預先預期改善的指標；基準和候選的 Git commit、旗標及參數。
2. 音訊與人工標註的來源、授權、是否可能進過模型訓練；開發／回歸／真正保留集的切分及筆數。人工標註不可由本專案預測反推。
3. 同一輸入、相同容差與評分程式下，逐組列出基準→候選的原始數值與退步案例；沒有對照就寫「未量測」。合成音、主觀試聽與真實人工譜分欄，不混算。
4. 原始報告、manifest／預測／評分程式的 SHA-256、重跑命令與儲存路徑。授權受限或含私人資料的錄音只留在受控 HDD，Git 僅放不含個資的摘要。
5. 決定：正式、選用、預設關閉或停止；明列已知限制、下一步，以及需要什麼新證據才可改變決定。

舊結果不覆寫，參數修正再追加新編號。評估工具與獨立人工對照集的規格及發布門檻見[準確度對照集說明](accuracy-evaluation.zh-TW.md)。
