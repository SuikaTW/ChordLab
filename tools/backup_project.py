"""Incremental, private ChordLab backups on the separate HDD."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data/chordlab.sqlite3"
DEST_ROOT = Path("/mnt/sdc/backups/chordlab-auto")
JOBS = Path(os.environ.get("CHORDLAB_JOBS_DIR", str(ROOT / "data/jobs")))


def validate_backup(folder: Path) -> dict:
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with sqlite3.connect(f"file:{folder / 'chordlab.sqlite3'}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("備份資料庫檢查失敗")
        count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        completed = [row[0] for row in db.execute("SELECT id FROM jobs WHERE status='done'")]
    if count != manifest["job_rows"]:
        raise RuntimeError("資料庫筆數與備份記錄不符")
    if not (folder / "jobs").is_dir() or not (folder / "project/app/main.py").is_file():
        raise RuntimeError("備份缺少歌曲資料或應用程式")
    if any(not (folder / "jobs" / job_id / "audio.wav").is_file() for job_id in completed):
        raise RuntimeError("備份缺少已完成歌曲的原始音訊")
    return manifest


def restore_test(folder: Path) -> None:
    """Open a restored DB copy and resolve completed songs against the snapshot."""
    with tempfile.TemporaryDirectory(prefix="chordlab-restore-check-") as temporary:
        restored = Path(temporary) / "restored.sqlite3"
        with sqlite3.connect(folder / "chordlab.sqlite3") as source, sqlite3.connect(restored) as destination:
            source.backup(destination)
        with sqlite3.connect(restored) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("還原演練資料庫檢查失敗")
            rows = db.execute("SELECT id FROM jobs WHERE status='done'").fetchall()
        for (job_id,) in rows:
            with (folder / "jobs" / job_id / "audio.wav").open("rb") as audio:
                if not audio.read(12):
                    raise RuntimeError("還原演練發現空白音訊檔")


def run_backup() -> Path:
    if not JOBS.is_dir() or not Path("/mnt/sdc").is_mount():
        raise RuntimeError("歌曲磁碟或備份磁碟尚未就緒")
    DEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DEST_ROOT, 0o700)
    previous = sorted(folder for folder in DEST_ROOT.iterdir()
                      if folder.is_dir() and not folder.name.startswith(".") and (folder / "manifest.json").is_file())
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = DEST_ROOT / stamp
    temporary = DEST_ROOT / f".{stamp}.{os.getpid()}.partial"
    if target.exists() or temporary.exists():
        raise RuntimeError("備份名稱已存在")
    temporary.mkdir(mode=0o700)
    try:
        (temporary / "jobs").mkdir(mode=0o700)
        (temporary / "project").mkdir(mode=0o700)
        command = ["rsync", "-a", "--delete", "--exclude=*.building*", "--exclude=*.tmp"]
        if previous:
            command.append(f"--link-dest={previous[-1] / 'jobs'}")
        subprocess.run(command + [f"{JOBS}/", f"{temporary / 'jobs'}/"], check=True)
        subprocess.run(["rsync", "-a", "--exclude=.git/", "--exclude=.venv*/",
            "--exclude=data/", "--exclude=bin/", "--exclude=vendor/", "--exclude=.env",
            "--exclude=client_secret*.json", "--exclude=token.json", "--exclude=*.log",
            f"{ROOT}/", f"{temporary / 'project'}/"], check=True)
        with sqlite3.connect(SOURCE_DB) as source, sqlite3.connect(temporary / "chordlab.sqlite3") as destination:
            source.backup(destination)
        with sqlite3.connect(temporary / "chordlab.sqlite3") as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("資料庫備份未通過完整性檢查")
            job_rows = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        private = temporary / "private"
        private.mkdir(mode=0o700)
        config = ROOT / ".env"
        if config.is_file():
            shutil.copy2(config, private / "chordlab.env")
            os.chmod(private / "chordlab.env", 0o600)
            for line in config.read_text(encoding="utf-8").splitlines():
                if line.startswith("GOOGLE_OAUTH_FILE="):
                    source_path = Path(line.split("=", 1)[1].strip().strip("'\""))
                    if source_path.is_file():
                        shutil.copy2(source_path, private / "google-oauth.json")
                        os.chmod(private / "google-oauth.json", 0o600)
                    break
        manifest = {"created_utc": stamp, "job_rows": job_rows,
                    "jobs_source": str(JOBS), "database_source": str(SOURCE_DB),
                    "previous": previous[-1].name if previous else None}
        (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary / "manifest.json", 0o600)
        validate_backup(temporary)
        temporary.rename(target)
        restore_test(target)
        return target
    except BaseException:
        # Leave the partial snapshot available for diagnosis; it is never selected as previous.
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate latest completed snapshot")
    args = parser.parse_args()
    try:
        if args.check:
            snapshots = sorted(folder for folder in DEST_ROOT.iterdir()
                               if folder.is_dir() and (folder / "manifest.json").is_file())
            if not snapshots:
                raise RuntimeError("尚無完整備份")
            print(json.dumps(validate_backup(snapshots[-1]), ensure_ascii=False))
            restore_test(snapshots[-1])
        else:
            print(run_backup())
    except (OSError, RuntimeError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print(f"ChordLab 備份失敗：{exc}", file=sys.stderr)
        raise SystemExit(1)
