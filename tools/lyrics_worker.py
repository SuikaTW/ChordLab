#!/usr/bin/env python3
"""Transcribe timed lyrics from an isolated vocal or full-mix audio file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("output")
    parser.add_argument("--model", default="small")
    parser.add_argument("--cache", required=True)
    args = parser.parse_args()

    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        download_root=args.cache,
    )
    segments, info = model.transcribe(
        args.audio,
        beam_size=5,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    output_segments = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        words = []
        for word in segment.words or []:
            if word.start is None or word.end is None:
                continue
            words.append({
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
                "text": word.word,
                "probability": round(float(word.probability), 3),
            })
        output_segments.append({
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": text,
            "words": words,
        })
    payload = {
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "segments": output_segments,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
