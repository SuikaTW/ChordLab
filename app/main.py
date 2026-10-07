from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import math
import os
import re
import secrets
import shutil
import socket
import sqlite3
# Required for fixed argv calls to bundled analysis binaries; shell execution is never used.
import subprocess  # nosec B404
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Iterator, Literal
from urllib.parse import parse_qs, urlparse

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from starlette.middleware.sessions import SessionMiddleware
from app.stem_activity import detect_activity
from app.light_tasks import LightTaskPool, PoolBusy
from app.preparation import DownloadPreparation
from app.tab_models import TabDocument
from app.chord_comparison import compare_chords
from app.guitar_engines import ENGINES as GUITAR_ENGINES, paths as guitar_paths, available as guitar_engine_available
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
JOBS = Path(os.getenv("CHORDLAB_JOBS_DIR", str(DATA / "jobs"))).expanduser()
if not JOBS.is_absolute():
    raise RuntimeError("CHORDLAB_JOBS_DIR 必須是絕對路徑")
STORAGE_MOUNT = Path(os.getenv("CHORDLAB_STORAGE_MOUNT", "")).expanduser() if os.getenv("CHORDLAB_STORAGE_MOUNT") else None
DB_PATH = DATA / "chordlab.sqlite3"
STATIC = ROOT / "app" / "static"
BASIC_PYTHON = ROOT / ".venv-basic" / "bin" / "python"
GUITAR_PYTHON = ROOT / ".venv-guitar" / "bin" / "python"
CHORDINO_PYTHON = ROOT / ".venv-chordino" / "bin" / "python"
BTC_PYTHON = ROOT / ".venv-btc" / "bin" / "python"
BTC_MODEL = ROOT / "vendor/btc/models/btc_model_large_voca.pt"
BTC_ENABLED = os.getenv("CHORDLAB_BTC_ENABLED", "true").lower() not in {"0", "false", "no"}
DEMUCS_PYTHON = ROOT / ".venv-demucs" / "bin" / "python"
WHISPER_PYTHON = ROOT / ".venv-whisper" / "bin" / "python"
VAMP_PATH = ROOT / "vendor" / "vamp"
FFMPEG = ROOT / "bin" / "ffmpeg"
FFPROBE = ROOT / "bin" / "ffprobe"
DENO = ROOT / "bin" / "deno"
YTDLP = ROOT / ".venv" / "bin" / "yt-dlp"
BWRAP = Path(shutil.which("bwrap")) if shutil.which("bwrap") else None
MAX_UPLOAD = int(os.getenv("CHORDLAB_MAX_UPLOAD_MB", "200")) * 1024 * 1024
MAX_DURATION = int(os.getenv("CHORDLAB_MAX_DURATION_MIN", "20")) * 60
ANALYSIS_WORKERS = max(1, min(3, int(os.getenv("CHORDLAB_ANALYSIS_WORKERS", "1"))))
MAX_ACTIVE_PER_USER = max(1, min(10, int(os.getenv("CHORDLAB_MAX_ACTIVE_PER_USER", "2"))))
DAILY_JOB_LIMIT = max(1, min(100, int(os.getenv("CHORDLAB_DAILY_JOB_LIMIT", "5"))))
SESSION_DAYS = max(1, min(30, int(os.getenv("CHORDLAB_SESSION_DAYS", "7"))))
ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.getenv(
        "CHORDLAB_MEDIA_HOSTS",
        "youtube.com,youtu.be,music.youtube.com,soundcloud.com,bandcamp.com,bilibili.com,vimeo.com",
    ).split(",")
    if host.strip()
}
APP_HOSTS = {
    host.strip().lower()
    for host in os.getenv("CHORDLAB_APP_HOSTS", "chord.suika.page,localhost,127.0.0.1,testserver").split(",")
    if host.strip()
}
SAFE_MEDIA_FORMATS = {
    "aac", "flac", "matroska", "mov", "mp3", "mp4", "m4a", "ogg", "opus", "wav", "webm",
    "3gp", "3g2", "mj2",
}
USERNAME = os.getenv("CHORDLAB_USERNAME", "")
PASSWORD = os.getenv("CHORDLAB_PASSWORD", "")
SECRET = os.getenv("CHORDLAB_SECRET", "")
SECURE_COOKIE = os.getenv("CHORDLAB_SECURE_COOKIE", "true").lower() not in {"0", "false", "no"}
COOKIE = "chordlab_session"
GOOGLE_OAUTH_FILE = os.getenv("GOOGLE_OAUTH_FILE", "").strip()


def google_oauth_credentials() -> tuple[str, str]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if GOOGLE_OAUTH_FILE:
        try:
            payload = json.loads(Path(GOOGLE_OAUTH_FILE).read_text(encoding="utf-8"))
            web = payload.get("web") or {}
            client_id = client_id or str(web.get("client_id") or "").strip()
            client_secret = client_secret or str(web.get("client_secret") or "").strip()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("GOOGLE_OAUTH_FILE 無法讀取或不是有效的 OAuth JSON") from exc
    return client_id, client_secret


GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET = google_oauth_credentials()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://chord.suika.page/auth/google/callback").strip()
GOOGLE_ALLOWED_EMAILS = {
    email.strip().lower() for email in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",") if email.strip()
}
GOOGLE_ADMIN_EMAILS = {
    email.strip().lower() for email in os.getenv("GOOGLE_ADMIN_EMAILS", "").split(",") if email.strip()
}
GOOGLE_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
executor = ThreadPoolExecutor(max_workers=ANALYSIS_WORKERS, thread_name_prefix="chordlab")
light_tasks = LightTaskPool()
download_preparation = DownloadPreparation()
heavy_analysis_slot = threading.BoundedSemaphore(1)
job_submission_lock = threading.Lock()
mix_generation_lock = threading.Lock()
login_attempts: dict[str, list[float]] = {}
login_lock = threading.Lock()

app = FastAPI(title="ChordLab", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET or secrets.token_hex(32), https_only=SECURE_COOKIE, same_site="lax", max_age=600)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
oauth = OAuth()
if GOOGLE_ENABLED:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        # sqlite3's own context manager commits/rolls back but does not close.
        # Close deterministically instead of waiting for cyclic garbage collection.
        with connection:
            yield connection
    finally:
        connection.close()


