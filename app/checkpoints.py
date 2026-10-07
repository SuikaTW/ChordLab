"""Atomic per-stage markers for restarting a song without rerunning valid outputs."""
from __future__ import annotations

import json
import os
from pathlib import Path


class StageCache:
    def __init__(self, directory: Path, signature: str):
        self.directory = directory
        self.signature = signature

    def _relative(self, path: Path) -> str:
        candidate = path.resolve(strict=False)
        if not candidate.is_relative_to(self.directory.resolve(strict=False)):
            raise ValueError("階段產物不在工作目錄內")
        return str(candidate.relative_to(self.directory.resolve(strict=False)))

    def _artifacts(self, paths: list[Path]) -> dict | None:
        artifacts = {}
        for path in paths:
            try:
                stat = path.stat()
                if not path.is_file() or stat.st_size <= 0:
                    return None
                artifacts[self._relative(path)] = [stat.st_size, stat.st_mtime_ns]
            except (OSError, ValueError):
                return None
        return artifacts

    def read(self, stage: str) -> dict | None:
        try:
            marker = json.loads((self.directory / f".checkpoint-{stage}.json").read_text(encoding="utf-8"))
            if (not isinstance(marker, dict) or not isinstance(marker.get("artifacts"), dict)
                    or not isinstance(marker.get("data", {}), dict)):
                return None
            if marker.get("signature") != self.signature or not marker.get("artifacts"):
                return None
            paths = [self.directory / name for name in marker["artifacts"]]
            if self._artifacts(paths) != marker["artifacts"]:
                return None
            return marker.get("data", {})
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def save(self, stage: str, paths: list[Path], data: dict | None = None) -> bool:
        artifacts = self._artifacts(paths)
        if not artifacts:
            return False
        marker = self.directory / f".checkpoint-{stage}.json"
        temporary = self.directory / f".checkpoint-{stage}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps({"signature": self.signature, "artifacts": artifacts,
                                         "data": data or {}}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(marker)
        return True
