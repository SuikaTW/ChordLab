"""Audit a synthetic-trained note scorer on fixed real-recording predictions."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import librosa
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.note_plausibility import features, predict, load_model
from tools.reference_corpus import checksum


def evaluate(root, report_path, model_path):
    manifest = json.loads((root / 'manifest.json').read_text())
    report = json.loads(report_path.read_text())
    if checksum(root / 'manifest.json') != report['manifest_sha256']:
        raise ValueError('Mismatched evaluation manifest')
    records = {row['id']: row for row in manifest['records']}
    model = load_model(model_path)
    scores, labels, clips = [], [], []
    for row in report['reports']:
        if row['engine'] != 'event_verified':
            continue
        record = records[row['id']]
        audio, reference, prediction = root / record['audio'], root / record['reference'], root / row['prediction']
        if checksum(audio) != record['audio_sha256'] or checksum(reference) != record['reference_sha256'] or checksum(prediction) != row['prediction_sha256']:
            raise ValueError('Evaluation artifact changed')
        samples, _ = librosa.load(audio, sr=16000, mono=True)
        expected = json.loads(reference.read_text())['notes']
        notes = json.loads(prediction.read_text())['notes']
        values = [features(samples, note['midi'], note['start'], note['end']) for note in notes]
        matched = [any(other['midi'] == note['midi'] and abs(other['start'] - note['start']) <= .08 for other in expected) for note in notes]
        scores.extend(predict(np.asarray(values), model).tolist() if values else [])
        labels.extend(matched); clips.append(row['id'])
    flagged, incorrect = np.asarray(scores) < .35, ~np.asarray(labels, dtype=bool)
    found = int(np.sum(flagged & incorrect))
    return dict(model_sha256=checksum(model_path), report_sha256=checksum(report_path), clips=clips,
        reference_policy='published_labels_pitch_onset_80ms_candidate_audit_not_end_to_end_accuracy',
        model_training_overlap=manifest['model_training_overlap'], candidate_notes=len(labels),
        flagged_notes=int(flagged.sum()), incorrect_flagged=found, correct_flagged=int(np.sum(flagged & ~incorrect)),
        incorrect_precision=found / max(1, int(flagged.sum())), incorrect_recall=found / max(1, int(incorrect.sum())),
        release_policy='advisory_only_no_note_deletion_requires_independent_holdout')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('model', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = evaluate(args.root, args.report, args.model)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
