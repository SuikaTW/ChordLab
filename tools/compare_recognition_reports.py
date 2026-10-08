"""Compare identical clips, keeping development and regression metrics separate."""
import argparse
import json
from pathlib import Path


def aggregate(rows):
    result = dict(clips=len(rows))
    for metric in ('pitch_onset', 'pitch_onset_offset'):
        matched = sum(row[metric]['matched'] for row in rows)
        expected = sum(row['reference_notes'] for row in rows)
        actual = sum(row['predicted_notes'] for row in rows)
        result[metric + '_f1'] = 2 * matched / max(1, expected + actual)
    tabs = [row['displayed_tab'] for row in rows if row.get('displayed_tab')]
    if len(tabs) == len(rows):
        result['displayed_tab_f1'] = 2 * sum(row['matched'] for row in tabs) / max(1, sum(row['displayed_notes'] for row in tabs) + sum(row['reference_notes'] for row in rows))
        count = sum(row.get('reference_fingerings', 0) for row in tabs)
        result['fingering_agreement'] = sum(row.get('fingering_agreement', 0) * row.get('reference_fingerings', 0) for row in tabs) / max(1, count)
    chords = [row['chord_annotations'][0]['metrics'] for row in rows if row.get('chord_annotations')]
    if len(chords) == len(rows):
        seconds = sum(row['annotated_seconds'] for row in chords)
        result['chord_duration_agreement'] = sum(row['exact_chord_duration_agreement'] * row['annotated_seconds'] for row in chords) / max(1e-12, seconds)
        result['chord_boundary_f1'] = 2 * sum(row['boundary_matched'] for row in chords) / max(1, sum(row['boundary_reference_count'] + row['boundary_predicted_count'] for row in chords))
    return result


def compare(before, after, engine='event_verified'):
    if before['manifest_sha256'] != after['manifest_sha256']:
        raise ValueError('Reports do not describe the same immutable corpus')
    old = {row['id']: row for row in before['reports'] if row['engine'] == engine}
    new = {row['id']: row for row in after['reports'] if row['engine'] == engine}
    if not old or old.keys() != new.keys():
        raise ValueError('Both reports must include the same complete clip selection')
    if any(old[key]['reference_sha256'] != new[key]['reference_sha256'] or old[key]['split'] != new[key]['split'] for key in old):
        raise ValueError('Reference labels or splits changed')
    groups = []
    for split in ('development', 'regression', 'all'):
        ids = sorted(key for key in old if split == 'all' or old[key]['split'] == split)
        if not ids:
            continue
        baseline, candidate = aggregate([old[key] for key in ids]), aggregate([new[key] for key in ids])
        groups.append(dict(split=split, baseline=baseline, candidate=candidate,
            delta={key: round(candidate[key] - baseline[key], 6) for key in baseline if key != 'clips' and key in candidate}))
    return dict(engine=engine, baseline_pipeline=before['pipeline_sha256'], candidate_pipeline=after['pipeline_sha256'],
        model_training_overlap=after['model_training_overlap'], groups=groups,
        policy='paired_exploratory_comparison_not_independent_accuracy_claim')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--engine', default='event_verified')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()), args.engine)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered)
    print(rendered)
