# 準確度對照集與發布門檻

現有 GuitarSet 12 段真實木吉他錄音屬於回歸／探索測試，**不能當獨立盲測**：模型可能已使用該資料訓練。`tools/corpus_summary.py` 現在會彙總音符 F1、畫面實際 TAB 的 F1／弦格一致率、和弦時間覆蓋率及 250 ms 容差的換和弦 F1；`tools/accuracy_gate.py` 只在條件完整、候選與基準評測相同音訊且回歸組有改善時通過。現有資料不滿足發布門檻。

新增 `tools/import_reference_corpus.py` 可匯入自有或有權使用的真實 WAV 與**獨立人工標註**。建立新的來源資料夾，放入 `intake.json` 與錄音／標註檔；標註不能從本專案的 MIDI、TAB 或和弦輸出反推。

```json
{
  "source": "my_recordings_2026",
  "records": [{
    "id": "take01", "performer": "performer_a", "split": "development",
    "source_condition": "real_acoustic_guitar", "audio": "take01.wav",
    "reference": "take01.json", "source_url": "https://example.org/my-recording",
    "license": "owned", "annotator": "independent human", "genre": "pop"
  }]
}
```

`take01.json` 的格式是 `{"notes":[{"start":0.1,"end":0.5,"midi":64,"string":1,"fret":0}],"chord_annotations":[{"provenance":{"annotator":"..."},"segments":[{"start":0,"end":1,"chord":"Em"}]}]}`。時間單位為秒；`string`／`fret` 只有在已知**原演奏弦格**時才填。不要把推測把位冒充實際按法。同一演奏者只能在 development 或 regression 其中一組。

```bash
.venv/bin/python tools/import_reference_corpus.py /path/to/intake /mnt/sdb/chordlab/benchmarks/my-corpus
.venv/bin/python tools/benchmark_corpus.py /mnt/sdb/chordlab/benchmarks/my-corpus --infer
.venv/bin/python tools/corpus_summary.py /mnt/sdb/chordlab/benchmarks/my-corpus
.venv/bin/python tools/accuracy_gate.py /mnt/sdb/chordlab/benchmarks/my-corpus/summary.json --baseline basic_pitch --candidate event_verified
```

匯入器固定標示訓練重疊狀態為 `unknown_not_audited`，所以即使數字變好，發布門檻仍不會通過。必須先由人查核各模型的訓練來源、錄音來源與資料授權，再將**有證據**的資料獨立封存；不能為了過門檻直接改 JSON。完整驗收至少需要每條件每組 3 段不同錄音：真實木吉他、電吉他、Bass、完整混音，共至少 24 段，並提供可評估的音符／實際指法／和弦標註。Bass 與完整混音的辨識流程仍需另做匹配的模型評測，不能拿吉他模型結果假充 Bass 準確率。

可供研究的公開候選包括 [IDMT-SMT-Guitar](https://zenodo.org/records/7544110)（含電吉他與和弦／節奏標註）和 [IDMT-SMT-Bass-Single-Track](https://www.idmt.fraunhofer.de/en/publications/datasets/bass_lines.html)（17 段、音符與弦格標註）。後者標示 CC BY-NC-ND 4.0、僅供評估，不能未經授權作商業使用或重新散布。這些候選也未被自動宣告為「與模型訓練無重疊」。