def init_db() -> None:
    DATA.mkdir(exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                duration REAL,
                note_count INTEGER,
                result TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
        if "separate_stems" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN separate_stems INTEGER NOT NULL DEFAULT 0")
        if "owner" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN owner TEXT NOT NULL DEFAULT 'legacy'")
        if "separation_model" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN separation_model TEXT NOT NULL DEFAULT 'htdemucs'")
        if "stem_midi" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN stem_midi INTEGER NOT NULL DEFAULT 0")
        if "pure_guitar" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN pure_guitar INTEGER NOT NULL DEFAULT 0")
        if "transcribe_lyrics" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN transcribe_lyrics INTEGER NOT NULL DEFAULT 0")
        if "source_kind" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'upload'")
            connection.execute("UPDATE jobs SET source_kind='url' WHERE source LIKE 'http://%' OR source LIKE 'https://%'")
        if "is_public" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0")
        if "public_at" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN public_at INTEGER")
        if "error_detail" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN error_detail TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_views (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                viewer TEXT NOT NULL,
                viewed_at INTEGER NOT NULL,
                PRIMARY KEY (job_id, viewer)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_favorites (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                owner TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (job_id, owner)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                provider TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_blocked INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                UNIQUE(provider, subject)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at, id)")
        if "review_guitar" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN review_guitar INTEGER NOT NULL DEFAULT 0")
        connection.execute("""CREATE TABLE IF NOT EXISTS user_tabs (
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            viewer TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
            updated_at INTEGER NOT NULL, PRIMARY KEY(job_id, viewer))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS user_bass_tabs (
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            viewer TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
            updated_at INTEGER NOT NULL, PRIMARY KEY(job_id, viewer))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS tab_references (
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, viewer TEXT NOT NULL,
            instrument TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
            updated_at INTEGER NOT NULL, PRIMARY KEY(job_id,viewer,instrument))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS guitar_tasks (
            job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
        guitar_columns = {row[1] for row in connection.execute("PRAGMA table_info(guitar_tasks)")}
        if "engine" not in guitar_columns:
            connection.execute("ALTER TABLE guitar_tasks ADD COLUMN engine TEXT NOT NULL DEFAULT 'basic_pitch'")
        had_submissions = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='guitar_submissions'").fetchone()
        # Keep an append-only quota record: switching failed engines (or deleting
        # a song) must not erase previous CPU requests from the daily allowance.
        connection.execute("""CREATE TABLE IF NOT EXISTS guitar_submissions (
            id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, owner TEXT NOT NULL,
            engine TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_guitar_submissions_owner_time ON guitar_submissions(owner,created_at)")
        if not had_submissions:
            connection.execute("""INSERT INTO guitar_submissions(job_id,owner,engine,created_at)
                SELECT t.job_id,j.owner,t.engine,t.created_at FROM guitar_tasks t JOIN jobs j ON j.id=t.job_id""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_status ON jobs(owner, status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_public_status ON jobs(is_public, status, public_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_job_views_rank ON job_views(job_id, viewed_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_job_favorites_rank ON job_favorites(job_id, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(created_at DESC)")
        now = int(time.time())
        configured_users = [(USERNAME.lower(), "local", USERNAME, 1)] + [
            (email, "google", email, 1) for email in GOOGLE_ADMIN_EMAILS
        ]
        for subject, provider, display_name, admin in configured_users:
            if not subject:
                continue
            key = identity_key({"sub": subject, "provider": provider})
            connection.execute(
                """
                INSERT INTO users(id,subject,provider,display_name,is_admin,is_blocked,created_at,last_seen)
                VALUES (?,?,?,?,?,0,?,?)
                ON CONFLICT(id) DO UPDATE SET is_admin=1, last_seen=excluded.last_seen
                """,
                (key, subject, provider, display_name, admin, now, now),
            )
        for owner_row in connection.execute("SELECT owner, MIN(created_at) AS first_seen, MAX(updated_at) AS last_seen FROM jobs GROUP BY owner"):
            subject = str(owner_row["owner"] or "legacy").lower()
            provider = "local" if subject == USERNAME.lower() else ("google" if "@" in subject else "legacy")
            identity = {"sub": subject, "provider": provider}
            connection.execute(
                """
                INSERT OR IGNORE INTO users(id,subject,provider,display_name,is_admin,is_blocked,created_at,last_seen)
                VALUES (?,?,?,?,?,0,?,?)
                """,
                (
                    identity_key(identity), subject, provider, subject, int(configured_admin(identity)),
                    int(owner_row["first_seen"] or now), int(owner_row["last_seen"] or now),
                ),
            )
        connection.execute("PRAGMA optimize")


def identity_key(identity: dict) -> str:
    raw = f"{identity['provider']}\0{identity['sub'].lower()}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def configured_admin(identity: dict) -> bool:
    return identity["provider"] == "local" or identity["sub"].lower() in GOOGLE_ADMIN_EMAILS


def touch_user(identity: dict, display_name: str = "") -> sqlite3.Row:
    now = int(time.time())
    key = identity_key(identity)
    subject = identity["sub"].lower()
    with db() as connection:
        connection.execute(
            """
            INSERT INTO users(id,subject,provider,display_name,is_admin,is_blocked,created_at,last_seen)
            VALUES (?,?,?,?,?,0,?,?)
            ON CONFLICT(id) DO UPDATE SET
                display_name=CASE WHEN excluded.display_name<>'' THEN excluded.display_name ELSE users.display_name END,
                is_admin=CASE WHEN excluded.is_admin=1 THEN 1 ELSE users.is_admin END,
                last_seen=CASE WHEN users.last_seen < excluded.last_seen - 300 THEN excluded.last_seen ELSE users.last_seen END
            """,
            (key, subject, identity["provider"], display_name[:120], int(configured_admin(identity)), now, now),
        )
        return connection.execute("SELECT * FROM users WHERE id=?", (key,)).fetchone()


def audit_admin(actor: dict, action: str, target: str, detail: dict | None = None, connection: sqlite3.Connection | None = None) -> None:
    values = (actor["sub"], action, target, json.dumps(detail or {}, ensure_ascii=False), int(time.time()))
    if connection is not None:
        connection.execute(
            "INSERT INTO admin_audit(actor,action,target,detail,created_at) VALUES (?,?,?,?,?)", values
        )
        return
    with db() as own_connection:
        own_connection.execute(
            "INSERT INTO admin_audit(actor,action,target,detail,created_at) VALUES (?,?,?,?,?)", values
        )


def sign_session(subject: str, provider: str, expires: int) -> str:
    body = base64.urlsafe_b64encode(json.dumps(
        {"sub": subject, "provider": provider, "expires": expires}, separators=(",", ":")
    ).encode()).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def session_identity(token: str | None) -> dict | None:
    if not token or not SECRET:
        return None
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        valid = (
            payload.get("provider") in {"local", "google"}
            and bool(payload.get("sub"))
            and int(payload["expires"]) > int(time.time())
            and hmac.compare_digest(signature, expected)
        )
        return {"sub": str(payload["sub"]).lower(), "provider": payload["provider"]} if valid else None
    except (KeyError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return None


def is_admin(identity: dict) -> bool:
    if configured_admin(identity):
        return True
    with db() as connection:
        row = connection.execute("SELECT is_admin FROM users WHERE id=?", (identity_key(identity),)).fetchone()
    return bool(row and row["is_admin"])


def require_admin(request: Request) -> dict:
    identity = request.state.identity
    if not is_admin(identity):
        raise HTTPException(403, "需要管理員權限")
    return identity


def request_origin(request: Request) -> str | None:
    value = request.headers.get("origin")
    if value:
        return value.rstrip("/")
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlparse(referer)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None


@app.middleware("http")
async def authentication(request: Request, call_next):
    public = request.url.path in {"/login", "/healthz", "/auth/google", "/auth/google/callback"} or request.url.path.startswith("/static/")
    if not public:
        identity = session_identity(request.cookies.get(COOKIE))
        if not identity:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "請先登入"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        user = await run_in_threadpool(touch_user, identity)
        if user["is_blocked"]:
            if request.url.path.startswith("/api/"):
                response = JSONResponse({"detail": "此帳號已被管理員停權"}, status_code=403)
            else:
                response = RedirectResponse("/login?error=blocked", status_code=303)
            response.delete_cookie(COOKIE)
            return response
        request.state.identity = identity
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != "/login":
        origin = request_origin(request)
        if not origin or origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "來源驗證失敗"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def https_policy(request: Request, call_next):
    if request.url.hostname not in APP_HOSTS:
        return PlainTextResponse("Invalid host", status_code=400)
    cloudflare_request = bool(request.headers.get("cf-ray"))
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
    if cloudflare_request and forwarded_proto != "https":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    response = await call_next(request)
    if forwarded_proto == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    if not request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.on_event("startup")
def startup() -> None:
    if not USERNAME or not PASSWORD or len(SECRET) < 32:
        raise RuntimeError("CHORDLAB_USERNAME, CHORDLAB_PASSWORD and a 32+ character CHORDLAB_SECRET are required")
    if STORAGE_MOUNT and not STORAGE_MOUNT.is_mount():
        raise RuntimeError(f"歌曲資料磁碟尚未掛載：{STORAGE_MOUNT}")
    if not BWRAP or not BWRAP.is_file() or not FFMPEG.is_file() or not FFPROBE.is_file() or not DENO.is_file() or not YTDLP.is_file():
        raise RuntimeError("分析沙箱、ffmpeg、ffprobe、Deno 或 yt-dlp 尚未安裝，服務拒絕啟動")
    init_db()
    with db() as connection:
        connection.execute("UPDATE jobs SET status='queued', progress=2, message='服務重啟，已重新加入佇列' WHERE status='working'")
        pending = connection.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at, id").fetchall()
    with db() as connection:
        connection.execute("UPDATE guitar_tasks SET status='queued' WHERE status='working'")
        guitar_pending = connection.execute("SELECT job_id,created_at FROM guitar_tasks WHERE status='queued'").fetchall()
    ordered = [(row["created_at"], row["id"], "song", row) for row in pending] + [(row["created_at"], row["job_id"], "tab", row) for row in guitar_pending]
    for _created, _id, kind, row in sorted(ordered, key=lambda item: (item[0], item[1])):
        if kind == "tab":
            executor.submit(process_guitar_task, row["job_id"])
        else:
            if row["source_kind"] == "url":
                schedule_download(row["id"], row["source"])
            executor.submit(process_job, row["id"], row["source_kind"], row["source"],
                            bool(row["separate_stems"]), row["separation_model"], bool(row["stem_midi"]),
                            bool(row["transcribe_lyrics"]), bool(row["pure_guitar"]), review_guitar=bool(row["review_guitar"]))


@app.get("/healthz")
def public_health() -> dict:
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "basic_pitch": BASIC_PYTHON.exists(),
        "chordino": CHORDINO_PYTHON.exists() and (VAMP_PATH / "nnls-chroma.so").exists(),
        "btc": BTC_ENABLED and BTC_PYTHON.exists() and BTC_MODEL.is_file(),
        "demucs": DEMUCS_PYTHON.exists(),
        "whisper": WHISPER_PYTHON.exists(),
        "google_login": GOOGLE_ENABLED,
        "analysis_workers": ANALYSIS_WORKERS,
        "storage_ready": not STORAGE_MOUNT or STORAGE_MOUNT.is_mount(),
        "worker_sandbox": bool(BWRAP and BWRAP.is_file()),
        "media_probe": FFPROBE.is_file(),
        "youtube_runtime": DENO.is_file() and YTDLP.is_file(),
    }


@app.get("/api/me")
def current_user(request: Request) -> dict:
    identity = request.state.identity
    viewer_key = hashlib.sha256(f"{identity['provider']}:{identity['sub']}".encode()).hexdigest()[:16]
    since = int(time.time()) - 86400
    with db() as connection:
        daily_jobs = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE owner=? AND created_at>=?", (identity["sub"], since)
        ).fetchone()[0]
    return {
        "key": viewer_key,
        "subject": identity["sub"],
        "provider": identity["provider"],
        "admin": is_admin(identity),
        "daily_jobs": daily_jobs,
        "daily_limit": None if is_admin(identity) else DAILY_JOB_LIMIT,
    }


@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = "") -> str:
    errors = {
        "1": "帳號或密碼錯誤",
        "google": "Google 登入失敗，請再試一次",
        "denied": "這個 Google 帳號沒有使用權限",
        "blocked": "這個帳號已被管理員停權",
    }
    error_html = f'<p class="login-error">{errors.get(error, "登入失敗")}</p>' if error else ""
    google_html = (
        '<a class="google-login" href="/auth/google"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.6h3.3c1.9-1.8 2.9-4.4 2.9-7.5z"/><path fill="#34A853" d="M12 22c2.7 0 5-.9 6.7-2.3l-3.3-2.6c-.9.6-2.1 1-3.4 1-2.6 0-4.8-1.8-5.6-4.2H3v2.7A10 10 0 0 0 12 22z"/><path fill="#FBBC05" d="M6.4 13.9A6 6 0 0 1 6.1 12c0-.7.1-1.3.3-1.9V7.4H3A10 10 0 0 0 2 12c0 1.7.4 3.2 1 4.6l3.4-2.7z"/><path fill="#EA4335" d="M12 5.9c1.5 0 2.8.5 3.9 1.5l2.9-2.9A9.8 9.8 0 0 0 3 7.4l3.4 2.7A6 6 0 0 1 12 5.9z"/></svg>使用 Google 登入</a><div class="login-divider"><span>或使用密碼</span></div>'
        if GOOGLE_ENABLED
        else '<p class="oauth-pending">Google 登入等待 OAuth 憑證，現在仍可使用原帳密。</p>'
    )
    return f"""<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"theme-color\" content=\"#f5f3ed\"><title>ChordLab 登入</title><link rel=\"icon\" href=\"/static/favicon.svg\"><link rel=\"stylesheet\" href=\"/static/style.css?v=15\"></head><body class=\"login-body\"><main class=\"login-card\"><div class=\"brand-mark\">CL</div><p class=\"eyebrow\">YOUR MUSIC, UNPACKED</p><h1>ChordLab</h1><p class=\"muted\">把一首歌整理成可以播放、閱讀與編輯的和弦、吉他 TAB、歌詞和分軌。</p>{error_html}{google_html}<form method=\"post\" action=\"/login\"><label>帳號<input name=\"username\" autocomplete=\"username\" required autofocus></label><label>密碼<input type=\"password\" name=\"password\" autocomplete=\"current-password\" required></label><button type=\"submit\">進入音樂工作台</button></form></main></body></html>"""


@app.get("/auth/google")
async def google_login(request: Request) -> Response:
    if not GOOGLE_ENABLED:
        return RedirectResponse("/login", status_code=303)
    return await oauth.google.authorize_redirect(request, GOOGLE_REDIRECT_URI)


@app.get("/auth/google/callback")
async def google_callback(request: Request) -> Response:
    if not GOOGLE_ENABLED:
        return RedirectResponse("/login", status_code=303)
    try:
        token = await oauth.google.authorize_access_token(request)
        identity = token.get("userinfo") or {}
        email = str(identity.get("email") or "").lower()
        if not email or not identity.get("email_verified"):
            return RedirectResponse("/login?error=google", status_code=303)
        if GOOGLE_ALLOWED_EMAILS and email not in GOOGLE_ALLOWED_EMAILS:
            return RedirectResponse("/login?error=denied", status_code=303)
    except Exception:
        return RedirectResponse("/login?error=google", status_code=303)
    user = touch_user({"sub": email, "provider": "google"}, str(identity.get("name") or ""))
    if user["is_blocked"]:
        return RedirectResponse("/login?error=blocked", status_code=303)
    max_age = SESSION_DAYS * 86400
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, sign_session(email, "google", int(time.time()) + max_age), max_age=max_age, httponly=True, secure=SECURE_COOKIE, samesite="lax")
    return response


@app.post("/login")
def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]) -> Response:
    peer = request.client.host if request.client else "unknown"
    if peer in {"127.0.0.1", "::1"}:
        peer = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", peer).split(",", 1)[0].strip()
    now = time.time()
    with login_lock:
        if len(login_attempts) >= 5000:
            stale_peers = [
                address for address, stamps in login_attempts.items()
                if not stamps or now - max(stamps) >= 300
            ]
            for address in stale_peers:
                login_attempts.pop(address, None)
            if len(login_attempts) >= 5000:
                oldest_peers = sorted(login_attempts, key=lambda address: max(login_attempts[address]))
                for address in oldest_peers[: len(login_attempts) - 4999]:
                    login_attempts.pop(address, None)
        attempts = [stamp for stamp in login_attempts.get(peer, []) if now - stamp < 300]
        login_attempts[peer] = attempts
        if len(attempts) >= 5:
            return PlainTextResponse("登入嘗試過多，請五分鐘後再試。", status_code=429)
    if not hmac.compare_digest(username, USERNAME) or not hmac.compare_digest(password, PASSWORD):
        with login_lock:
            login_attempts.setdefault(peer, []).append(now)
        return RedirectResponse("/login?error=1", status_code=303)
    with login_lock:
        login_attempts.pop(peer, None)
    identity = {"sub": username.lower(), "provider": "local"}
    touch_user(identity, username)
    max_age = SESSION_DAYS * 86400
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, sign_session(username, "local", int(time.time()) + max_age), max_age=max_age, httponly=True, secure=SECURE_COOKIE, samesite="strict")
    return response


@app.post("/logout")
def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin_page(request: Request) -> FileResponse:
    require_admin(request)
    return FileResponse(STATIC / "admin.html")


LYRIC_CREDIT_PREFIX = re.compile(
    r"^(?:作詞|作词|作曲|詞曲|词曲|編曲|编曲|填詞|填词|譜曲|谱曲|演唱|主唱|"
    r"lyrics?|composer|songwriter)\s*(?:[:：\-—]\s*)?.{1,24}$",
    re.IGNORECASE,
)
LYRIC_KNOWN_HALLUCINATIONS = {"詞曲李宗盛", "词曲李宗盛"}


def clean_lyrics_payload(lyrics: dict | None) -> dict | None:
    """Remove short opening-credit captions that speech models mistake for sung lyrics."""
    if not isinstance(lyrics, dict):
        return lyrics
    cleaned = dict(lyrics)
    segments = []
    for index, segment in enumerate(lyrics.get("segments") or []):
        text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
        compact = re.sub(r"[\s:：\-—·•]+", "", text)
        leading_credit = index < 3 and float(segment.get("start") or 0) < 60 and (
            compact in LYRIC_KNOWN_HALLUCINATIONS
            or (len(text) <= 30 and bool(LYRIC_CREDIT_PREFIX.fullmatch(text)))
        )
        if not text or leading_credit:
            continue
        segments.append(dict(segment) | {"text": text})
    cleaned["segments"] = segments
    return cleaned


def serialize_job(row: sqlite3.Row, include_result: bool = True) -> dict:
    payload = dict(row)
    if include_result:
        payload["result"] = json.loads(payload["result"]) if payload.get("result") else None
        if payload["result"]:
            payload["result"]["lyrics"] = clean_lyrics_payload(payload["result"].get("lyrics"))
            method = payload["result"].get("active_method", "chordino")
            methods = payload["result"].get("methods", {})
            selected = methods.get(method, [])
            if not any(segment.get("chord") != "N" for segment in selected):
                selected = methods.get("basic_pitch", [])
                if any(segment.get("chord") != "N" for segment in selected):
                    payload["result"]["active_method"] = "basic_pitch"
            if not payload["result"].get("key"):
                payload["result"]["key"] = detect_key(selected)
    else:
        payload.pop("result", None)
    return payload


def add_queue_metadata(connection: sqlite3.Connection, payloads: list[dict]) -> None:
    queued = connection.execute("""SELECT id FROM (
        SELECT id,created_at FROM jobs WHERE status='queued'
        UNION ALL SELECT 'tab:'||job_id AS id,created_at FROM guitar_tasks WHERE status='queued'
        ) ORDER BY created_at,id""").fetchall()
    positions = {row["id"]: index for index, row in enumerate(queued, start=1)}
    active_jobs = connection.execute("SELECT (SELECT COUNT(*) FROM jobs WHERE status='working') + (SELECT COUNT(*) FROM guitar_tasks WHERE status='working')").fetchone()[0]
    for payload in payloads:
        payload["queue_position"] = positions.get(payload["id"])
        payload["analysis_workers"] = ANALYSIS_WORKERS
        payload["active_jobs"] = active_jobs
        payload["ahead_count"] = (
            active_jobs + positions[payload["id"]] - 1 if payload["id"] in positions else 0
        )


@app.get("/api/queue")
def queue_status() -> dict:
    with db() as connection:
        working = connection.execute("SELECT (SELECT COUNT(*) FROM jobs WHERE status='working') + (SELECT COUNT(*) FROM guitar_tasks WHERE status='working')").fetchone()[0]
        waiting = connection.execute("SELECT (SELECT COUNT(*) FROM jobs WHERE status='queued') + (SELECT COUNT(*) FROM guitar_tasks WHERE status='queued')").fetchone()[0]
    return {"working": working, "waiting": waiting, "total": working + waiting, "workers": ANALYSIS_WORKERS}


@app.get("/api/jobs")
def list_jobs(request: Request) -> list[dict]:
    identity = request.state.identity
    with db() as connection:
        if is_admin(identity):
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 40").fetchall()
        else:
            rows = connection.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 40", (identity["sub"],)).fetchall()
        payloads = [serialize_job(row, include_result=False) for row in rows]
        for payload in payloads:
            payload["mine"] = payload["owner"] == identity["sub"]
        add_queue_metadata(connection, payloads)
    return payloads


def accessible_job(request: Request, job_id: str) -> sqlite3.Row:
    with db() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    identity = request.state.identity
    public_access = bool(row and row["is_public"] and row["status"] == "done")
    if not row or (not is_admin(identity) and row["owner"] != identity["sub"] and not public_access):
        raise HTTPException(404, "找不到分析工作")
    return row


def editable_job(request: Request, job_id: str) -> sqlite3.Row:
    with db() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    identity = request.state.identity
    if not row or (row["owner"] != identity["sub"] and not is_admin(identity)):
        raise HTTPException(404, "找不到可編輯的分析工作")
    return row


@app.get("/api/jobs/{job_id}")
def get_job(request: Request, job_id: str, include_notes: bool = True) -> dict:
    row = accessible_job(request, job_id)
    payload = serialize_job(row)
    if not include_notes and payload.get("result"):
        payload["result"].pop("notes", None)
    payload["mine"] = payload["owner"] == request.state.identity["sub"]
    if not payload["mine"] and not is_admin(request.state.identity):
        payload.pop("owner", None)
        payload.pop("source", None)
    with db() as connection:
        add_queue_metadata(connection, [payload])
    return payload


def public_summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "duration": row["duration"],
        "note_count": row["note_count"],
        "separate_stems": bool(row["separate_stems"]),
        "separation_model": row["separation_model"],
        "transcribe_lyrics": bool(row["transcribe_lyrics"]),
        "created_at": row["created_at"],
        "public_at": row["public_at"],
        "view_count": row["view_count"],
        "favorite_count": row["favorite_count"],
        "is_favorite": bool(row["is_favorite"]),
    }


