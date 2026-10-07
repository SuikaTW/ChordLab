"""Require independent, complete references before promoting a recognition variant."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_CONDITIONS = {"real_acoustic_guitar", "real_electric_guitar", "real_bass", "real_full_mix"}
METRICS = (("pitch_onset", "micro_f1"), ("pitch_onset_offset", "micro_f1"),
           ("displayed_tab", "micro_f1"), ("displayed_tab", "actual_fingering_agreement"))


def assess(summary: dict, baseline: str, candidate: str,
           conditions: set[str] = REQUIRED_CONDITIONS) -> list[str]:
    issues = []
    if not summary.get("complete_selection") or summary.get("evaluated_clips") != summary.get("selected_clips"):
        issues.append("對照集尚未全部完成")
    if summary.get("model_training_overlap") not in {"none", "verified_none"}:
        issues.append("對照集可能與模型訓練資料重疊，不能作獨立盲測")
    groups = {(row["engine"], row["split"], row["source_condition"]): row
              for row in summary.get("groups", []) if row.get("genre") == "all"}
    improved = False
    for condition in sorted(conditions):
        for split in ("development", "regression"):
            left = groups.get((baseline, split, condition))
            right = groups.get((candidate, split, condition))
            if not left or not right or min(left.get("clips", 0), right.get("clips", 0)) < 3:
                issues.append(f"{condition}/{split}：兩版本各需至少三段獨立音訊")
                continue
            for category, metric in METRICS:
                old = left.get("metrics", {}).get(category, {}).get(metric)
                new = right.get("metrics", {}).get(category, {}).get(metric)
                if old is None or new is None:
                    issues.append(f"{condition}/{split}：缺少 {category}.{metric}")
                elif new < old - 0.005:
                    issues.append(f"{condition}/{split}：{category}.{metric} 從 {old} 降到 {new}")
                elif split == "regression" and new > old + 0.005:
                    improved = True
    old_chords = summary.get("chord_metrics_first_annotation_weighted", {}).get(baseline)
    new_chords = summary.get("chord_metrics_first_annotation_weighted", {}).get(candidate)
    if old_chords and new_chords:
        for metric in ("exact_chord_duration_agreement", "boundary_f1"):
            if metric not in old_chords or metric not in new_chords:
                issues.append(f"缺少和弦驗收指標 {metric}")
            elif new_chords[metric] < old_chords[metric] - 0.005:
                issues.append(f"和弦 {metric} 從 {old_chords[metric]} 降到 {new_chords[metric]}")
            elif new_chords[metric] > old_chords[metric] + 0.005:
                improved = True
    else:
        issues.append("缺少和弦時間準確率與切換點比較")
    if not improved:
        issues.append("回歸組沒有至少一個明確改善的指標")
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    issues = assess(json.loads(args.summary.read_text(encoding="utf-8")), args.baseline, args.candidate)
    for issue in issues:
        print("-", issue)
    if issues:
        raise SystemExit(1)
    print("數值門檻通過；仍需人工試聽與資料來源審查。")
