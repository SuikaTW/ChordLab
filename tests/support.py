"""Test-only stand-ins for optional production executables.

API/queue unit tests mock subprocess execution.  They only need executable
paths to pass availability checks; CI does not install the audio/ML toolchains.
"""

import sys
from pathlib import Path
from unittest.mock import patch


def runtime_patches(main):
    executable = Path(sys.executable)
    return [
        patch.object(main, name, executable)
        for name in (
            "BWRAP", "FFMPEG", "FFPROBE", "DENO", "YTDLP",
            "BASIC_PYTHON", "GUITAR_PYTHON",
        )
    ]