@app.get("/api/public/jobs")
def list_public_jobs(
    request: Request,
    search: Annotated[str, Query(max_length=80)] = "",
    sort: Annotated[str, Query()] = "recent",
) -> list[dict]:
    if sort not in {"recent", "views", "favorites"}:
        raise HTTPException(400, "未知的排序方式")
    query = """
        SELECT j.*,
          (SELECT COUNT(*) FROM job_views v WHERE v.job_id=j.id) AS view_count,
          (SELECT COUNT(*) FROM job_favorites f WHERE f.job_id=j.id) AS favorite_count,
          EXISTS(SELECT 1 FROM job_favorites mine WHERE mine.job_id=j.id AND mine.owner=?) AS is_favorite
        FROM jobs j
        WHERE j.is_public=1 AND j.status='done' AND j.title LIKE ?
        ORDER BY
          CASE WHEN ?='views' THEN view_count END DESC,
          CASE WHEN ?='favorites' THEN favorite_count END DESC,
          COALESCE(j.public_at, j.updated_at) DESC,
          j.id DESC
        LIMIT 60
    """
    with db() as connection:
        rows = connection.execute(
            query,
            (request.state.identity["sub"], f"%{search.strip()}%", sort, sort),
        ).fetchall()
    return [public_summary(row) for row in rows]


@app.get("/api/public/jobs/{job_id}")
def get_public_job(request: Request, job_id: str, include_notes: bool = True) -> dict:
    viewer = request.state.identity["sub"]
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id=? AND is_public=1 AND status='done'", (job_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "找不到公開分析")
        connection.execute(
            "INSERT OR IGNORE INTO job_views(job_id,viewer,viewed_at) VALUES (?,?,?)",
            (job_id, viewer, int(time.time())),
        )
        view_count = connection.execute("SELECT COUNT(*) FROM job_views WHERE job_id=?", (job_id,)).fetchone()[0]
        favorite_count = connection.execute("SELECT COUNT(*) FROM job_favorites WHERE job_id=?", (job_id,)).fetchone()[0]
        is_favorite = connection.execute(
            "SELECT 1 FROM job_favorites WHERE job_id=? AND owner=?", (job_id, viewer)
        ).fetchone()
    payload = serialize_job(row)
    if not include_notes and payload.get("result"):
        payload["result"].pop("notes", None)
    payload["mine"] = row["owner"] == viewer
    payload["view_count"] = view_count
    payload["favorite_count"] = favorite_count
    payload["is_favorite"] = bool(is_favorite)
    payload.pop("owner", None)
    payload.pop("source", None)
    return payload


class VisibilityUpdate(BaseModel):
    is_public: bool


@app.put("/api/jobs/{job_id}/visibility")
def update_visibility(request: Request, job_id: str, update: VisibilityUpdate) -> dict:
    with db() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        identity = request.state.identity
        if not row or (row["owner"] != identity["sub"] and not is_admin(identity)):
            raise HTTPException(404, "找不到分析工作")
        if update.is_public and row["status"] != "done":
            raise HTTPException(400, "分析完成後才能公開")
        connection.execute(
            "UPDATE jobs SET is_public=?, public_at=?, updated_at=? WHERE id=?",
            (int(update.is_public), int(time.time()) if update.is_public else None, int(time.time()), job_id),
        )
    return {"ok": True, "is_public": update.is_public}


@app.post("/api/public/jobs/{job_id}/favorite")
def toggle_favorite(request: Request, job_id: str) -> dict:
    owner = request.state.identity["sub"]
    with db() as connection:
        public_job = connection.execute(
            "SELECT 1 FROM jobs WHERE id=? AND is_public=1 AND status='done'", (job_id,)
        ).fetchone()
        if not public_job:
            raise HTTPException(404, "找不到公開分析")
        existing = connection.execute(
            "SELECT 1 FROM job_favorites WHERE job_id=? AND owner=?", (job_id, owner)
        ).fetchone()
        if existing:
            connection.execute("DELETE FROM job_favorites WHERE job_id=? AND owner=?", (job_id, owner))
            favorited = False
        else:
            connection.execute(
                "INSERT INTO job_favorites(job_id,owner,created_at) VALUES (?,?,?)",
                (job_id, owner, int(time.time())),
            )
            favorited = True
        count = connection.execute("SELECT COUNT(*) FROM job_favorites WHERE job_id=?", (job_id,)).fetchone()[0]
    return {"favorited": favorited, "favorite_count": count}


class AdminUserUpdate(BaseModel):
    is_admin: bool | None = None
    is_blocked: bool | None = None


class AdminVisibilityUpdate(BaseModel):
    is_public: bool


class AdminDeleteJob(BaseModel):
    confirm: str


@app.get("/api/admin/overview")
def admin_overview(request: Request) -> dict:
    require_admin(request)
    now = int(time.time())
    with db() as connection:
        users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = connection.execute("SELECT COUNT(*) FROM users WHERE last_seen>=?", (now - 7 * 86400,)).fetchone()[0]
        jobs = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        public_jobs = connection.execute("SELECT COUNT(*) FROM jobs WHERE is_public=1 AND status='done'").fetchone()[0]
        queued = connection.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
        working = connection.execute("SELECT COUNT(*) FROM jobs WHERE status='working'").fetchone()[0]
        failed = connection.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()[0]
    storage = shutil.disk_usage(JOBS)
    return {
        "users": users,
        "active_users_7d": active_users,
        "jobs": jobs,
        "public_jobs": public_jobs,
        "queued": queued,
        "working": working,
        "failed": failed,
        "daily_job_limit": DAILY_JOB_LIMIT,
        "storage": {"total": storage.total, "used": storage.used, "free": storage.free},
    }


