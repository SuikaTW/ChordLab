"""Fixed engine/file names: experimental results never replace the baseline."""
from pathlib import Path

ENGINES = {
    "basic_pitch": {"label": "原版", "profile": "guitar_v2", "file": "guitar"},
    "gaps": {"label": "GAPS 音符辨識（實驗）", "profile": "guitar_gaps_v1", "file": "guitar-gaps", "model": "guitar-gaps-paper.pth"},
    "tabcnn": {"label": "TabCNN 弦位辨識（實驗）", "profile": "guitar_tabcnn_gpfx_v1", "file": "guitar-tabcnn", "model": "tabcnn-gpfx.onnx"},
}


def paths(directory: Path, engine: str) -> tuple[Path, Path]:
    name = ENGINES[engine]["file"]
    return directory / "stem-midi" / f"{name}.json", directory / "stem-midi" / f"{name}.mid"


def available(root: Path, engine: str) -> bool:
    if engine == "basic_pitch":
        return (root / ".venv-basic/bin/python").is_file()
    return (root / ".venv-guitar/bin/python").is_file() and (root / "vendor/guitar/models" / ENGINES[engine]["model"]).is_file()
