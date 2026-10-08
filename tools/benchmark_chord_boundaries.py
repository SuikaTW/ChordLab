"""Paired audit of existing chord transition timing on immutable real clips."""
import argparse
import json
from pathlib import Path
import sys
import librosa
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.recognition_context import refine_boundary
from tools.reference_corpus import checksum
from tools.benchmark_corpus import weighted_chords


def run(root, report_path, output):
    manifest = json.loads((root / 'manifest.json').read_text())
    report = json.loads(report_path.read_text())
    if checksum(root / 'manifest.json') != report['manifest_sha256']:
        raise ValueError('Corpus manifest differs')
    predictions = {row['id']: row for row in report['reports'] if row['engine'] == 'chordino'}
    rows = []
    for record in manifest['records']:
        prediction = predictions[record['id']]
        path = root / prediction['prediction']
        if checksum(path) != prediction['prediction_sha256'] or checksum(root / record['audio']) != record['audio_sha256'] or checksum(root / record['reference']) != record['reference_sha256']:
            raise ValueError('Corpus or prediction changed')
        audio, _ = librosa.load(root / record['audio'], sr=16000, mono=True)
        baseline = json.loads(path.read_text())['chords']
        candidate = [dict(segment) for segment in baseline]
        for left, right in zip(candidate, candidate[1:]):
            if left.get('manual') or right.get('manual') or left['chord'] == right['chord'] or left['chord'] in {'N','X'} or right['chord'] in {'N','X'} or abs(left['end']-right['start']) > .02:
                continue
            proposed = refine_boundary(audio, right['start'])
            if left['start'] + .2 < proposed < right['end'] - .2:
                left['end'] = right['start'] = proposed
        references = json.loads((root / record['reference']).read_text())['chord_annotations']
        if not references:
            continue
        rows.append(dict(id=record['id'], split=record['split'],
            baseline=weighted_chords(references[0]['segments'], baseline, len(audio)/16000),
            candidate=weighted_chords(references[0]['segments'], candidate, len(audio)/16000)))
    output.write_text(json.dumps(dict(policy='timing_only_same_chord_labels_exploratory', rows=rows), indent=2))
    for split in ('development','regression'):
        selected = [row for row in rows if row['split']==split]
        for variant in ('baseline','candidate'):
            seconds = sum(row[variant]['annotated_seconds'] for row in selected)
            agreement = sum(row[variant]['exact_chord_duration_agreement']*row[variant]['annotated_seconds'] for row in selected)/seconds
            matched = sum(row[variant]['boundary_matched'] for row in selected)
            count = sum(row[variant]['boundary_reference_count']+row[variant]['boundary_predicted_count'] for row in selected)
            print(split, variant, 'duration', round(agreement,4), 'boundary_f1', round(2*matched/max(1,count),4))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('report',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();run(args.root,args.report,args.output)
