"""Conservative signal gate, not an instrument-presence classifier.

Measure short windows so a brief solo survives even in a long song. Stereo
channels are squared independently to avoid phase cancellation. Keep files and
fail open on unsupported input; users can reveal gated tracks manually.
"""
from array import array
import math
import sys
import wave


def window_levels(path):
    levels = []
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
            raise ValueError("Expected PCM16")
        frames = max(1, round(audio.getframerate() / 4))
        while raw := audio.readframes(frames):
            samples = array("h", raw)
            if sys.byteorder != "little":
                samples.byteswap()
            # Sample frames, retaining both channels, with bounded memory.
            channels = audio.getnchannels()
            selected = [samples[i + c] / 32768 for i in range(0, len(samples), 8 * channels)
                        for c in range(channels) if i + c < len(samples)]
            rms = math.sqrt(sum(s * s for s in selected) / max(1, len(selected)))
            levels.append(20 * math.log10(max(rms, 1e-9)))
    return levels


def detect_activity(directory, stems):
    try:
        reference = window_levels(directory / "audio.wav")
    except (OSError, ValueError, wave.Error):
        return {}
    result = {}
    for stem in stems:
        if stem == "original":
            continue
        try:
            levels = window_levels(directory / "stems" / f"{stem}.wav")
            audible = sum(level > -55 and level - ref > -32
                          for level, ref in zip(levels, reference))
            strong = any(level > -45 and level - ref > -20
                         for level, ref in zip(levels, reference))
            active = strong or audible >= min(2, max(1, len(levels)))
            result[stem] = {"active": active, "audible_seconds": round(audible * .25, 2),
                            "max_window_dbfs": round(max(levels, default=-180), 1),
                            "reason": "signal" if active else "weak_signal", "version": 1}
        except (OSError, ValueError, wave.Error):
            result[stem] = {"active": True, "reason": "unverified", "version": 1}
    return result
