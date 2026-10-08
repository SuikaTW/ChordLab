"""Fixed engine/file names: experimental results never replace the baseline."""
from pathlib import Path
from functools import lru_cache
import hashlib
import json
import os

RECOMMENDATION_REVISION = 6
CONTEXT_REVIEW_ENABLED = os.getenv('CHORDLAB_CONTEXT_REVIEW', 'false').lower() in {'1','true','yes'}
NOTE_SCORER = Path(__file__).resolve().parents[1] / 'app/models/note-plausibility-v1.json'

ENGINES = {
    "basic_pitch": {"label": "原版", "profile": "guitar_v2", "file": "guitar"},
    "gaps": {"label": "GAPS 音符辨識（實驗）", "profile": "guitar_gaps_v1", "file": "guitar-gaps", "model": "guitar-gaps-paper.pth"},
    "tabcnn": {"label": "TabCNN 弦位辨識（實驗）", "profile": "guitar_tabcnn_gpfx_v1", "file": "guitar-tabcnn", "model": "tabcnn-gpfx.onnx"},
    "hybrid": {"label": "整合 TAB v2（實驗）", "profile": "guitar_hybrid_v2", "file": "guitar-hybrid"},
    "verified": {"label": "音訊校驗（實驗）", "profile": "guitar_verified_v1", "file": "guitar-verified"},
    "cross_verified": {"label": "交叉校驗（實驗）", "profile": "guitar_cross_verified_v1", "file": "guitar-cross-verified"},
    "event_verified": {"label": "建議譜（自動整合）", "profile": "guitar_event_verified_v1", "file": "guitar-event-verified"},
}


def paths(directory: Path, engine: str) -> tuple[Path, Path]:
    name = ENGINES[engine]["file"]
    return directory / "stem-midi" / f"{name}.json", directory / "stem-midi" / f"{name}.mid"


def harmony_audio(directory: Path) -> Path:
    return next((directory/name for name in ('stems/harmony.wav','harmony.wav') if (directory/name).is_file()),directory/'audio.wav')


def available(root: Path, engine: str) -> bool:
    if engine in {"verified", "cross_verified", "event_verified"}:
        return (root / ".venv-guitar/bin/python").is_file()
    if engine == "hybrid":
        return available(root, "gaps") and available(root, "tabcnn")
    if engine == "basic_pitch":
        return (root / ".venv-basic/bin/python").is_file()
    return (root / ".venv-guitar/bin/python").is_file() and (root / "vendor/guitar/models" / ENGINES[engine]["model"]).is_file()


@lru_cache(maxsize=256)
def _digest_file(path, size, modified, inode):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recommendation_digest(directory: Path, result: dict) -> str:
    models = {}
    for name in ("basic_pitch", "gaps", "tabcnn", "hybrid"):
        path = paths(directory,name)[0]
        if path.is_file():
            info = path.stat()
            models[name] = _digest_file(str(path),info.st_size,info.st_mtime_ns,info.st_ino)
    methods = {name:result.get("methods",{}).get(name,[]) for name in ("chordino","btc","chord_v2")}
    audio = {}
    for name in ("audio.wav","stems/guitar.wav","stems/harmony.wav","harmony.wav","stems/bass.wav"):
        path = directory/name
        if path.is_file():
            info=path.stat();audio[name]=(info.st_size,info.st_mtime_ns,info.st_ino)
    scorer=None
    if NOTE_SCORER.is_file():
        info=NOTE_SCORER.stat();scorer=_digest_file(str(NOTE_SCORER),info.st_size,info.st_mtime_ns,info.st_ino)
    data=dict(revision=RECOMMENDATION_REVISION,models=models,methods=methods,audio=audio,harmony_notes=result.get('notes',[]),
        active_method=result.get("active_method") if result.get("active_method") in methods else None)
    if CONTEXT_REVIEW_ENABLED:
        data['context_review']=True
    if scorer:
        data['note_scorer']=scorer
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()


@lru_cache(maxsize=128)
def _recommendation_metadata(path, size, modified, inode):
    try:
        return json.loads(Path(path).read_text()).get("recommendation",{})
    except (ValueError,OSError):
        return {}


def recommendation_current(directory: Path, result: dict) -> bool:
    note_path,midi_path=paths(directory,"event_verified")
    if not note_path.is_file() or not midi_path.is_file(): return False
    info=note_path.stat()
    metadata=_recommendation_metadata(str(note_path),info.st_size,info.st_mtime_ns,info.st_ino)
    return metadata.get("revision")==RECOMMENDATION_REVISION and metadata.get("input_digest")==recommendation_digest(directory,result)
