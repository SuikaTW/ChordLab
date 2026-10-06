# ChordLab

[English](README.md) | [繁體中文](README.zh-TW.md)

Private music-analysis workspace for a single server. It accepts an upload or a supported public media URL, normalizes the audio, and runs two independent analysis paths:

- Spotify Basic Pitch for note events and MIDI, followed by a local chord-template/HMM pass.
- Chordino (NNLS Chroma Vamp plugin) for full-mix chord recognition.
- Optional Demucs `htdemucs` four-stem separation. When selected, Basic Pitch and Chordino analyze the `other` stem while the browser can play the original, vocals, bass, drums, or other-instruments stem.

The browser provides synchronized multi-stem playback/mixing, method comparison, automatic key estimation, a Capo/play-key view, a chord editor, generated guitar voicings/string notes, and PDF, MIDI, ChordPro, and JSON exports.

Continuous TAB never falls back to the full mix. The one-click guitar TAB option enables the experimental six-stem Demucs model and runs note transcription only on its isolated guitar stem. Six-stem jobs always produce guitar MIDI for TAB; the all-stem MIDI option remains separate.

Users may explicitly publish a completed analysis to the shared library. Public analyses are searchable and ranked by unique signed-in viewers or favorites; exact matching public URL jobs with the same analysis options are reused instead of being processed again. Private jobs remain visible only to their owner and administrators.

Optional timed-lyrics transcription uses a separate CPU-only faster-whisper runtime. When stems are enabled it transcribes the isolated vocal track; otherwise it uses the normalized full mix. Timed lyrics are shown in the player and merged with overlapping play chords in the PDF export. Singing transcription is approximate and may need manual correction.

## Service

The user service listens only on `127.0.0.1:8788`. Put HTTPS authentication/proxying in front of it; the application also requires its own login from `.env`.

```bash
systemctl --user status chordlab
journalctl --user -u chordlab -f
curl http://127.0.0.1:8788/healthz
```

`chordlab-tunnel.service` runs the persistent Cloudflare Named Tunnel for the public address:

```bash
https://chord.suika.page
```

Cloudflare terminates TLS at the public edge. The application redirects Cloudflare HTTP requests to HTTPS and sends a one-year HSTS policy on HTTPS responses; local loopback HTTP remains available for health checks.

Change the password and signing secret in `.env`, then restart:

```bash
chmod 600 .env
systemctl --user restart chordlab
```

`/healthz` is the unauthenticated minimal liveness endpoint. `/api/health` includes engine details and requires a signed-in account.

## Administration and public access

Administrators can open `https://chord.suika.page/admin` to inspect server/queue/storage status, manage user roles or blocks, moderate public analyses, review internal job failures, permanently delete completed/failed jobs, and inspect an audit trail. The local password account and emails in `GOOGLE_ADMIN_EMAILS` are configuration-managed administrators; an existing administrator may grant the database-backed administrator role to another signed-in Google account.

For public access, non-administrators default to five newly processed jobs per rolling 24 hours (`CHORDLAB_DAILY_JOB_LIMIT`) and remain subject to the active-job limit. Reusing an existing matching public analysis does not consume a new analysis. Sessions default to seven days (`CHORDLAB_SESSION_DAYS`). `CHORDLAB_APP_HOSTS` restricts accepted HTTP Host values.

Security headers, strict same-origin checks for state-changing browser requests, private cookies, server-side account blocking, owner-only editing, URL port/credential validation, generic user-facing processing errors, and administrator-only diagnostic details are enforced by the application. Keep Cloudflare rate limiting/WAF enabled as an additional edge layer; application controls do not replace OS patching or isolation of untrusted media decoders.

## Google login

Create a Google Cloud OAuth 2.0 client of type **Web application** and register this exact authorized redirect URI:

```text
https://chord.suika.page/auth/google/callback
```

