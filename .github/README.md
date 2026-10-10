<p align="center"><img src="../app/static/favicon.svg" alt="ChordLab" width="72"></p>

# ChordLab

**從歌曲到可試聽、可修正的和弦與吉他／Bass 譜。**

ChordLab 是自架的音樂分析工作區：匯入音檔或支援的公開媒體網址，檢視分離音軌、和弦時間軸、MIDI 與連續 TAB，跟著播放器核對，再保留自己的修正。辨識結果是練習起點，**不是原曲的保證正確譜**。

[試用網站](https://chord.suika.page) · [中文完整說明](../README.zh-TW.md) · [English documentation](../README.md) · [實驗紀錄](../docs/experiment-ledger.zh-TW.md)

## 可以做什麼

| 聽與看 | 分析與修正 | 匯出 |
| --- | --- | --- |
| 同步試聽分軌、跟隨播放的和弦時間軸 | 比較和弦／吉他音符版本、編輯私人 TAB | MIDI、PDF、ChordPro、JSON |
| 吉他與 Bass 的連續 TAB | Capo、調弦、替代把位與局部和弦重查 | 依實際分析結果保留各版本 |

```text
音檔或網址 → 正規化／選用分軌 → 和弦與音符辨識
                                  ↓
                    播放核對 → TAB／人工修正 → 匯出
```

## 目前的研究問題

分軌串音、和弦漏判、快速音符，以及「同一音高有多種弦／格彈法」都會影響成譜。系統保留多種辨識版本與人工修正，不把不同模型的一致結果當成正確答案。現有 12 段 GuitarSet 評估可能與模型訓練資料重疊，**不是獨立盲測**；退步的實驗也照實記錄。

- [實驗台帳：方法、結果與失敗案例](../docs/experiment-ledger.zh-TW.md)
- [評測資料與發布門檻](../docs/accuracy-evaluation.zh-TW.md)
- [和弦指型輔助 TAB 的實測](../docs/chord-shape-tab-experiment-20261008.zh-TW.md)

## 找文件

| 想了解… | 從這裡開始 |
| --- | --- |
| 功能、操作與限制 | [中文完整說明](../README.zh-TW.md) |
| 安裝依賴 | [依賴檔索引](../requirements/README.md) |
| 服務單元與部署 | [systemd 範本說明](../deploy/systemd/README.md) |
| 備份、容量與還原 | [維運文件](../docs/operations-20261008.md) |
| 原版介面與回復 | [介面試行紀錄](../docs/ui-redesign-20261008.md) |

> 部署檔是這台伺服器的範本，不能直接當通用的一鍵安裝。音訊、模型權重、私人設定與使用者資料不包含在 Git 倉庫中。