@app.get("/api/admin/users")
def admin_users(request: Request) -> list[dict]:
    require_admin(request)
    with db() as connection:
        rows = connection.execute(
            """
            SELECT u.*,
              COUNT(j.id) AS job_count,
              SUM(CASE WHEN j.status IN ('queued','working') THEN 1 ELSE 0 END) AS active_jobs,
              SUM(CASE WHEN j.is_public=1 AND j.status='done' THEN 1 ELSE 0 END) AS public_jobs
            FROM users u
            LEFT JOIN jobs j ON j.owner=u.subject
            GROUP BY u.id
            ORDER BY u.last_seen DESC, u.subject
            LIMIT 300
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "subject": row["subject"],
            "provider": row["provider"],
            "display_name": row["display_name"],
            "is_admin": bool(row["is_admin"]),
            "is_blocked": bool(row["is_blocked"]),
            "configured_admin": configured_admin({"sub": row["subject"], "provider": row["provider"]}),
            "created_at": row["created_at"],
            "last_seen": row["last_seen"],
            "job_count": row["job_count"],
            "active_jobs": row["active_jobs"] or 0,
            "public_jobs": row["public_jobs"] or 0,
        }
        for row in rows
    ]


@app.put("/api/admin/users/{user_id}")
def admin_update_user(request: Request, user_id: str, update: AdminUserUpdate) -> dict:
    actor = require_admin(request)
    if update.is_admin is None and update.is_blocked is None:
        raise HTTPException(400, "沒有要更新的使用者設定")
    with db() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到使用者")
        target_identity = {"sub": row["subject"], "provider": row["provider"]}
        target_configured_admin = configured_admin(target_identity)
        if update.is_admin is False and target_configured_admin:
            raise HTTPException(400, "設定檔指定的管理員不能在網頁中移除權限")
        next_admin = bool(row["is_admin"]) if update.is_admin is None else update.is_admin
        next_blocked = bool(row["is_blocked"]) if update.is_blocked is None else update.is_blocked
        if next_blocked and (next_admin or target_configured_admin):
            raise HTTPException(400, "請先移除管理權限，再停權這個帳號")
        if next_blocked and user_id == identity_key(actor):
            raise HTTPException(400, "不能停權目前登入的帳號")
        connection.execute(
            "UPDATE users SET is_admin=?, is_blocked=? WHERE id=?",
            (int(next_admin), int(next_blocked), user_id),
        )
        audit_admin(
            actor,
            "user.update",
            row["subject"],
            {"is_admin": next_admin, "is_blocked": next_blocked},
            connection,
        )
    return {"ok": True, "is_admin": next_admin, "is_blocked": next_blocked}


@app.get("/api/admin/jobs")
def admin_jobs(
    request: Request,
    status: Annotated[str, Query(max_length=20)] = "",
    search: Annotated[str, Query(max_length=80)] = "",
) -> list[dict]:
    require_admin(request)
    if status and status not in {"queued", "working", "done", "failed"}:
        raise HTTPException(400, "未知的工作狀態")
    term = f"%{search.strip()}%"
    with db() as connection:
        rows = connection.execute(
            """
            SELECT id,title,owner,source_kind,status,progress,message,duration,note_count,
                   is_public,separate_stems,separation_model,created_at,updated_at,error_detail
            FROM jobs
            WHERE (?='' OR status=?) AND (title LIKE ? OR owner LIKE ? OR id LIKE ?)
            ORDER BY created_at DESC
            LIMIT 150
            """,
            (status, status, term, term, term),
        ).fetchall()
    return [dict(row) | {"is_public": bool(row["is_public"]), "separate_stems": bool(row["separate_stems"])} for row in rows]


@app.put("/api/admin/jobs/{job_id}/visibility")
def admin_job_visibility(request: Request, job_id: str, update: AdminVisibilityUpdate) -> dict:
    actor = require_admin(request)
    with db() as connection:
        row = connection.execute("SELECT id,title,status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到分析工作")
        if update.is_public and row["status"] != "done":
            raise HTTPException(400, "只有完成的分析可以公開")
        now = int(time.time())
        connection.execute(
            "UPDATE jobs SET is_public=?, public_at=?, updated_at=? WHERE id=?",
            (int(update.is_public), now if update.is_public else None, now, job_id),
        )
        audit_admin(actor, "job.visibility", job_id, {"title": row["title"], "is_public": update.is_public}, connection)
    return {"ok": True, "is_public": update.is_public}


@app.delete("/api/admin/jobs/{job_id}")
def admin_delete_job(request: Request, job_id: str, update: AdminDeleteJob) -> dict:
    # Keep the status check and deletion atomic relative to new TAB submissions.
    with job_submission_lock:
        return delete_admin_job_locked(request, job_id, update)


def delete_admin_job_locked(request: Request, job_id: str, update: AdminDeleteJob) -> dict:
    actor = require_admin(request)
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not hmac.compare_digest(update.confirm, job_id):
        raise HTTPException(400, "刪除確認不符")
    with db() as connection:
        row = connection.execute("SELECT id,title,status,owner FROM jobs WHERE id=?", (job_id,)).fetchone()
        guitar_task = connection.execute("SELECT status FROM guitar_tasks WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "找不到分析工作")
    if row["status"] in {"queued", "working"} or guitar_task and guitar_task["status"] in {"queued", "working"}:
        raise HTTPException(409, "不能刪除排隊中或處理中的工作")
    source_dir = JOBS / job_id
    trash_root = JOBS / ".admin-trash"
    moved_dir = trash_root / f"{job_id}-{int(time.time())}"
    if source_dir.exists():
        trash_root.mkdir(mode=0o700, exist_ok=True)
        source_dir.rename(moved_dir)
    try:
        with db() as connection:
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            audit_admin(
                actor,
                "job.delete",
                job_id,
                {"title": row["title"], "owner": row["owner"], "status": row["status"]},
                connection,
            )
    except Exception:
        if moved_dir.exists() and not source_dir.exists():
            moved_dir.rename(source_dir)
        raise
    if moved_dir.exists():
        shutil.rmtree(moved_dir)
    return {"ok": True}


@app.get("/api/admin/audit")
def admin_audit_log(request: Request) -> list[dict]:
    require_admin(request)
    with db() as connection:
        rows = connection.execute(
            "SELECT actor,action,target,detail,created_at FROM admin_audit ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return [dict(row) | {"detail": json.loads(row["detail"] or "{}") } for row in rows]


@app.get("/api/jobs/{job_id}/notes/{track}")
def get_track_notes(request: Request, job_id: str, track: str, engine: str = "basic_pitch") -> dict:
    row = accessible_job(request, job_id)
    if not row["result"]:
        raise HTTPException(404, "尚無音符結果")
    result = json.loads(row["result"])
    separation = result.get("separation") or {}
    if engine not in GUITAR_ENGINES or engine != "basic_pitch" and track != "guitar":
        raise HTTPException(400, "未知的吉他辨識引擎")
    if track == "guitar" and engine != "basic_pitch":
        notes_path, _ = guitar_paths(JOBS / job_id, engine)
        path = job_file(job_id, str(notes_path.relative_to(JOBS / job_id)))
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"source": track, **payload}
    if track == separation.get("analysis_stem") or track == "analysis":
        return {"source": separation.get("analysis_stem", "original"), "notes": result.get("notes", [])}
    if track not in set(separation.get("midi_stems", [])):
        raise HTTPException(404, "這個音軌沒有音符資料")
    path = job_file(job_id, f"stem-midi/{track}.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {"source": track, "notes": payload.get("notes", []), "profile": payload.get("profile", "general")}


@app.get("/api/jobs/{job_id}/tab")
def get_personal_tab(request: Request, job_id: str, instrument: Literal["guitar", "bass"] = "guitar") -> dict:
    accessible_job(request, job_id)
    table = "user_bass_tabs" if instrument == "bass" else "user_tabs"
    with db() as connection:
        row = connection.execute(f"SELECT document,revision FROM {table} WHERE job_id=? AND viewer=?",
                                 (job_id, identity_key(request.state.identity))).fetchone()
        reference = connection.execute("SELECT 1 FROM tab_references WHERE job_id=? AND viewer=? AND instrument=?",
            (job_id,identity_key(request.state.identity),instrument)).fetchone()
    return {"document": json.loads(row["document"]) if row else None, "revision": row["revision"] if row else 0,
            "reference_confirmed": bool(reference)}


@app.put("/api/jobs/{job_id}/tab")
def save_personal_tab(request: Request, job_id: str, document: TabDocument, instrument: Literal["guitar", "bass"] = "guitar", confirmed_reference: bool = False) -> dict:
    job = accessible_job(request, job_id)
    if document.instrument != instrument:
        raise HTTPException(400, "樂器與儲存目標不一致")
    if confirmed_reference and not any(note.edited for note in document.notes):
        raise HTTPException(400, "私人校驗資料需包含已核對的手動修正")
    table = "user_bass_tabs" if instrument == "bass" else "user_tabs"
    if job["status"] != "done":
        raise HTTPException(409, "請等分析完成")
    if any(note.end > float(job["duration"] or MAX_DURATION) + .5 for note in document.notes):
        raise HTTPException(400, "音符超過歌曲長度")
    key = identity_key(request.state.identity)
    with db() as connection:
        # Acquire the write lock before checking revision, avoiding lost updates.
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
            raise HTTPException(404, "此分析已被刪除")
        existing = connection.execute(f"SELECT revision FROM {table} WHERE job_id=? AND viewer=?", (job_id, key)).fetchone()
        revision = existing["revision"] if existing else 0
        if document.revision != revision:
            raise HTTPException(409, "另一個分頁已更新此譜，請重新載入後再編輯")
        payload = document.model_dump()
        payload["revision"] = revision + 1
        connection.execute(f"""INSERT INTO {table}(job_id,viewer,revision,document,updated_at) VALUES (?,?,?,?,?)
            ON CONFLICT(job_id,viewer) DO UPDATE SET revision=excluded.revision,
            document=excluded.document,updated_at=excluded.updated_at""",
                           (job_id, key, revision + 1, json.dumps(payload), int(time.time())))
        # A reference is a separately confirmed snapshot, never an automatic label.
        if confirmed_reference:
            connection.execute("""INSERT INTO tab_references(job_id,viewer,instrument,revision,document,updated_at)
                VALUES (?,?,?,?,?,?) ON CONFLICT(job_id,viewer,instrument) DO UPDATE SET
                revision=excluded.revision,document=excluded.document,updated_at=excluded.updated_at""",
                (job_id,key,instrument,revision+1,json.dumps(payload),int(time.time())))
        else:
            # Subsequent unconfirmed saves revoke the earlier training snapshot.
            connection.execute("DELETE FROM tab_references WHERE job_id=? AND viewer=? AND instrument=?", (job_id,key,instrument))
    return {"document": payload, "revision": revision + 1, "reference_confirmed": confirmed_reference}


@app.get("/api/jobs/{job_id}/tab-reference")
def get_tab_reference(request: Request, job_id: str, instrument: Literal["guitar", "bass"] = "guitar"):
    accessible_job(request, job_id)
    with db() as connection:
        row = connection.execute("SELECT document,revision FROM tab_references WHERE job_id=? AND viewer=? AND instrument=?",
            (job_id,identity_key(request.state.identity),instrument)).fetchone()
    if not row:
        raise HTTPException(404, "尚無已確認的私人校驗資料")
    return JSONResponse({"notes": json.loads(row["document"])["notes"], "revision": row["revision"], "instrument": instrument,
                         "kind": "user_confirmed_not_independently_verified"},
                        headers={"Content-Disposition": f'attachment; filename="reference-{instrument}.json"'})


@app.delete("/api/jobs/{job_id}/tab-reference")
def revoke_tab_reference(request: Request, job_id: str, instrument: Literal["guitar", "bass"] = "guitar"):
    accessible_job(request,job_id)
    with db() as connection:
        connection.execute("DELETE FROM tab_references WHERE job_id=? AND viewer=? AND instrument=?",
            (job_id,identity_key(request.state.identity),instrument))
    return {"ok": True}


def guitar_uses_original(row: sqlite3.Row, result: dict) -> bool:
    return bool(row["pure_guitar"]) or (result.get("guitar_tab") or {}).get("source") == "original"


def bass_is_ready(job_id: str, result: dict) -> bool:
    return "bass" in (result.get("separation") or {}).get("midi_stems", []) and all(
        (JOBS / job_id / "stem-midi" / f"bass.{suffix}").is_file() for suffix in ("json", "mid"))


@app.get("/api/jobs/{job_id}/bass-analysis")
def bass_task_status(request: Request, job_id: str) -> dict:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"] or "{}")
    has_source = "bass" in ((result.get("separation") or {}).get("all_stems") or
                            (result.get("separation") or {}).get("stems") or [])
    ready = bass_is_ready(job_id, result)
    status = "done" if ready else (result.get("bass_tab") or {}).get("status", "pending" if has_source else "unavailable")
    with db() as connection:
        task = connection.execute("SELECT engine,status FROM guitar_tasks WHERE job_id=?", (job_id,)).fetchone()
    if task and task["engine"] == "bass":
        status = task["status"]
    return {"status": status, "ready": ready, "available": has_source and BASIC_PYTHON.is_file(),
        "busy_engine": task["engine"] if task and task["status"] in {"queued", "working"} else None}


@app.post("/api/jobs/{job_id}/bass-analysis", status_code=202)
def start_bass_task(request: Request, job_id: str) -> dict:
    row = editable_job(request, job_id)
    result = json.loads(row["result"] or "{}")
    separation = result.get("separation") or {}
    if row["status"] != "done" or "bass" not in (separation.get("all_stems") or separation.get("stems") or []):
        raise HTTPException(400, "這首歌沒有可分析的 Bass 分軌")
    if not BASIC_PYTHON.is_file():
        raise HTTPException(503, "Bass 轉錄環境尚未安裝")
    if bass_is_ready(job_id, result):
        return {"status": "done"}
    job_file(job_id, "stems/bass.wav")
    return enqueue_refinement_task(request, row, "bass")


def process_bass_task(job_id: str) -> None:
    directory = JOBS / job_id / "stem-midi"
    directory.mkdir(mode=0o700, exist_ok=True)
    output, midi = directory / "bass.json", directory / "bass.mid"
    temporary, temporary_midi = output.with_suffix(".json.tmp"), midi.with_suffix(".mid.tmp")
    with heavy_analysis_slot:
        run_command([str(BASIC_PYTHON), str(ROOT / "tools/basic_pitch_worker.py"),
            str(JOBS / job_id / "stems/bass.wav"), str(temporary), str(temporary_midi), "--bass"], timeout=1800)
    payload = json.loads(temporary.read_text())
    if payload.get("profile") != "bass_v1" or not isinstance(payload.get("notes"), list):
        raise ValueError("Invalid Bass transcription output")
    temporary.replace(output)
    temporary_midi.replace(midi)
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            result = json.loads(row["result"] or "{}")
            separation = result.setdefault("separation", {})
            separation["midi_stems"] = list(dict.fromkeys([*separation.get("midi_stems", []), "bass"]))
            separation.setdefault("midi_errors", {}).pop("bass", None)
            result["bass_tab"] = {"status": "done", "profile": "bass_v1", "source": "separated"}
            connection.execute("UPDATE jobs SET result=?,updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), int(time.time()), job_id))
        connection.execute("UPDATE guitar_tasks SET status='done',updated_at=? WHERE job_id=?", (int(time.time()), job_id))


@app.get("/api/jobs/{job_id}/guitar-analysis")
def guitar_task_status(request: Request, job_id: str, engine: str = "basic_pitch") -> dict:
    if engine not in GUITAR_ENGINES:
        raise HTTPException(400, "未知的吉他辨識引擎")
    row = accessible_job(request, job_id)
    with db() as connection:
        task = connection.execute("SELECT status,engine FROM guitar_tasks WHERE job_id=?", (job_id,)).fetchone()
    result = json.loads(row["result"] or "{}")
    status = (result.get("guitar_tab") or {}).get("status", "done" if "guitar" in (result.get("separation") or {}).get("midi_stems", []) else "unavailable")
    if status == "unavailable" and guitar_uses_original(row, result):
        status = "failed" if (result.get("separation") or {}).get("midi_errors", {}).get("guitar") else "pending"
    variants = []
    for name, info in GUITAR_ENGINES.items():
        notes_path, midi_path = guitar_paths(JOBS / job_id, name)
        ready = notes_path.is_file() and midi_path.is_file()
        if name == "basic_pitch":
            ready = ready or "guitar" in (result.get("separation") or {}).get("midi_stems", [])
        variants.append({"engine": name, "label": info["label"], "available": guitar_engine_available(ROOT, name), "ready": ready})
        if name == engine and name != "basic_pitch":
            status = "done" if ready else (result.get("guitar_tab") or {}).get("variants", {}).get(name, {}).get("status", "pending")
    if task and task["engine"] == engine:
        status = task["status"]
    return {"status": status, "engine": engine, "variants": variants,
            "busy_engine": task["engine"] if task and task["status"] in {"queued", "working"} else None}


@app.get("/api/jobs/{job_id}/guitar-midi/{engine}")
def get_guitar_engine_midi(request: Request, job_id: str, engine: str):
    row = accessible_job(request, job_id)
    if engine not in GUITAR_ENGINES:
        raise HTTPException(400, "未知的吉他辨識引擎")
    _, path = guitar_paths(JOBS / job_id, engine)
    return FileResponse(job_file(job_id, str(path.relative_to(JOBS / job_id))), media_type="audio/midi",
                        filename=f"{safe_title(row['title'])}-{engine}.mid")


@app.get("/api/jobs/{job_id}/verification-preview")
def verification_preview(request: Request, job_id: str):
    accessible_job(request, job_id)
    return FileResponse(job_file(job_id,"stem-midi/guitar-verified.preview.wav"), media_type="audio/wav")


@app.post("/api/jobs/{job_id}/guitar-analysis", status_code=202)
def start_guitar_task(request: Request, job_id: str, engine: str = "basic_pitch") -> dict:
    row = editable_job(request, job_id)
    if engine not in GUITAR_ENGINES:
        raise HTTPException(400, "未知的吉他辨識引擎")
    if not guitar_engine_available(ROOT, engine):
        raise HTTPException(503, "這個吉他辨識引擎尚未安裝")
    result = json.loads(row["result"] or "{}")
    separation = result.get("separation") or {}
    original = guitar_uses_original(row, result)
    if row["status"] != "done" or not original and "guitar" not in (separation.get("all_stems") or separation.get("stems") or []):
        raise HTTPException(400, "這首歌沒有可分析的吉他分軌")
    notes_path, midi_path = guitar_paths(JOBS / job_id, engine)
    if (engine == "basic_pitch" and "guitar" in separation.get("midi_stems", [])) or notes_path.is_file() and midi_path.is_file():
        return {"status": "done"}
    job_file(job_id, "audio.wav" if original else "stems/guitar.wav")
    if engine == "verified" and not any(guitar_paths(JOBS / job_id, name)[0].is_file() for name in ("hybrid","gaps","basic_pitch","tabcnn")):
        raise HTTPException(400, "請先產生一個吉他音符版本，再進行音訊校驗")
    return enqueue_refinement_task(request, row, engine)


def enqueue_refinement_task(request: Request, row: sqlite3.Row, engine: str) -> dict:
    """Shared durable queue and quotas for optional heavy refinement work."""
    job_id = row["id"]
    with job_submission_lock:
        with db() as connection:
            task = connection.execute("SELECT * FROM guitar_tasks WHERE job_id=?", (job_id,)).fetchone()
            if task and task["status"] in {"queued", "working"}:
                if task["engine"] != engine:
                    raise HTTPException(409, "這首歌已有另一個進階分析，請等它完成")
                return {"status": task["status"]}
            if task and task["engine"] == engine and task["attempts"] >= 3:
                raise HTTPException(429, "已重試三次，請聯絡管理員")
            active = connection.execute("""SELECT
                (SELECT COUNT(*) FROM jobs WHERE owner=? AND status IN ('queued','working')) +
                (SELECT COUNT(*) FROM guitar_tasks t JOIN jobs j ON j.id=t.job_id WHERE j.owner=? AND t.status IN ('queued','working'))""", (row["owner"], row["owner"])).fetchone()[0]
            if active >= MAX_ACTIVE_PER_USER:
                raise HTTPException(429, "你的分析工作已達上限，請等待前一個完成")
            if not is_admin(request.state.identity):
                recent = connection.execute("SELECT COUNT(*) FROM guitar_submissions WHERE owner=? AND created_at>=?", (row["owner"], int(time.time()) - 86400)).fetchone()[0]
                if recent >= DAILY_JOB_LIMIT:
                    raise HTTPException(429, "今日進階分析額度已用完")
            now = int(time.time())
            connection.execute("""INSERT INTO guitar_tasks(job_id,status,engine,created_at,updated_at) VALUES (?,'queued',?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET status='queued',
                attempts=CASE WHEN guitar_tasks.engine=excluded.engine THEN attempts+1 ELSE 1 END,
                engine=excluded.engine,created_at=excluded.created_at,updated_at=excluded.updated_at""", (job_id, engine, now, now))
            connection.execute("INSERT INTO guitar_submissions(job_id,owner,engine,created_at) VALUES (?,?,?,?)", (job_id, row["owner"], engine, now))
        executor.submit(process_guitar_task, job_id)
    return {"status": "queued"}


@app.get("/api/jobs/{job_id}/chord-refinement")
def chord_refinement_status(request: Request, job_id: str) -> dict:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"] or "{}")
    ready = bool(result.get("methods", {}).get("chord_v2"))
    status = "done" if ready else result.get("chord_refinement", {}).get("status", "pending")
    with db() as connection:
        task = connection.execute("SELECT status,engine FROM guitar_tasks WHERE job_id=?", (job_id,)).fetchone()
    if task and task["engine"] == "chord_v2":
        status = task["status"]
    return {"status": status, "ready": ready, "available": GUITAR_PYTHON.is_file(),
        "busy_engine": task["engine"] if task and task["status"] in {"queued", "working"} else None}


@app.post("/api/jobs/{job_id}/chord-refinement", status_code=202)
def start_chord_refinement(request: Request, job_id: str) -> dict:
    row = editable_job(request, job_id)
    result = json.loads(row["result"] or "{}")
    if row["status"] != "done" or not result.get("methods"):
        raise HTTPException(400, "請先完成原本分析")
    if not GUITAR_PYTHON.is_file():
        raise HTTPException(503, "和弦 v2 環境尚未安裝")
    if result.get("methods", {}).get("chord_v2"):
        return {"status": "done"}
    job_file(job_id, "audio.wav")
    return enqueue_refinement_task(request, row, "chord_v2")


def process_chord_refinement(job_id: str, initial: sqlite3.Row) -> None:
    directory = JOBS / job_id
    result = json.loads(initial["result"] or "{}")
    separation = result.get("separation") or {}
    stem = separation.get("analysis_stem", "original")
    # Select only known stem paths, never an arbitrary path from metadata.
    source = directory / "stems" / f"{stem}.wav" if stem in {"harmony", "other", "guitar"} else directory / "audio.wav"
    baseline = directory / "chordino.json"
    if not baseline.is_file() or not any(s.get("chord") != "N" for s in json.loads(baseline.read_text()).get("chords", [])):
        baseline = directory / "basic_pitch.json"
    output = directory / "harmony-v2.json"
    temporary = output.with_suffix(".json.tmp")
    command = [str(GUITAR_PYTHON), str(ROOT / "tools/harmony_worker.py"), str(source), str(baseline), str(temporary)]
    if (directory / "btc.json").is_file():
        command += ["--btc", str(directory / "btc.json")]
    if "bass" in separation.get("stems", []) and (directory / "stems/bass.wav").is_file():
        command += ["--bass", str(directory / "stems/bass.wav")]
    with heavy_analysis_slot:
        run_command(command, timeout=600)
    refined = json.loads(temporary.read_text())
    if refined.get("summary", {}).get("version") != 2 or not isinstance(refined.get("chords"), list) or not refined["chords"]:
        raise ValueError("Invalid chord refinement output")
    temporary.replace(output)
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            latest = json.loads(row["result"] or "{}")
            latest.setdefault("methods", {})["chord_v2"] = refined["chords"]
            latest["chord_refinement"] = {**refined["summary"], "status": "done"}
            # Keep active_method, key and any concurrent manual corrections.
            connection.execute("UPDATE jobs SET result=?,updated_at=? WHERE id=?", (json.dumps(latest, ensure_ascii=False), int(time.time()), job_id))
        connection.execute("UPDATE guitar_tasks SET status='done',updated_at=? WHERE job_id=?", (int(time.time()), job_id))


def process_guitar_task(job_id: str) -> None:
    with db() as connection:
        initial = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not initial:
            return
        original = guitar_uses_original(initial, json.loads(initial["result"] or "{}"))
        task = connection.execute("SELECT engine FROM guitar_tasks WHERE job_id=?", (job_id,)).fetchone()
        engine = task["engine"] if task else "basic_pitch"
        connection.execute("UPDATE guitar_tasks SET status='working',updated_at=? WHERE job_id=?", (int(time.time()), job_id))
    try:
        if engine == "bass":
            process_bass_task(job_id)
            return
        if engine == "chord_v2":
            process_chord_refinement(job_id, initial)
            return
        with heavy_analysis_slot:
            if engine != "basic_pitch":
                stems, errors = transcribe_guitar_tab(job_id, JOBS / job_id,
                    direct_source=JOBS / job_id / "audio.wav" if original else None, engine=engine)
            elif original:
                stems, errors = transcribe_guitar_tab(job_id, JOBS / job_id, direct_source=JOBS / job_id / "audio.wav")
            else:
                stems, errors = transcribe_guitar_tab(job_id, JOBS / job_id)
        status = "done" if "guitar" in stems else "failed"
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row:
                result = json.loads(row["result"] or "{}")
                separation = result.setdefault("separation", {})
                if engine == "basic_pitch":
                    separation["midi_stems"] = list(dict.fromkeys([*separation.get("midi_stems", []), *stems]))
                    separation.setdefault("midi_errors", {}).update(errors)
                    if status == "done":
                        separation["midi_errors"].pop("guitar", None)
                    variants = (result.get("guitar_tab") or {}).get("variants")
                    result["guitar_tab"] = {"profile": "guitar_v2" if status == "done" else None, "source": "original" if original else "separated", "status": status}
                    if variants:
                        result["guitar_tab"]["variants"] = variants
                else:
                    guitar = result.setdefault("guitar_tab", {"source": "original" if original else "separated", "status": "pending"})
                    guitar.setdefault("variants", {})[engine] = {"profile": GUITAR_ENGINES[engine]["profile"], "status": status}
                connection.execute("UPDATE jobs SET result=?,progress=100,message='分析完成',updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), int(time.time()), job_id))
            connection.execute("UPDATE guitar_tasks SET status=?,updated_at=? WHERE job_id=?", (status, int(time.time()), job_id))
    except Exception as exc:
        log_job_error(job_id, "guitar-task", exc)
        with db() as connection:
            connection.execute("UPDATE guitar_tasks SET status='failed',updated_at=? WHERE job_id=?", (int(time.time()), job_id))
            if engine in {"chord_v2", "bass"}:
                row = connection.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row:
                    result = json.loads(row["result"] or "{}")
                    result["bass_tab" if engine == "bass" else "chord_refinement"] = {"status": "failed"}
                    connection.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), job_id))


def update_job(job_id: str, **changes) -> None:
    fields = ("title", "status", "progress", "message", "duration", "note_count", "result", "error_detail")
    allowed = set(fields)
    if not changes or not set(changes).issubset(allowed):
        raise ValueError("不允許的工作欄位更新")
    values: list[object] = []
    for field in fields:
        values.extend((int(field in changes), changes.get(field)))
    values.extend((int(time.time()), job_id))
    with db() as connection:
        connection.execute(
            """
            UPDATE jobs SET
              title=CASE WHEN ? THEN ? ELSE title END,
              status=CASE WHEN ? THEN ? ELSE status END,
              progress=CASE WHEN ? THEN ? ELSE progress END,
              message=CASE WHEN ? THEN ? ELSE message END,
              duration=CASE WHEN ? THEN ? ELSE duration END,
              note_count=CASE WHEN ? THEN ? ELSE note_count END,
              result=CASE WHEN ? THEN ? ELSE result END,
              error_detail=CASE WHEN ? THEN ? ELSE error_detail END,
              updated_at=?
            WHERE id=?
            """,
            values,
        )


def ensure_public_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "請輸入完整的 http(s) 音樂網址")
    if parsed.username or parsed.password:
        raise HTTPException(400, "音樂網址不能包含帳號或密碼")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "網址連接埠格式錯誤") from exc
    if port not in {None, 80, 443}:
        raise HTTPException(400, "音樂網址只允許標準 HTTP／HTTPS 連接埠")
    hostname = parsed.hostname.lower().rstrip(".")
    if not any(hostname == allowed or hostname.endswith("." + allowed) for allowed in ALLOWED_HOSTS):
        raise HTTPException(400, "此網域未開放自動下載；請改用上傳音檔")
    youtube_id: str | None = None
    if hostname == "youtu.be" or hostname.endswith(".youtu.be"):
        youtube_id = parsed.path.strip("/").split("/", 1)[0]
    elif hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        if parsed.path.rstrip("/") == "/watch":
            youtube_id = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] in {"embed", "live", "shorts"}:
                youtube_id = path_parts[1]
    if youtube_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id):
        raise HTTPException(400, "YouTube 網址不完整：影片 ID 應為 11 碼，請重新複製完整分享連結")
    try:
        default_port = 443 if parsed.scheme == "https" else 80
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port or default_port, type=socket.SOCK_STREAM)}
        if not addresses or any(ipaddress.ip_address(address).is_private or ipaddress.ip_address(address).is_loopback or ipaddress.ip_address(address).is_reserved for address in addresses):
            raise HTTPException(400, "基於伺服器安全，不能存取內網網址")
    except socket.gaierror as exc:
        raise HTTPException(400, "網址主機無法解析") from exc
    return value.strip()


def safe_title(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", " ", value).strip()
    return cleaned[:120] or "未命名分析"


@app.post("/api/jobs", status_code=202)
async def create_job(
    request: Request,
    url: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    file: UploadFile | None = File(default=None),
    separate_stems: Annotated[bool, Form()] = False,
    separation_model: Annotated[str, Form()] = "htdemucs",
    stem_midi: Annotated[bool, Form()] = False,
    transcribe_lyrics: Annotated[bool, Form()] = False,
    pure_guitar: Annotated[bool, Form()] = False,
    review_guitar: Annotated[bool, Form()] = False,
    is_public: Annotated[bool, Form()] = False,
) -> dict:
    if bool(url and url.strip()) == bool(file and file.filename):
        raise HTTPException(400, "請選擇網址或音檔其中一種")
    if pure_guitar:
        separate_stems = False
        stem_midi = False
    owner = request.state.identity["sub"]
    with db() as connection:
        active_count = active_jobs_for_owner(connection, owner)
    if active_count >= MAX_ACTIVE_PER_USER:
        raise HTTPException(429, f"你已有 {MAX_ACTIVE_PER_USER} 個工作正在處理或排隊，請完成後再加入")
    job_id = uuid.uuid4().hex
    job_dir = JOBS / job_id
    job_dir.mkdir(mode=0o700)
    source = "upload"
    if file and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm", ".mp4"}:
            shutil.rmtree(job_dir)
            raise HTTPException(400, "不支援這個檔案格式")
        incoming = job_dir / f"source{suffix}"
        size = 0
        try:
            with incoming.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "檔案超過大小限制")
                    target.write(chunk)
            incoming.chmod(0o600)
            await run_in_threadpool(validate_uploaded_media, incoming)
        except HTTPException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        except MediaValidationError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, str(exc)) from exc
        finally:
            await file.close()
        display_title = safe_title(title or Path(file.filename).stem)
        source_detail = file.filename
    else:
        source = "url"
        try:
            source_detail = await run_in_threadpool(ensure_public_url, url or "")
        except HTTPException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        display_title = safe_title(title or "網址匯入")
    if separation_model not in {"htdemucs", "htdemucs_6s"}:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, "未知的分軌模型")
    if not separate_stems:
        separation_model = "htdemucs"
        stem_midi = False
    if source == "url":
        with db() as connection:
            candidates = connection.execute(
                """
                SELECT id, result FROM jobs
                WHERE source=? AND source_kind='url' AND status='done' AND is_public=1
                  AND separate_stems=? AND separation_model=?
                  AND stem_midi>=? AND transcribe_lyrics>=? AND pure_guitar=?
                ORDER BY updated_at DESC LIMIT 8
                """,
                (source_detail, int(separate_stems), separation_model, int(stem_midi), int(transcribe_lyrics), int(pure_guitar)),
            ).fetchall()
        duplicate = None
        for candidate in candidates:
            if pure_guitar or separation_model == "htdemucs_6s":
                candidate_result = json.loads(candidate["result"] or "{}")
                if "guitar" not in (candidate_result.get("separation") or {}).get("midi_stems", []):
                    continue
                if (candidate_result.get("guitar_tab") or {}).get("profile") != "guitar_v2":
                    continue
            duplicate = candidate
            break
        if duplicate:
            shutil.rmtree(job_dir, ignore_errors=True)
            return {"id": duplicate["id"], "status": "done", "reused": True}
    now = int(time.time())
    with job_submission_lock:
        with db() as connection:
            active_count = active_jobs_for_owner(connection, owner)
            if active_count >= MAX_ACTIVE_PER_USER:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(429, f"你已有 {MAX_ACTIVE_PER_USER} 個工作正在處理或排隊，請完成後再加入")
            if not is_admin(request.state.identity):
                daily_count = connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE owner=? AND created_at>=?", (owner, now - 86400)
                ).fetchone()[0]
                if daily_count >= DAILY_JOB_LIMIT:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(429, f"你在最近 24 小時已使用 {DAILY_JOB_LIMIT} 次分析額度")
            connection.execute(
                "INSERT INTO jobs (id,title,source,source_kind,status,progress,message,separate_stems,separation_model,stem_midi,transcribe_lyrics,pure_guitar,is_public,public_at,owner,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, display_title, source_detail, source, "queued", 2, "等待處理", int(separate_stems), separation_model, int(stem_midi), int(transcribe_lyrics), int(pure_guitar), int(is_public), now if is_public else None, owner, now, now),
            )
            connection.execute("UPDATE jobs SET review_guitar=? WHERE id=?", (int(review_guitar), job_id))
        if source == "url":
            schedule_download(job_id, source_detail)
        executor.submit(process_job, job_id, source, source_detail, separate_stems, separation_model, stem_midi, transcribe_lyrics, pure_guitar, review_guitar=review_guitar)
    return {"id": job_id, "status": "queued"}


def command_environment(overrides: dict | None = None) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR")
    environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    environment.update({
        "HOME": str(ROOT.parent),
        "XDG_CACHE_HOME": str(ROOT.parent / ".cache"),
        "TORCH_HOME": str(ROOT.parent / ".cache" / "torch"),
        # Bubblewrap mounts a fresh private tmpfs at /tmp for every child process.
        "NUMBA_CACHE_DIR": "/tmp/numba",  # nosec B108
        "MPLCONFIGDIR": "/tmp/matplotlib",  # nosec B108
        "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
        "TF_NUM_INTRAOP_THREADS": "2", "TF_NUM_INTEROP_THREADS": "1",
    })
    if overrides:
        environment.update(overrides)
    return environment


def sandbox_command(command: list[str], allow_network: bool) -> list[str]:
    if not BWRAP or not BWRAP.is_file():
        raise RuntimeError("分析沙箱 bwrap 尚未安裝")
    arguments = [
        str(BWRAP), "--die-with-parent", "--new-session", "--unshare-all",
        # This /tmp is intentionally replaced rather than shared with the host.
        "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",  # nosec B108
        "--tmpfs", str(ROOT.parent), "--ro-bind", str(ROOT), str(ROOT),
        "--tmpfs", str(DATA), "--ro-bind", "/dev/null", str(ROOT / ".env"),
    ]
    if allow_network:
        arguments.append("--share-net")
    cache = ROOT.parent / ".cache"
    if cache.is_dir():
        arguments.extend(("--ro-bind", str(cache), str(cache)))
    uv_python = ROOT.parent / ".local" / "share" / "uv" / "python"
    if uv_python.is_dir():
        arguments.extend(("--ro-bind", str(uv_python), str(uv_python)))
    runtime = Path(f"/run/user/{os.getuid()}")
    if runtime.is_dir():
        arguments.extend(("--tmpfs", str(runtime)))
    if STORAGE_MOUNT and STORAGE_MOUNT.is_dir():
        arguments.extend(("--tmpfs", str(STORAGE_MOUNT)))
    mounted_jobs: set[Path] = set()
    readonly_jobs: set[Path] = set()
    jobs_root = JOBS.resolve()
    for index, item in enumerate(command):
        if not item.startswith("/"):
            continue
        candidate = Path(item).resolve(strict=False)
        try:
            relative = candidate.relative_to(jobs_root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        target = jobs_root / relative.parts[0]
        if index and command[index-1] == "--reference-audio":
            readonly_jobs.add(target)
        else:
            mounted_jobs.add(target)
    for job_dir in sorted(mounted_jobs):
        if job_dir.is_dir():
            arguments.extend(("--bind", str(job_dir), str(job_dir)))
    for job_dir in sorted(readonly_jobs - mounted_jobs):
        if job_dir.is_dir():
            arguments.extend(("--ro-bind", str(job_dir), str(job_dir)))
    arguments.extend(("--chdir", str(ROOT), "--", *command))
    return arguments


def run_command(
    command: list[str], *, env: dict | None = None, timeout: int = 1800, allow_network: bool = False
) -> subprocess.CompletedProcess:
    # The command is an argv list using fixed local binaries; shell execution is never enabled.
    isolated_command = sandbox_command(command, allow_network)
    result = subprocess.run(
        isolated_command,
        cwd=ROOT,
        env=command_environment(env),
        text=True,
        capture_output=True,
        timeout=timeout,
    )  # nosec B603
    if result.returncode:
        diagnostic = (result.stderr or result.stdout or "未知錯誤")[-3000:]
        raise RuntimeError(diagnostic)
    return result


class MediaValidationError(ValueError):
    """A safe, user-facing rejection reason for an untrusted upload."""


def validate_uploaded_media(source: Path) -> None:
    """Verify file content with lightweight signatures and sandboxed ffprobe."""
    try:
        with source.open("rb") as uploaded:
            sample = uploaded.read(4096)
    except OSError as exc:
        raise MediaValidationError("無法讀取上傳檔案") from exc
    if not sample:
        raise MediaValidationError("上傳檔案是空的")

    lowered = sample.lstrip().lower()
    executable_headers = (b"\x7felf", b"mz", b"#!")
    script_markers = (b"<?php", b"<script", b"<html", b"<!doctype html")
    if lowered.startswith(executable_headers) or any(marker in lowered for marker in script_markers):
        raise MediaValidationError("檔案內容是程式或網頁，不是可接受的音訊／影片")

    try:
        probe = run_command([
            str(FFPROBE), "-v", "error", "-probesize", "10M", "-analyzeduration", "15M",
            "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
            "-of", "json", str(source),
        ], timeout=30)
        metadata = json.loads(probe.stdout)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError) as exc:
        raise MediaValidationError("檔案內容不是可辨識的音訊或影片") from exc

    streams = metadata.get("streams") or []
    if not any(stream.get("codec_type") == "audio" and stream.get("codec_name") for stream in streams):
        raise MediaValidationError("檔案中找不到可辨識的音訊軌")
    format_names = set(str((metadata.get("format") or {}).get("format_name") or "").split(","))
    if not format_names.intersection(SAFE_MEDIA_FORMATS):
        raise MediaValidationError("檔案實際格式不在允許的音訊／影片清單中")
    duration_value = (metadata.get("format") or {}).get("duration")
    try:
        duration = float(duration_value)
    except (TypeError, ValueError):
        duration = 0
    if duration and (not math.isfinite(duration) or duration > MAX_DURATION + 1):
        raise MediaValidationError(f"音訊超過 {MAX_DURATION // 60} 分鐘限制")


def log_job_error(job_id: str, stage: str, error: Exception) -> None:
    print(f"ChordLab job {job_id} failed during {stage}: {str(error)[-3000:]}", flush=True)


def normalize_audio(source: Path, destination: Path) -> float:
    run_command([str(FFMPEG), "-nostdin", "-y", "-i", str(source), "-t", str(MAX_DURATION + 1), "-vn", "-ac", "1", "-ar", "22050", "-c:a", "pcm_s16le", str(destination)], timeout=600)
    with wave.open(str(destination), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    if duration < 1:
        raise RuntimeError("音訊長度不足一秒")
    if duration > MAX_DURATION:
        raise RuntimeError(f"音訊超過 {MAX_DURATION // 60} 分鐘限制")
    return duration


def separate_audio(job_id: str, source: Path, directory: Path, model: str) -> tuple[Path, list[str]]:
    if not DEMUCS_PYTHON.exists():
        raise RuntimeError("四軌分離引擎尚未安裝完成")
    demucs_input = directory / "separation-input.wav"
    update_job(job_id, progress=30, message="準備四軌分離音訊")
    run_command([
        str(FFMPEG), "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100",
        "-c:a", "pcm_s16le", str(demucs_input),
    ], timeout=600)
    output_root = directory / "demucs-output"
    detailed = model == "htdemucs_6s"
    update_job(job_id, progress=36, message="分離六軌：人聲、Bass、鼓、吉他、鋼琴與其他樂器" if detailed else "分離人聲、Bass、鼓與其他樂器（CPU 會需要一段時間）")
    demucs_env = {"PATH": f"{ROOT / 'bin'}:{os.environ.get('PATH', '')}"}
    run_command([
        str(DEMUCS_PYTHON), "-m", "demucs.separate",
        "--name", model, "--device", "cpu", "--shifts", "0", "--overlap", "0.1", "--jobs", "1",
        "--mp3", "--mp3-bitrate", "320",
        "--out", str(output_root), str(demucs_input),
    ], env=demucs_env, timeout=5400)
    generated = output_root / model / demucs_input.stem
    stems = directory / "stems"
    stems.mkdir(mode=0o700, exist_ok=True)
    stem_names = ["vocals", "bass", "drums", "other"] + (["guitar", "piano"] if detailed else [])
    for stem in stem_names:
        candidate = generated / f"{stem}.mp3"
        if not candidate.is_file():
            raise RuntimeError(f"四軌分離完成，但缺少 {stem} 音軌")
        run_command([
            str(FFMPEG), "-nostdin", "-y", "-i", str(candidate), "-ac", "2", "-ar", "44100",
            "-c:a", "pcm_s16le", str(stems / f"{stem}.wav"),
        ], timeout=600)
    shutil.rmtree(output_root, ignore_errors=True)
    demucs_input.unlink(missing_ok=True)
    if detailed:
        harmony = stems / "harmony.wav"
        run_command([
            str(FFMPEG), "-nostdin", "-y", "-i", str(stems / "other.wav"), "-i", str(stems / "guitar.wav"),
            "-i", str(stems / "piano.wav"), "-filter_complex", "amix=inputs=3:normalize=1", "-ac", "2", "-ar", "44100",
            "-c:a", "pcm_s16le", str(harmony),
        ], timeout=600)
        return harmony, ["original", "harmony", *stem_names]
    return stems / "other.wav", ["original", *stem_names]


def download_url(job_id: str, url: str, directory: Path) -> tuple[Path, str]:
    update_job(job_id, progress=8, message="讀取網址資訊")
    ytdlp_args = [
        str(YTDLP), "--ignore-config", "--no-cache-dir",
        "--js-runtimes", f"deno:{DENO}",
    ]
    metadata = run_command([*ytdlp_args, "--dump-single-json", "--no-playlist", "--socket-timeout", "15", url], timeout=90, allow_network=True)
    info = json.loads(metadata.stdout)
    duration = float(info.get("duration") or 0)
    if duration and duration > MAX_DURATION:
        raise RuntimeError(f"音訊超過 {MAX_DURATION // 60} 分鐘限制")
    title = safe_title(str(info.get("title") or "網址匯入"))
    output = directory / "download.%(ext)s"
    for stale_download in directory.glob("download.*"):
        if stale_download.is_file() or stale_download.is_symlink():
            stale_download.unlink(missing_ok=True)
    update_job(job_id, title=title, progress=14, message="下載音訊")
    run_command([
        *ytdlp_args, "--no-playlist", "--no-part", "--restrict-filenames", "--max-filesize", str(MAX_UPLOAD),
        "-f", "bestaudio/best", "-o", str(output), url,
    ], timeout=900, allow_network=True)
    candidates = [path for path in directory.glob("download.*") if path.is_file()]
    if not candidates:
        raise RuntimeError("下載完成但找不到音訊檔")
    return candidates[0], title


def schedule_download(job_id: str, url: str) -> None:
    # Optional prefetch. Saturated preparation falls back to the existing queue,
    # without rejecting a valid submitted analysis or accumulating unlimited RAM.
    download_preparation.submit(job_id, download_url, job_id, url, JOBS / job_id)


def active_jobs_for_owner(connection: sqlite3.Connection, owner: str) -> int:
    return connection.execute("""SELECT
        (SELECT COUNT(*) FROM jobs WHERE owner=? AND status IN ('queued','working')) +
        (SELECT COUNT(*) FROM guitar_tasks t JOIN jobs j ON j.id=t.job_id WHERE j.owner=? AND t.status IN ('queued','working'))""", (owner, owner)).fetchone()[0]


KEY_NAMES = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
KEY_ROOTS = {"C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4,
             "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10,
             "Bb": 10, "B": 11, "Cb": 11}
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def detect_key(chords: list[dict]) -> dict | None:
    chroma = [0.0] * 12
    for segment in chords:
        label = str(segment.get("chord") or "")
        match = re.match(r"^([A-G](?:#|b)?)(.*)$", label)
        if not match or match.group(1) not in KEY_ROOTS or label == "N":
            continue
        root = KEY_ROOTS[match.group(1)]
        quality = match.group(2).lower()
        minor = quality.startswith("m") and not quality.startswith("maj")
        diminished = "dim" in quality or "b5" in quality
        tones = (0, 3, 6) if diminished else ((0, 3, 7) if minor else (0, 4, 7))
        duration = max(0.05, float(segment.get("end", 0)) - float(segment.get("start", 0)))
        for index, interval in enumerate(tones):
            chroma[(root + interval) % 12] += duration * (1.35 if index == 0 else 0.7)
    if not any(chroma):
        return None
    scores: list[tuple[float, int, str]] = []
    for tonic in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            score = sum(chroma[pitch] * profile[(pitch - tonic) % 12] for pitch in range(12))
            scores.append((score, tonic, mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    confidence = max(0.0, min(0.99, (best[0] - second[0]) / max(best[0], 1e-9) * 4))
    return {"tonic": KEY_NAMES[best[1]], "pitch_class": best[1], "mode": best[2], "label": f"{KEY_NAMES[best[1]]} {best[2]}", "confidence": round(confidence, 3)}


def transcribe_stem_midis(job_id: str, directory: Path, stem_names: list[str], analysis_stem: str, midi_output: Path) -> tuple[list[str], dict[str, str]]:
    output_dir = directory / "stem-midi"
    output_dir.mkdir(mode=0o700, exist_ok=True)
    completed: list[str] = []
    failures: dict[str, str] = {}
    if analysis_stem in stem_names:
        shutil.copyfile(midi_output, output_dir / f"{analysis_stem}.mid")
        completed.append(analysis_stem)
    pitched_stems = [name for name in stem_names if name not in {"original", "drums", analysis_stem}]
    for index, stem in enumerate(pitched_stems, start=1):
        update_job(job_id, progress=min(90, 68 + index * 3), message=f"轉錄 {stem} 分軌 MIDI（{index}/{len(pitched_stems)}）")
        source = directory / "stems" / f"{stem}.wav"
        if not source.is_file():
            continue
        try:
            run_command([
                str(BASIC_PYTHON), str(ROOT / "tools" / "basic_pitch_worker.py"), str(source),
                str(output_dir / f"{stem}.json"), str(output_dir / f"{stem}.mid"),
                *(["--guitar"] if stem == "guitar" else []),
                *(["--bass"] if stem == "bass" else []),
            ], timeout=1800)
            completed.append(stem)
        except Exception as exc:
            log_job_error(job_id, f"stem-midi:{stem}", exc)
            failures[stem] = "轉錄失敗"
    return completed, failures


def transcribe_guitar_tab(job_id: str, directory: Path, direct_source: Path | None = None, engine: str = "basic_pitch") -> tuple[list[str], dict[str, str]]:
    output_dir = directory / "stem-midi"
    output_dir.mkdir(mode=0o700, exist_ok=True)
    source = direct_source if direct_source is not None else directory / "stems" / "guitar.wav"
    if not source.is_file():
        return [], {"guitar": "找不到純吉他音訊" if direct_source is not None else "六軌分離未產生吉他音軌"}
    update_job(job_id, progress=88, message="辨識純吉他原音，產生 TAB" if direct_source is not None else "只分析吉他獨立軌，產生連續 TAB")
    try:
        if engine != "basic_pitch":
            notes_path, midi_path = guitar_paths(directory, engine)
            temporary_notes, temporary_midi = notes_path.with_suffix(".json.tmp"), midi_path.with_suffix(".mid.tmp")
            if engine == "verified":
                base = next((guitar_paths(directory, name)[0] for name in ("hybrid","gaps","basic_pitch","tabcnn") if guitar_paths(directory,name)[0].is_file()), None)
                if base is None:
                    raise ValueError("Verification needs an existing note version")
                references = []
                with db() as connection:
                    owner = connection.execute("SELECT owner FROM jobs WHERE id=?", (job_id,)).fetchone()
                    rows = connection.execute("""SELECT r.job_id,r.document,j.result,j.pure_guitar FROM tab_references r
                        JOIN users u ON u.id=r.viewer JOIN jobs j ON j.id=r.job_id
                        WHERE u.subject=? AND r.instrument='guitar' AND j.status='done'
                        AND (j.owner=? OR j.is_public=1) ORDER BY r.updated_at DESC LIMIT 8""", (owner["owner"], owner["owner"])).fetchall() if owner else []
                for row in rows:
                    audio = JOBS / row["job_id"] / ("audio.wav" if guitar_uses_original(row,json.loads(row["result"] or "{}")) else "stems/guitar.wav")
                    if audio.is_file():
                        references.append({"audio": str(audio), "notes": json.loads(row["document"])["notes"]})
                reference_path = output_dir / "verification-references.private.json"
                preview_path = output_dir / "guitar-verified.preview.wav.tmp"
                try:
                    reference_path.write_text(json.dumps(references), encoding="utf-8")
                    run_command([str(GUITAR_PYTHON), str(ROOT / "tools/audio_verification_worker.py"), str(source),
                        str(temporary_notes), str(temporary_midi), "--notes-cache", str(base), "--references", str(reference_path), "--preview", str(preview_path),
                        *[argument for reference in references for argument in ("--reference-audio",reference["audio"])]], timeout=1800)
                finally:
                    reference_path.unlink(missing_ok=True)
            else:
                run_command([str(GUITAR_PYTHON), str(ROOT / "tools/guitar_worker.py"), str(source),
                             str(temporary_notes), str(temporary_midi), "--engine", engine,
                             *(["--gaps-cache", str(guitar_paths(directory, "gaps")[0])] if engine == "hybrid" and guitar_paths(directory, "gaps")[0].is_file() else [])], timeout=1800)
            payload = json.loads(temporary_notes.read_text(encoding="utf-8"))
            if payload.get("profile") != GUITAR_ENGINES[engine]["profile"] or not isinstance(payload.get("notes"), list):
                raise ValueError("Invalid guitar experiment output")
            if engine == "verified":
                preview_path.replace(output_dir / "guitar-verified.preview.wav")
            temporary_midi.replace(midi_path)
            temporary_notes.replace(notes_path)
            return ["guitar"], {}
        run_command([
            str(BASIC_PYTHON), str(ROOT / "tools" / "basic_pitch_worker.py"), str(source),
            str(output_dir / "guitar.json"), str(output_dir / "guitar.mid"),
            "--guitar",
        ], timeout=1800)
        return ["guitar"], {}
    except Exception as exc:
        log_job_error(job_id, "guitar-tab", exc)
        return [], {"guitar": "轉錄失敗"}


def transcribe_lyrics(job_id: str, audio: Path, directory: Path) -> dict:
    if not WHISPER_PYTHON.exists():
        raise RuntimeError("歌詞辨識引擎尚未安裝完成")
    output = directory / "lyrics.json"
    model = os.getenv("CHORDLAB_WHISPER_MODEL", "small").strip() or "small"
    cache = ROOT / "vendor" / "whisper"
    cache.mkdir(parents=True, exist_ok=True)
    update_job(job_id, progress=55, message="辨識歌詞與對齊時間（第一次會下載語音模型）")
    run_command([
        str(WHISPER_PYTHON), str(ROOT / "tools" / "lyrics_worker.py"), str(audio), str(output),
        "--model", model, "--cache", str(cache),
    ], timeout=7200)
    lyrics = clean_lyrics_payload(json.loads(output.read_text(encoding="utf-8"))) or {"segments": []}
    output.write_text(json.dumps(lyrics, ensure_ascii=False), encoding="utf-8")
    return lyrics


def process_job(
    job_id: str,
    source_kind: str,
    source_detail: str,
    separate_stems: bool = False,
    separation_model: str = "htdemucs",
    stem_midi: bool = False,
    lyrics_requested: bool = False,
    pure_guitar: bool = False,
    review_guitar: bool = False,
) -> None:
    directory = JOBS / job_id
    try:
        update_job(job_id, status="working", progress=5, message="準備音訊")
        if source_kind == "url":
            prepared = download_preparation.take(job_id)
            source, _title = prepared.result() if prepared is not None else download_url(job_id, source_detail, directory)
        else:
            source = next(directory.glob("source.*"))
        audio = directory / "audio.wav"
        update_job(job_id, progress=25, message="轉換成分析格式")
        duration = normalize_audio(source, audio)
        if separate_stems:
            with heavy_analysis_slot:
                analysis_audio, stem_names = separate_audio(job_id, source, directory, separation_model)
            analysis_stem = "harmony" if separation_model == "htdemucs_6s" else "other"
        else:
            analysis_audio, stem_names, analysis_stem = audio, ["original"], "original"
        all_stems = list(stem_names)
        activity = detect_activity(directory, all_stems) if separate_stems else {}
        stem_names = [name for name in all_stems if activity.get(name, {}).get("active", True)]
        lyrics = None
        lyrics_error = None
        if lyrics_requested:
            lyrics_audio = directory / "stems" / "vocals.wav" if separate_stems else audio
            try:
                with heavy_analysis_slot:
                    lyrics = transcribe_lyrics(job_id, lyrics_audio, directory)
            except Exception as exc:
                log_job_error(job_id, "lyrics", exc)
                lyrics_error = "歌詞辨識失敗"
        basic_progress = 68 if lyrics_requested else (62 if separate_stems else 36)
        chordino_progress = 82 if separate_stems else 72
        update_job(job_id, duration=duration, progress=basic_progress, message="Basic Pitch 辨識音符")
        basic_output = directory / "basic_pitch.json"
        midi_output = directory / "transcription.mid"
        run_command([str(BASIC_PYTHON), str(ROOT / "tools" / "basic_pitch_worker.py"), str(analysis_audio), str(basic_output), str(midi_output)], timeout=1800)
        basic = json.loads(basic_output.read_text(encoding="utf-8"))
        midi_stems: list[str] = []
        midi_errors: dict[str, str] = {}
        if pure_guitar and not review_guitar:
            # Decode/normalize once with FFmpeg. Basic Pitch cannot reliably
            # read yt-dlp WebM/Opus containers directly inside the sandbox.
            midi_stems, midi_errors = transcribe_guitar_tab(job_id, directory, direct_source=audio)
            chordino_progress = 94
        elif pure_guitar:
            pass  # Respect preview-first mode for an original guitar recording too.
        elif separate_stems and stem_midi:
            midi_names = [name for name in stem_names if not (review_guitar and name == "guitar")]
            midi_stems, midi_errors = transcribe_stem_midis(job_id, directory, midi_names, analysis_stem, midi_output)
            chordino_progress = 94
        elif separate_stems and separation_model == "htdemucs_6s" and "guitar" in stem_names and not review_guitar:
            midi_stems, midi_errors = transcribe_guitar_tab(job_id, directory)
            chordino_progress = 94
        update_job(job_id, note_count=basic.get("note_count", 0), progress=chordino_progress, message="Chordino 辨識和弦與分析 Key")
        chordino_output = directory / "chordino.json"
        chordino_env = {"VAMP_PATH": str(VAMP_PATH)}
        try:
            run_command([str(CHORDINO_PYTHON), str(ROOT / "tools" / "chordino_worker.py"), str(analysis_audio), str(chordino_output)], env=chordino_env, timeout=1200)
            chordino = json.loads(chordino_output.read_text(encoding="utf-8"))
            chordino_chords = chordino["chords"]
            chordino_error = None
        except Exception as exc:
            log_job_error(job_id, "chordino", exc)
            chordino_chords = []
            chordino_error = "Chordino 辨識失敗"
        chordino_usable = any(segment.get("chord") != "N" for segment in chordino_chords)
        btc = None
        btc_error = None
        comparison = None
        if BTC_ENABLED and BTC_PYTHON.exists() and BTC_MODEL.is_file():
            update_job(job_id, progress=96, message="雙引擎比對和弦")
            try:
                btc_output = directory / "btc.json"
                with heavy_analysis_slot:
                    run_command([str(BTC_PYTHON), str(ROOT / "tools/btc_worker.py"), str(analysis_audio), str(btc_output)], timeout=600)
                btc = json.loads(btc_output.read_text(encoding="utf-8"))
                if btc.get("chords") and chordino_chords:
                    comparison = compare_chords(chordino_chords, btc["chords"], duration)
            except Exception as exc:
                log_job_error(job_id, "btc", exc)
                btc = None
                comparison = None
                btc_error = "雙引擎比對暫時無法完成，已保留原本結果"
        rhythm = None
        try:
            rhythm_output = directory / "rhythm.json"
            rhythm_audio = directory / "stems" / "drums.wav" if "drums" in stem_names else audio
            run_command([str(BASIC_PYTHON), str(ROOT / "tools" / "rhythm_worker.py"), str(rhythm_audio), str(rhythm_output)], timeout=300)
            rhythm = json.loads(rhythm_output.read_text(encoding="utf-8"))
        except Exception as exc:
            log_job_error(job_id, "rhythm", exc)
        preferred_chords = chordino_chords if chordino_usable else basic.get("chords", [])
        result = {
            "active_method": "ensemble" if comparison and chordino_usable else ("chordino" if chordino_usable else "basic_pitch"),
            "methods": {"basic_pitch": basic.get("chords", []), "chordino": chordino_chords,
                        **({"btc": btc["chords"]} if btc else {}),
                        **({"ensemble": comparison["chords"]} if comparison else {})},
            "chord_comparison": {**comparison["summary"], "input_stem": analysis_stem,
                                 "btc_elapsed_seconds": btc.get("elapsed_seconds"), "engine": btc.get("engine")} if comparison else None,
            "btc_error": btc_error,
            "notes": basic.get("notes", []),
            "chordino_error": chordino_error,
            "lyrics": lyrics,
            "lyrics_error": lyrics_error,
            "key": detect_key(preferred_chords),
            "rhythm": rhythm,
            "guitar_tab": {
                "profile": "guitar_v2" if "guitar" in midi_stems else None,
                "source": "original" if pure_guitar else "separated",
                "status": "done" if "guitar" in midi_stems else ("failed" if "guitar" in midi_errors else ("pending" if review_guitar and (pure_guitar or "guitar" in stem_names) else "unavailable")),
            },
            "separation": {
                "enabled": bool(separate_stems),
                "model": separation_model if separate_stems else None,
                "analysis_stem": analysis_stem,
                "stems": stem_names,
                "all_stems": all_stems,
                "activity": activity,
                "midi_stems": midi_stems,
                "midi_errors": midi_errors,
            },
        }
        update_job(job_id, status="done", progress=100, message="分析完成", result=json.dumps(result, ensure_ascii=False), error_detail=None)
    except Exception as exc:
        log_job_error(job_id, "pipeline", exc)
        update_job(
            job_id,
            status="failed",
            message="分析失敗，請稍後再試或更換音訊來源。管理員可在管理頁查看詳細原因。",
            error_detail=str(exc)[-3000:],
            progress=100,
        )


class ChordSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    chord: str = Field(min_length=1, max_length=24)
    confidence: float | None = None


class ChordUpdate(BaseModel):
    method: str
    chords: list[ChordSegment]


@app.put("/api/jobs/{job_id}/chords")
def save_chords(request: Request, job_id: str, update: ChordUpdate) -> dict:
    if update.method not in {"basic_pitch", "chordino", "ensemble", "chord_v2"}:
        raise HTTPException(400, "未知的分析方式")
    row = editable_job(request, job_id)
    if not row["result"]:
        raise HTTPException(404, "找不到可編輯結果")
    duration = float(row["duration"] or 0)
    chords = [segment.model_dump() for segment in sorted(update.chords, key=lambda item: item.start)]
    for index, segment in enumerate(chords):
        if segment["end"] <= segment["start"] or segment["end"] > duration + 0.25:
            raise HTTPException(400, "和弦時間範圍錯誤")
        if index and segment["start"] < chords[index - 1]["start"]:
            raise HTTPException(400, "和弦順序錯誤")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        latest = connection.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not latest:
            raise HTTPException(404, "找不到可編輯結果")
        result = json.loads(latest["result"])
        if update.method not in result.get("methods", {}):
            raise HTTPException(400, "這首歌沒有這種分析結果")
        previous = {(s["start"], s["end"], s["chord"]): s for s in result["methods"][update.method]}
        if update.method == "chord_v2":
            for segment in chords:
                old = previous.get((segment["start"], segment["end"], segment["chord"]))
                if old and old.get("refinement"):
                    segment["refinement"] = old["refinement"]
                else:
                    segment["manual"] = True
        if update.method == "ensemble":
            for segment in chords:
                old = previous.get((segment["start"], segment["end"], segment["chord"]))
                if old and old.get("comparison"):
                    segment["comparison"] = old["comparison"]
                else:
                    segment["manual"] = True
            result["chord_comparison"]["review_segments"] = sum(
                s.get("comparison", {}).get("status") in {"detail", "conflict", "mixed"} for s in chords)
        result["methods"][update.method] = chords
        result["active_method"] = update.method
        result["key"] = detect_key(chords)
        connection.execute("UPDATE jobs SET result=?,message='已儲存人工修正',updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), int(time.time()), job_id))
    return {"ok": True}


def job_file(job_id: str, filename: str) -> Path:
    path = JOBS / job_id / filename
    if not path.is_file():
        raise HTTPException(404, "檔案不存在")
    return path


@app.get("/api/jobs/{job_id}/audio")
def audio(request: Request, job_id: str) -> FileResponse:
    accessible_job(request, job_id)
    return FileResponse(job_file(job_id, "audio.wav"), media_type="audio/wav", filename=f"{job_id}.wav")


@app.get("/api/jobs/{job_id}/audio-mix")
async def audio_mix(
    request: Request,
    job_id: str,
    tracks: Annotated[str, Query(min_length=3, max_length=120)],
) -> FileResponse:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"]) if row["result"] else {}
    separation = result.get("separation") or {}
    available = list(separation.get("all_stems") or separation.get("stems") or ["original"])
    requested = [track.strip() for track in tracks.split(",") if track.strip()]
    selected = [track for track in available if track in requested]
    if len(selected) < 2 or len(selected) != len(set(requested)):
        raise HTTPException(400, "同步混音至少需要兩個有效音軌")

    mix_key = hashlib.sha256("\0".join(selected).encode()).hexdigest()[:16]
    cached = JOBS / job_id / "mixes" / f"{mix_key}.m4a"
    if cached.is_file():
        return FileResponse(cached, media_type="audio/mp4")
    try:
        return await light_tasks.run(build_audio_mix, job_id, selected)
    except PoolBusy as exc:
        raise HTTPException(429, str(exc)) from exc


def build_audio_mix(job_id: str, selected: list[str]) -> FileResponse:

    sources = [
        job_file(job_id, "audio.wav" if track == "original" else f"stems/{track}.wav")
        for track in selected
    ]
    mix_key = hashlib.sha256("\0".join(selected).encode()).hexdigest()[:16]
    mixes = JOBS / job_id / "mixes"
    output = mixes / f"{mix_key}.m4a"
    if not output.is_file():
        with mix_generation_lock:
            if not output.is_file():
                mixes.mkdir(mode=0o700, exist_ok=True)
                if sum(1 for path in mixes.glob("*.m4a") if path.is_file()) >= 64:
                    raise HTTPException(429, "這首歌的同步混音快取已達上限")
                temporary = mixes / f"{mix_key}.building.m4a"
                temporary.unlink(missing_ok=True)
                command = [str(FFMPEG), "-nostdin", "-y"]
                for source in sources:
                    command.extend(("-i", str(source)))
                command.extend((
                    "-filter_complex_threads", "1", "-filter_complex",
                    f"amix=inputs={len(sources)}:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.95",
                    "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k",
                    "-threads", "1", "-movflags", "+faststart", str(temporary),
                ))
                try:
                    run_command(command, timeout=600)
                    temporary.replace(output)
                finally:
                    temporary.unlink(missing_ok=True)
    return FileResponse(output, media_type="audio/mp4")


@app.get("/api/jobs/{job_id}/guitar-preview")
async def guitar_preview(request: Request, job_id: str, start: Annotated[float, Query(ge=0, le=1200, allow_inf_nan=False)] = 0,
                         track: Literal["guitar", "bass"] = "guitar") -> FileResponse:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"] or "{}")
    original = track == "guitar" and guitar_uses_original(row, result)
    separation = result.get("separation") or {}
    if not original and track not in (separation.get("all_stems") or separation.get("stems") or []):
        raise HTTPException(404, "沒有這個樂器音軌")
    source = job_file(job_id, "audio.wav" if original else f"stems/{track}.wav")
    start = int(min(start, max(0, float(row["duration"] or 20) - 1)) // 20 * 20)
    cached = JOBS / job_id / f"{track}-preview-{start}.m4a"
    if cached.is_file():
        return FileResponse(cached, media_type="audio/mp4")
    try:
        return await light_tasks.run(build_guitar_preview, job_id, source, start, track)
    except PoolBusy as exc:
        raise HTTPException(429, str(exc)) from exc


def build_guitar_preview(job_id: str, source: Path, start: int, track: str = "guitar") -> FileResponse:
    output = JOBS / job_id / f"{track}-preview-{start}.m4a"
    with mix_generation_lock:
        if not output.is_file():
            temporary = output.with_suffix(".building.m4a")
            try:
                run_command([str(FFMPEG), "-nostdin", "-y", "-ss", str(start), "-i", str(source), "-t", "20", "-vn", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "128k", "-threads", "1", "-movflags", "+faststart", str(temporary)], timeout=45)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
    return FileResponse(output, media_type="audio/mp4")


@app.get("/api/jobs/{job_id}/audio/{track}")
def audio_track(request: Request, job_id: str, track: str) -> FileResponse:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"]) if row["result"] else {}
    separation = result.get("separation") or {}
    allowed = set(separation.get("all_stems") or separation.get("stems") or ["original"])
    if track not in allowed:
        raise HTTPException(404, "未知的音軌")
    if track == "original":
        path = job_file(job_id, "audio.wav")
    else:
        path = job_file(job_id, f"stems/{track}.wav")
    return FileResponse(path, media_type="audio/wav", filename=f"{track}.wav")


@app.get("/api/jobs/{job_id}/audio-stream/{track}")
async def audio_stream(request: Request, job_id: str, track: str) -> FileResponse:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"] or "{}")
    separation = result.get("separation") or {}
    if track not in (separation.get("all_stems") or separation.get("stems") or ["original"]):
        raise HTTPException(404, "未知的音軌")
    source = job_file(job_id, "audio.wav" if track == "original" else f"stems/{track}.wav")
    cached = JOBS / job_id / "streams" / f"{track}.m4a"
    if cached.is_file():
        return FileResponse(cached, media_type="audio/mp4")
    try:
        return await light_tasks.run(build_audio_stream, job_id, source, track)
    except PoolBusy as exc:
        raise HTTPException(429, str(exc)) from exc


def build_audio_stream(job_id: str, source: Path, track: str) -> FileResponse:
    directory = JOBS / job_id / "streams"
    output = directory / f"{track}.m4a"
    with mix_generation_lock:
        if not output.is_file():
            directory.mkdir(mode=0o700, exist_ok=True)
            temporary = output.with_suffix(".building.m4a")
            try:
                run_command([str(FFMPEG), "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", "-threads", "1", "-movflags", "+faststart", str(temporary)], timeout=120)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
    return FileResponse(output, media_type="audio/mp4")


def result_for_export(request: Request, job_id: str) -> tuple[sqlite3.Row, dict, list[dict]]:
    row = accessible_job(request, job_id)
    if not row["result"]:
        raise HTTPException(404, "尚無分析結果")
    result = serialize_job(row)["result"]
    chords = result["methods"].get(result["active_method"], [])
    return row, result, chords


def validate_capo(capo: int) -> int:
    if capo < 0 or capo > 11:
        raise HTTPException(400, "Capo 必須介於 0 到 11 格")
    return capo


def transpose_chord_label(label: str, semitones: int) -> str:
    if not label or label == "N":
        return label
    match = re.match(r"^([A-G](?:#|b)?)([^/]*)?(?:/([A-G](?:#|b)?))?$", label)
    if not match or match.group(1) not in KEY_ROOTS:
        return label
    root = KEY_NAMES[(KEY_ROOTS[match.group(1)] + semitones) % 12]
    bass = match.group(3)
    bass_text = f"/{KEY_NAMES[(KEY_ROOTS[bass] + semitones) % 12]}" if bass in KEY_ROOTS else ""
    return f"{root}{match.group(2) or ''}{bass_text}"


@app.get("/api/jobs/{job_id}/export/midi")
def export_midi(request: Request, job_id: str) -> FileResponse:
    accessible_job(request, job_id)
    path = job_file(job_id, "transcription.mid")
    return FileResponse(path, media_type="audio/midi", filename="chordlab-transcription.mid")


@app.get("/api/jobs/{job_id}/export/midi/{track}")
def export_stem_midi(request: Request, job_id: str, track: str) -> FileResponse:
    row = accessible_job(request, job_id)
    result = json.loads(row["result"]) if row["result"] else {}
    allowed = set(result.get("separation", {}).get("midi_stems", []))
    if track not in allowed:
        raise HTTPException(404, "這個音軌沒有 MIDI")
    path = job_file(job_id, f"stem-midi/{track}.mid")
    return FileResponse(path, media_type="audio/midi", filename=f"{safe_title(row['title'])}-{track}.mid")


@app.get("/api/jobs/{job_id}/export/chordpro")
def export_chordpro(request: Request, job_id: str, capo: int = 0) -> PlainTextResponse:
    capo = validate_capo(capo)
    row, result, chords = result_for_export(request, job_id)
    key_info = result.get("key") or detect_key(chords) or {}
    lines = [f"{{title: {row['title']}}}", f"{{capo: {capo}}}", f"{{comment: ChordLab · {result['active_method']} · Original key {key_info.get('label', 'unknown')}}}", ""]
    for chord in chords:
        minutes, seconds = divmod(float(chord["start"]), 60)
        lines.append(f"{{comment: {int(minutes):02d}:{seconds:05.2f}}} [{transpose_chord_label(chord['chord'], -capo)}]")
    headers = {"Content-Disposition": 'attachment; filename="chordlab.cho"'}
    return PlainTextResponse("\n".join(lines), headers=headers, media_type="text/plain; charset=utf-8")


@app.get("/api/jobs/{job_id}/export/json")
def export_json(request: Request, job_id: str, capo: int = 0) -> Response:
    capo = validate_capo(capo)
    row, result, _chords = result_for_export(request, job_id)
    payload = {"title": row["title"], "duration": row["duration"], "capo": capo, **result}
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="chordlab-project.json"'})


@app.get("/api/jobs/{job_id}/export/pdf")
def export_pdf(request: Request, job_id: str, capo: int = 0) -> FileResponse:
    capo = validate_capo(capo)
    row, result, chords = result_for_export(request, job_id)
    output = JOBS / job_id / f"chord-sheet-capo-{capo}.pdf"
    styles = getSampleStyleSheet()
    embedded_font = ROOT / "vendor" / "fonts" / "NotoSansTC-VF.ttf"
    if embedded_font.is_file():
        if "NotoSansTC" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("NotoSansTC", str(embedded_font)))
        font_name = bold_font_name = "NotoSansTC"
    else:
        font_name, bold_font_name = "Helvetica", "Helvetica-Bold"
    styles["Title"].fontName = bold_font_name
    styles["BodyText"].fontName = font_name
    styles["Heading2"].fontName = bold_font_name
    document = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=row["title"])
    play_key = result.get("key") or detect_key(chords)
    original_key = play_key.get("label", "Unknown") if play_key else "Unknown"
    play_key_label = f"{KEY_NAMES[(int(play_key['pitch_class']) - capo) % 12]} {play_key['mode']}" if play_key else "Unknown"
    story = [Paragraph(row["title"], styles["Title"]), Paragraph(f"ChordLab · {result['active_method']} · Original key: {original_key} · Capo {capo} · Play key: {play_key_label}", styles["BodyText"]), Spacer(1, 7 * mm)]
    table_data = [["Time", "Chord", "Duration"]]
    for chord in chords:
        start = float(chord["start"])
        table_data.append([f"{int(start // 60):02d}:{start % 60:05.2f}", transpose_chord_label(chord["chord"], -capo), f"{float(chord['end']) - start:.2f}s"])
    table = Table(table_data, colWidths=[35 * mm, 65 * mm, 35 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16191d")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), bold_font_name), ("FONTNAME", (0, 1), (-1, -1), font_name), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f2f0e9"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b5b1a7")), ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(table)
    lyric_segments = (result.get("lyrics") or {}).get("segments", [])
    if lyric_segments:
        lyric_style = ParagraphStyle("Lyrics", parent=styles["BodyText"], fontName=font_name, fontSize=10, leading=15)
        story.extend([PageBreak(), Paragraph("Timed lyrics / 對時歌詞", styles["Heading2"]), Spacer(1, 4 * mm)])
        lyric_rows = [["Time", "Play chord", "Lyrics"]]
        for segment in lyric_segments:
            start = float(segment.get("start", 0))
            end = float(segment.get("end", start))
            overlapping = []
            for chord in chords:
                if float(chord["end"]) > start and float(chord["start"]) < end:
                    played = transpose_chord_label(chord["chord"], -capo)
                    if played != "N" and played not in overlapping:
                        overlapping.append(played)
            timestamp = f"{int(start // 60):02d}:{start % 60:05.2f}"
            lyric_rows.append([timestamp, " · ".join(overlapping) or "—", Paragraph(html.escape(str(segment.get("text", ""))), lyric_style)])
        lyric_table = Table(lyric_rows, colWidths=[25 * mm, 38 * mm, 105 * mm], repeatRows=1)
        lyric_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16191d")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold_font_name), ("FONTNAME", (0, 1), (1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f2f0e9"), colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b5b1a7")), ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(lyric_table)
    document.build(story)
    return FileResponse(output, media_type="application/pdf", filename="chordlab-chords.pdf")
