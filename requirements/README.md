# 分析環境依賴

主網站使用根目錄的 `pyproject.toml` 與 `uv.lock`。這裡的檔案是額外分析環境，不應全部安裝到同一個 Python 環境；模型依賴與 Python 版本可能不同。

| 檔案 | 用途 |
| --- | --- |
| `basic.txt` | Basic Pitch 音符／Bass 轉錄 |
| `chordino.txt` | Chordino 分析環境 |
| `btc.txt` | BTC 和弦模型 |
| `demucs.txt` | 音軌分離 |
| `guitar.txt` | GAPS、TabCNN 等吉他實驗模型 |
| `whisper.txt` | 選用的歌詞辨識 |

吉他與 BTC 的安裝腳本分別是 [`scripts/install-guitar.sh`](../scripts/install-guitar.sh) 與 [`scripts/install-btc.sh`](../scripts/install-btc.sh)。其他環境的手動安裝步驟見[完整說明](../README.zh-TW.md)。
