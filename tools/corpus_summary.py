"""Compact grouped metrics. Derived stress clips never become independent truth."""
import argparse
import json
from pathlib import Path


def summarize(root):
    report=json.loads((root/'report.json').read_text())
    manifest=json.loads((root/'manifest.json').read_text())
    groups={}
    for row in report['reports']:
        if 'pitch_onset' not in row:continue
        for genre in ('all',row.get('genre') or 'unknown'):
            key=(row['engine'],row['split'],genre,row.get('source_condition','real_acoustic_guitar'))
            groups.setdefault(key,[]).append(row)
    output=[]
    for (engine,split,genre,condition),rows in sorted(groups.items()):
        metrics={}
        for name in ('pitch_onset','pitch_onset_offset'):
            matched=sum(row[name]['matched'] for row in rows)
            expected=sum(row['reference_notes'] for row in rows)
            predicted=sum(row['predicted_notes'] for row in rows)
            metrics[name]={'matched':matched,'reference_notes':expected,'predicted_notes':predicted,
                'micro_f1':round(2*matched/max(1,expected+predicted),4)}
        displayed=[row for row in rows if row.get('displayed_tab')]
        if displayed:
            matched=sum(row['displayed_tab']['matched'] for row in displayed)
            expected=sum(row['reference_notes'] for row in displayed)
            actual=sum(row['displayed_tab']['displayed_notes'] for row in displayed)
            known=sum(row['displayed_tab'].get('reference_fingerings',0) for row in displayed)
            exact=sum(row['displayed_tab'].get('fingering_agreement',0)*row['displayed_tab'].get('reference_fingerings',0) for row in displayed)
            metrics['displayed_tab']={'micro_f1':round(2*matched/max(1,expected+actual),4),
                'actual_fingering_agreement':round(exact/known,4) if known else None}
        output.append({'engine':engine,'split':split,'genre':genre,'source_condition':condition,'clips':len(rows),'metrics':metrics})
    ids={row['id'] for row in report['reports']}
    result={'schema':1,'pipeline_sha256':report['pipeline_sha256'],'evaluation_sha256':report['evaluation_sha256'],
        'manifest_sha256':report['manifest_sha256'],'selected_clips':len(manifest['records']),'evaluated_clips':len(ids),
        'complete_selection':ids=={row['id'] for row in manifest['records']},
        'genres':sorted({row.get('genre','unknown') for row in manifest['records']}),
        'condition_policy':'derived_cases_are_not_real_electric_or_band_and_not_independent_samples',
        'model_training_overlap':report['model_training_overlap'],
        'metrics_policy':'separate_development_regression_genre_and_source_condition_no_training', 'groups':output}
    (root/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({key:result[key] for key in ('evaluated_clips','selected_clips','complete_selection','genres')},ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    summarize(parser.parse_args().root)