Then either set `GOOGLE_OAUTH_FILE` to the absolute path of Google's downloaded client-secret JSON, or set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` directly. `GOOGLE_ALLOWED_EMAILS` is an optional comma-separated login allowlist: when blank, any verified Google account can sign in. `GOOGLE_ADMIN_EMAILS` lists accounts that can see every user's analyses; other Google users only see their own jobs. Restart `chordlab.service` after editing. The local password login remains available as an administrator fallback.

## Demucs environment

Demucs is isolated from the web and transcription runtimes in `.venv-demucs`. The standard model creates four stems; the optional experimental `htdemucs_6s` model also separates guitar and piano. Detailed jobs remix guitar, piano, and the remaining accompaniment into a `harmony` stem for chord/key analysis. This server uses CPU-only PyTorch and serializes jobs to limit resource usage. Rebuild it with:

```bash
uv venv .venv-demucs --python 3.12
uv pip install --python .venv-demucs/bin/python -r requirements-demucs.txt
```

`bin/ffmpeg` and `bin/ffprobe` are used for decoding and encoding without requiring a system package install. The first separation downloads the `htdemucs` model weights to the user cache.

The lyrics runtime is isolated in `.venv-whisper` and defaults to the multilingual `small` model configured by `CHORDLAB_WHISPER_MODEL`:

```bash
uv venv .venv-whisper --python 3.12
uv pip install --python .venv-whisper/bin/python -r requirements-whisper.txt
```

Analysis jobs use a persistent FIFO queue. `CHORDLAB_ANALYSIS_WORKERS=1` processes one song at a time and shows later submissions their queue position. `CHORDLAB_MAX_ACTIVE_PER_USER=2` prevents one account from filling the queue. Queued jobs are restored automatically after a service restart.

Large per-song artifacts are stored outside the application checkout. `CHORDLAB_JOBS_DIR` selects the job directory and `CHORDLAB_STORAGE_MOUNT` makes startup fail safely instead of writing to the SSD when the data disk is not mounted. The SQLite catalog remains under `data/` on the SSD.

## Limits and safety

- URL imports are restricted to the configured public media domains and are checked against private/reserved IP addresses.
- Uploads are checked beyond their extension: executable/web signatures are rejected, then `ffprobe` verifies the real container and audio stream inside a Bubblewrap sandbox. Files live outside public static paths under server-generated names and are never executed.
- Playlists are disabled, processing is serialized, and uploads default to 200 MB / 20 minutes.
- Spotify music links are not downloaded. Upload only audio you are allowed to process.
- Analysis is probabilistic. Isolated instruments generally produce cleaner Basic Pitch MIDI; Chordino is usually the better first view for a full mix.
- Source separation can remove masking, but separation artifacts can occasionally make recognition worse. It is opt-in so the same source can be compared with and without it.
- When two or more tracks are selected on iPhone or iPad, the server renders them into one AAC stream to avoid iOS WebKit multi-player start latency and playback-rate glitches. The first play creates a reusable cache, capped at 24 combinations per job.
- Per-stem MIDI uses Basic Pitch for pitched stems (vocals, bass, accompaniment, guitar, and piano). Drums remain an audio stem because pitched-note transcription is not a drum-event model.
- The six-source model is experimental. Demucs upstream specifically warns that the piano stem can contain substantial bleed and artifacts.
- Key estimation is inferred from the duration-weighted chord track and should be treated as a starting point when a song modulates or the chord recognition is sparse.
- Continuous TAB maps detected pitches onto standard-tuned guitar strings with a continuity heuristic. It is a playable estimate, not a claim about the original performer's exact string/fret choices or techniques.

## Attribution

- Basic Pitch: Spotify AB, Apache-2.0.
- NNLS Chroma / Chordino: Matthias Mauch and Chris Cannam; downloaded from the official Vamp plugin distribution with a pinned checksum.
- Demucs: Meta Research, MIT license.
- faster-whisper: SYSTRAN, MIT license; Whisper model weights originate from OpenAI's Whisper project.
- Noto Sans TC: Google, SIL Open Font License 1.1. The bundled license is stored at `vendor/fonts/OFL.txt`.
- The checksum-pinned no-root Chordino installation approach follows the MIT-licensed ChordFlask project by bkl2000.
