from typing import Literal
from pydantic import BaseModel, Field, model_validator

TUNINGS = {"standard": [40,45,50,55,59,64], "drop_d": [38,45,50,55,59,64],
           "dadgad": [38,45,50,55,57,62], "half_down": [39,44,49,54,58,63],
           "whole_down": [38,43,48,53,57,62]}


class TabNote(BaseModel):
    index: int = Field(ge=0, le=10000000)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    midi: int = Field(ge=0, le=127)
    velocity: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    string: int = Field(ge=0, le=5)
    fret: int = Field(ge=0, le=24)
    edited: bool = False
    suspicious: bool = False


class TabRhythm(BaseModel):
    bpm: float = Field(default=120, ge=30, le=300, allow_inf_nan=False)
    meter: Literal[3, 4, 6] = 4
    offset: float = Field(default=0, ge=0, le=1200, allow_inf_nan=False)
    manual: bool = False


class TabDocument(BaseModel):
    revision: int = Field(default=0, ge=0)
    notes: list[TabNote] = Field(max_length=20000)
    tuning: Literal["standard", "drop_d", "dadgad", "half_down", "whole_down"] = "standard"
    capo: int = Field(default=0, ge=0, le=11)
    voice: Literal["all", "high", "low"] = "all"
    position: Literal["auto", "open", "middle", "high"] = "auto"
    density: Literal["clean", "full"] = "clean"
    source_engine: Literal["basic_pitch", "gaps", "tabcnn", "hybrid"] = "basic_pitch"
    fingering_mode: Literal["model", "playable"] = "model"
    rhythm: TabRhythm = Field(default_factory=TabRhythm)

    @model_validator(mode="after")
    def validate_fingering(self):
        seen, last = set(), {}
        for note in sorted(self.notes, key=lambda n: (n.start, n.string)):
            if note.index in seen or note.end <= note.start:
                raise ValueError("音符重複或時間無效")
            if TUNINGS[self.tuning][note.string] + self.capo + note.fret != note.midi:
                raise ValueError("音高與調弦、Capo、弦及格數不一致")
            if note.fret + self.capo > 24:
                raise ValueError("超出 24 個實際琴格")
            if last.get(note.string, 0) > note.start + .00001:
                raise ValueError("同一條弦的音符不可重疊")
            seen.add(note.index)
            last[note.string] = note.end
        return self
