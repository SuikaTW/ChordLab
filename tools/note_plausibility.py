"""Small learned candidate scorer. Synthetic scores never remove real notes."""
import json
import numpy as np
from tools.audio_verification import FREQ, spectrum

FEATURES = ['fundamental', 'second', 'third', 'suboctave', 'onset_rise', 'local_contrast']


def features(samples, pitch, start, end):
    center = start + min(.1, (end - start) * .5)
    spec, before = spectrum(samples, center), spectrum(samples, max(0, start - .07))
    frequency = 440 * 2 ** ((pitch - 69) / 12)
    maximum = max(1e-9, float(spec.max()))
    def band(values, freq):
        return float(values[np.abs(FREQ - freq) < 9].max(initial=0))
    strengths = [band(spec, frequency * ratio) / maximum for ratio in (1, 2, 3, .5)]
    prior = band(before, frequency) / maximum
    neighbors = max(band(spec, frequency * 2 ** (step / 12)) for step in (-1, 1)) / maximum
    return np.array([*strengths, np.clip(strengths[0] - prior, -2, 2), strengths[0] - neighbors], dtype=float)


def load_model(path):
    model = json.loads(path.read_text())
    if model.get('features') != FEATURES or model.get('policy') != 'synthetic_trained_advisory_only':
        raise ValueError('Unrecognized note scoring model')
    for key in ('mean', 'scale', 'weights'):
        values = np.asarray(model[key], dtype=float)
        if values.shape != (len(FEATURES),) or not np.isfinite(values).all():
            raise ValueError('Invalid scoring parameters')
    if min(model['scale']) <= 0 or not np.isfinite(model['bias']):
        raise ValueError('Invalid scoring normalization')
    return model


def predict(matrix, model):
    values = (np.asarray(matrix) - model['mean']) / model['scale']
    logits = values @ np.asarray(model['weights']) + model['bias']
    return 1 / (1 + np.exp(-np.clip(logits, -30, 30)))


def audit_notes(samples, notes, model):
    output = []
    for index, note in enumerate(notes[:2000]):
        if note.get('edited'):
            continue
        score = float(predict(features(samples, note['midi'], note['start'], note['end']), model))
        if score < .35:
            output.append(dict(kind='learned_low_support', index=index, midi=note['midi'], start=note['start'], score=round(score, 4)))
    return dict(policy=model['policy'], scored_notes=min(len(notes), 2000), suggestions=output[:100],
                score_kind='uncalibrated_outside_synthetic_domain', model_version=model['version'])
