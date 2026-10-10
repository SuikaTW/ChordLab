# ChordLab

For the full history of recognition, TAB, playback, and UI experiments—including negative results, evidence locations, and current rollout decisions—see the [Traditional Chinese experiment ledger](docs/experiment-ledger.zh-TW.md). The [Chinese README](README.zh-TW.md) includes a compact results summary.

The Studio interface offers a persistent bottom player while reading TAB. The header style selector switches back to the original look without interrupting playback; it remembers the browser preference. The original source archive, Git tag and restore details are documented in [UI backup notes](docs/ui-redesign-20261008.md).

Recent safeguards add revocable login sessions, optimistic revisions and restore history for chord edits, a streaming upload body limit, a bounded global analysis queue, and single-flight audio mixes. Daily HDD snapshots cover the database, songs, source, and private configuration; see [operations and recovery](docs/operations-20261008.md). GitHub Actions runs the isolated Python and Deno tests.

The practice workspace includes private, account-scoped TAB editing, guitar-stem
preview before optional transcription, estimated beat/bar layout with manual
correction, windowed TAB rendering, and separate bounded download/media pools.
Audio pitch and rhythm estimates do not identify the original played strings,
separate acoustic/electric guitars, or reliably identify downbeats/time signatures.
See [中文說明](README.zh-TW.md) for workflow, persistence, limits, and evaluation.

[English](README.md) | [繁體中文](README.zh-TW.md)

Private music-analysis workspace for a single server. It accepts an upload or a supported public media URL, normalizes the audio, and runs two independent analysis paths:

- Spotify Basic Pitch for note events and MIDI, followed by a local chord-template/HMM pass.
- Chordino (NNLS Chroma Vamp plugin) for full-mix chord recognition.
- Optional Demucs `htdemucs` four-stem separation. When selected, Basic Pitch and Chordino analyze the `other` stem while the browser can play the original, vocals, bass, drums, or other-instruments stem.

The browser provides synchronized multi-stem playback/mixing, method comparison, automatic key estimation, a Capo/play-key view, a chord editor, generated guitar voicings/string notes, and PDF, MIDI, ChordPro, and JSON exports.

Click a timeline chord for a conventional vertical chord diagram and selectable positions. Strings run low E to high e, with mute/open markers, barre lines and numbered frets relative to Capo. Standard tuning only; familiar shapes are preferred and generated alternatives are labeled. These are reference voicings, not verified original fingerings, and never modify continuous TAB or recognition results.

The chord timeline follows playback by default, with active-segment highlighting and a moving playhead. Only the timeline scrolls horizontally; the editor selection and page position are preserved. Manual browsing suspends following for five seconds. The follow toggle remembers its setting, paused playback never scrolls automatically, and reduced-motion mode only scrolls when the playhead leaves the visible range.

Practice tools add pitch-preserving 0.5×/0.75× playback and A–B loops on the existing single master player. Song changes clear the loop. Pitch-preservation quality/background timing depends on the browser. The connected-voicing option uses dynamic programming over the selected chord plus up to four neighbors on each side to reduce position/string movement without changing the chords.

Optional **Audio verification** creates a separate guitar variant from existing hybrid/GAPS/Basic Pitch/TabCNN notes (that priority order). A nonnegative harmonic-resynthesis fit must improve at two distinct audio windows with fundamental evidence before a semitone/octave correction is accepted. At most two passes plus a final recheck; uncertain/dense/short/manual events are retained, and event counts/timing never change. Original analyses and personal revisions remain untouched. Independent MIDI and synthetic WAV previews live on the existing HDD; previews start at the current player position, with no claim of matching real timbre.

References can be revoked at any time without deleting or editing the personal score; withdrawal excludes them from future calibration, not already generated variants.

**Cross verification** is a separate guitar variant using existing Basic Pitch/GAPS/TabCNN events and acoustic chord methods. GAPS and hybrid count as one family; MIDI, derived TAB and Basic-Pitch-derived chords are never extra votes. Missing models are not automatically run. Disagreement is reviewed first; two independent families may nominate nearby pitches beyond semitones/octaves, but the two-window audio gate and final recheck are always mandatory. Harmony is only a small tie-breaker. Manual events, timing and counts are preserved; TabCNN hints must match standard-tuning pitch before use, without claiming true original string identification.

An independent cross-checked chord method is also published without overwriting the stored active method or key. Durable independent acoustic changes can split long baseline segments before the 80% local-coverage check; short extension flicker is merged. Review uses the actual `stems/harmony.wav` and full harmonic-track notes when available, not guitar-only notes in piano passages. Changes need two-window spectral gains or a stable bass/low harmonic root with visible added tones, harmonic-note agreement and bounded fit loss. Root evidence alone never chooses a chord or its quality; arpeggiated added tones can appear across either window. Harmonic notes and bass are context, not additional model votes. Manual segments are preserved; a baseline hash prevents publishing stale chords when a concurrent edit occurs. New recommendations open by default unless the stored active method contains manual edits; original versions remain selectable. PDF/ChordPro/JSON exports use the currently selected method. A completed stale recommendation can be explicitly refreshed without exhausting a past successful cycle's retry allowance; failed retries and daily/concurrent quotas still apply. MIDI and synthetic previews remain separate, as do personal documents. See `tools/benchmark_cross_verification.py`, `tests/cross_verification_checks.py`, and the read-only live browser check `tests/cross_verification_browser_smoke.py`. Synthetic benchmarks do not establish real-song accuracy.

Explicitly confirmed manual TAB edits can be stored as a private reference snapshot and exported via `/api/jobs/{id}/tab-reference?instrument=guitar|bass`. Unconfirmed saves revoke that snapshot. Future owner guitar verification can inspect up to eight private references, using only isolated edited notes; three observations of a pitch are required before a 30% harmonic-template calibration is used. Other reference jobs are mounted read-only in the sandbox. No automatic pseudo-label learning, shared model poisoning, or neural-network retraining. Bass references are supported but audio verification is currently guitar-only.

`tools/benchmark_verification.py` is a reproducible synthetic single/polyphonic reference corpus using the existing pitch/onset F1 scorer; `tests/audio_verification_checks.py` adds held-out timbres and conservative guard tests. Neither synthetic metrics nor spectral residual gains establish real-song accuracy; independent real annotations are still needed. Reference exports are user-confirmed snapshots, not independently verified full scores.

Continuous TAB never falls back to the full mix. The guitar workflow uses the experimental six-stem model and defaults to reviewing a guitar preview before optional transcription; all-stem MIDI is separate. An already isolated guitar recording can bypass separation. TAB uses estimated bars with adaptive row grouping based on available width and note density, plus editable tempo/meter/first-beat timing. Clean suppresses extremely weak/short events; Full retains more detections. These layouts are estimates, not verified original scores.

Users may explicitly publish a completed analysis to the shared library. Public analyses are searchable and ranked by unique signed-in viewers or favorites; exact matching public URL jobs with the same analysis options are reused instead of being processed again. Private jobs remain visible only to their owner and administrators.

Optional timed-lyrics transcription uses a separate CPU-only faster-whisper runtime. When stems are enabled it transcribes the isolated vocal track; otherwise it uses the normalized full mix. Timed lyrics are shown in the player and merged with overlapping play chords in the PDF export. Short opening songwriter/composer captions hallucinated as lyrics are filtered; singing transcription remains approximate and may need manual correction.

## Reproducible reference corpus and event review

The primary **Recommended TAB** button (`event_verified`) prepares missing
installed Basic Pitch, GAPS, TabCNN and hybrid outputs in one queued task, then
consolidates independent evidence. Viewing an existing recommendation does not
start another analysis. Raw variants remain in a closed advanced comparison;
saved personal scores take priority. Input fingerprints flag stale recommendations
for explicit refresh. Every original analysis and personal edit is preserved.
It combines cross-model pitch verification with
bounded onset/offset repairs, independently supported retrigger splits and missing-note additions. Additions need two independent
model families, an audio transient, fundamentals in two windows and a spectral
fit gain, followed by a final recheck. A full mix is confirmation/veto, not another
guitar-model vote. Suspected false notes, retriggers and repeated phrases remain
clickable review hints: no automatic deletion, phrase copying or training. Offsets
need two agreeing model endpoints and an audible pitch-envelope drop; retrigger
splits need a transient and pitch-energy rise and never affect manual events.
Four-window complexity-penalized addition evidence is advisory: the tested strict
gate lost true notes, so it is not the default selection rule. Phrase fingering
search preserves sustains and valid manual choices, considers held hand spans and
melodic continuity, and deduplicates future states without guessing techniques.

`tools/reference_corpus.py` explicitly downloads the checksum-pinned **GuitarSet
v1.1.0** microphone audio and JAMS archives, selects six clips by performer/style,
excludes three upstream known annotation-error files, and preserves source,
license, attribution and immutable audio/reference hashes. GuitarSet is by
Qingyang Xi, Rachel M. Bittner, Johan Pauwels, Xuzhou Ye and Juan P. Bello (ISMIR
2018), licensed CC BY 4.0; source: https://zenodo.org/records/3371780.

`tools/benchmark_corpus.py` runs the application's pinned workers in its existing
network-isolated sandbox, without passing references into inference or changing
production jobs, weights or answers. It measures pitch/onset, offsets, actual
client TAB allocation and separately sourced chord annotations. Performer-grouped
development/regression splits and pipeline-hashed reports support reproducible
comparisons. **Existing models may have trained on GuitarSet: this is regression
coverage, not an independent blind test.** The initial six-clip pilot covers one
Bossa Nova piece, not broad genre accuracy. Internet scores need recording/version,
tuning/capo, licensing and alignment review before becoming trusted references.
Predictions never become reference labels. `--reuse-raw-report` explicitly reuses
checksum-verified raw predictions for controlled postprocessing comparisons;
reports retain provenance and reject mid-run inference-code changes. See the
Chinese README for commands.

## Bass TAB

Select **Bass** in the instrument TAB panel for a continuous four-string score,
or choose Drop D / five-string low B in the tuning options. Actual bass octave,
independent settings and personal revisions, no guitar capo or guitar model
anchors. Existing Bass MIDI/JSON is reused without rewriting. Owners/admins can
queue missing transcription from an existing Bass stem; no new separation is
needed. Jobs without a Bass stem need a new stem-enabled analysis.

New Basic Pitch `bass_v1` transcription constrains B0–G4, retains events down to
60 ms and uses GM fingered-bass MIDI. This is not a proven accuracy improvement;
harmonics, bleed, slides/slap and inferred fingerings remain approximate. The
durable refinement queue/quotas/recovery are shared with guitar and chord v2.
Private Bass documents use `user_bass_tabs`; existing `user_tabs` and the default
guitar API remain compatible. Read/write `/tab?instrument=bass` for Bass. MIDI
download is supported; existing PDF export remains chords/lyrics, not Bass TAB.
Desktop/mobile switching and isolated-catalog save/reload checks are provided in
`tests/bass_tab_browser_smoke.py` (default read-only, explicit generation flag).

## Experimental guitar transcription

The guitar TAB engine selector keeps Basic Pitch, GAPS pitch transcription and
TabCNN/GuitarProFX string estimation and hybrid TAB v2 as independent versions. Owners/admins can
queue missing versions and download their MIDI; public viewers can read completed
versions. No existing baseline, chord edits or personal TAB is overwritten by
experiment generation. Tasks survive restarts and share the heavy-analysis queue.

GAPS still needs pitch-to-fingering search. TabCNN soft string anchors apply only
to standard tuning, capo 0 and frets 0–19; playable re-fingering is optional.
Repeated same-fret plucks may merge in its frame-to-note decoder. Model scores
are not accuracy probabilities. On two EGSet12 clips, pitch/onset F1 was
0.837/0.831 for the baseline and 0.984/0.969 for GAPS, but offset timing was not
uniformly better and TabCNN did not beat baseline pitch transcription. This is
the authors' benchmark, not an independent blind test. Basic Pitch remains the
default; new engines remain explicitly experimental.

See [model provenance, licenses and rebuild instructions](vendor/guitar/README.md).
Hybrid v2 preserves GAPS pitches/timing and uses pitch-valid TabCNN alternatives
as soft anchors in whole-phrase fingering search. Low-evidence hints are omitted;
release proposals remain diagnostic, not automatic trimming. EGSet01/07 annotated
fingering agreement rose from 54.3%/37.5% (GAPS + original search) to 73.9%/62.5%
(hybrid, 80 ms onset tolerance, maximum one-to-one matching). This is a small
author-dataset check, not a general accuracy claim; pitch/onset F1 is unchanged.

Optional **chord v2** uses a custom acoustic/bass/context decoder with new
boundaries, while preserving the baseline, saved edits and active key/method.
Queue it from the chord panel and select it after completion. Bass is not assumed
to be the root; inversions require sustained separate-bass evidence. No invented
9/11/13 labels or forced key/progression prior. Ambiguous candidates are not
probabilities. It shares durable refinement quotas/queue/restart recovery, and
failure is nonfatal. Controlled audio tests pass; real-song chord accuracy has
not yet been measured against human ground truth. See the Chinese README for
details and validation commands.
Models/runtimes stay on SSD; media, experimental predictions and benchmarks stay
on HDD. `tools/benchmark_guitar.py` scores annotated notes without editing jobs.

## Dual-engine chord cross-check

Run `bash scripts/install-btc.sh`, then restart the service. New jobs use the official
BTC-ISMIR19 170-class checkpoint to cross-check Chordino on the same analysis audio.
The default comparison keeps the baseline labels and boundaries; dots indicate
disagreement, not correctness. Candidate percentages represent overlap duration,
not confidence. Owners/admins may explicitly replace a whole segment with a candidate;
the original Chordino timeline is retained. BTC failures do not fail the job.

Existing jobs are not automatically reprocessed or switched. With an idle queue:

```bash
.venv/bin/python tools/backfill_chord_comparison.py --job SONG_JOB_ID
```

Disable future cross-checks with `CHORDLAB_BTC_ENABLED=false` and a service restart.
The isolated CPU runtime uses a pinned, SHA-256-verified official checkpoint,
restricted weights-only loading and a network-disabled sandbox. BTC's vocabulary
does not include full 9/11/13 or inversions; it is not a guitar-note/TAB transcriber.
Accuracy must be evaluated against human annotations, not engine agreement.

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
uv pip install --python .venv-demucs/bin/python -r requirements/demucs.txt
```

`bin/ffmpeg` and `bin/ffprobe` are used for decoding and encoding without requiring a system package install. YouTube imports also require yt-dlp's JavaScript runtime: `uv sync` installs `yt-dlp-ejs`, then `scripts/install-deno.sh` installs the pinned Deno build after verifying its SHA-256 digest. The first separation downloads the `htdemucs` model weights to the user cache.

The lyrics runtime is isolated in `.venv-whisper` and defaults to the multilingual `small` model configured by `CHORDLAB_WHISPER_MODEL`:

```bash
uv venv .venv-whisper --python 3.12
uv pip install --python .venv-whisper/bin/python -r requirements/whisper.txt
```

Analysis jobs use a persistent FIFO queue. `CHORDLAB_ANALYSIS_WORKERS=1` processes one song at a time and shows later submissions their queue position. `CHORDLAB_MAX_ACTIVE_PER_USER=2` prevents one account from filling the queue. Queued jobs are restored automatically after a service restart.

Large per-song artifacts are stored outside the application checkout. `CHORDLAB_JOBS_DIR` selects the job directory and `CHORDLAB_STORAGE_MOUNT` makes startup fail safely instead of writing to the SSD when the data disk is not mounted. The SQLite catalog remains under `data/` on the SSD.

## Guitar TAB

Use the guitar TAB option for six-stem separation of full mixes. For isolated guitar recordings, select the pure-guitar input option to transcribe the original audio without separation. The guitar transcription profile preserves shorter notes with a stricter onset threshold; phrase-level candidate search considers chord spans and position changes, and repeated plucks remain separate events. Standard tuning, Drop D, DADGAD, half-step down, and whole-step down are supported alongside capo settings. Tuning affects continuous TAB only; chord shape diagrams still use standard tuning.

Existing notes use the new fingering search immediately, but need reanalysis for the new short-note profile. Old public guitar transcriptions are excluded from automatic reuse. Estimated fingerings are not guaranteed to reproduce the original performance, and distorted guitars, harmonics, overlapping guitar parts, and separation artifacts remain difficult.

Run `bin/deno test tests/tab-engine.test.js` and `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` for regressions. With the service environment loaded, `tools/evaluate_guitar_tab.py --audio /absolute/path/to/guitar.wav` compares profiles without changing saved songs. The synthetic fixture has reference onsets/pitches; real clips without reference annotations only show output changes, not accuracy.

## Limits and safety

- URL imports are restricted to the configured public media domains and are checked against private/reserved IP addresses.
- Uploads are checked beyond their extension: executable/web signatures are rejected, then `ffprobe` verifies the real container and audio stream inside a Bubblewrap sandbox. Files live outside public static paths under server-generated names and are never executed.
- Playlists are disabled, processing is serialized, and uploads default to 200 MB / 20 minutes.
- Spotify music links are not downloaded. Upload only audio you are allowed to process.
- Analysis is probabilistic. Isolated instruments generally produce cleaner Basic Pitch MIDI; Chordino is usually the better first view for a full mix.
- Source separation can remove masking, but separation artifacts can occasionally make recognition worse. It is opt-in so the same source can be compared with and without it.
- On every browser, selecting two or more tracks makes the server render them into one AAC stream before playback, avoiding multi-player start latency, drift, and glitches. Rapid track selections are debounced into one request; the first play creates a reusable cache, capped at 64 combinations per job.
- Per-stem MIDI uses Basic Pitch for pitched stems (vocals, bass, accompaniment, guitar, and piano). Drums remain an audio stem because pitched-note transcription is not a drum-event model.
- The six-source model is experimental. Demucs upstream specifically warns that the piano stem can contain substantial bleed and artifacts.
- Key estimation is inferred from the duration-weighted chord track and should be treated as a starting point when a song modulates or the chord recognition is sparse.
- Continuous TAB maps detected pitches onto standard-tuned guitar strings with a continuity heuristic. It is a playable estimate, not a claim about the original performer's exact string/fret choices or techniques.

## Acoustic change audit and local chord review

Recommendation revision 6 adds bounded acoustic change proposals without requiring another model to nominate a boundary. Silence, volume-only changes and beat grids cannot force chord changes. Acoustic-only chord candidates need local note support for every chord tone, added fundamentals and a strict two-window fit improvement; they are not another independent vote. Root, candidate bass, third and seventh evidence is stored separately, not presented as calibrated probabilities. All cross-verification pitch corrections now also require two independent model families: expanded evaluation exposed false octave-down corrections from spectral evidence alone. Inversions and omitted/extended tones remain ambiguous; this is not neural-network training.

Fixed-raw-output evaluation on 2026-10-08 is recorded in benchmarks/evaluation-20261008.json: 12 real acoustic clips across five genres. Recommended pitch/onset micro-F1 moves from 0.8994 to 0.8997; including offsets, from 0.7351 to 0.7392. Gains are small, regression-split onset F1 decreases (0.9368 to 0.9360), and false additions remain. Chord metrics are unchanged, so improved chord accuracy is not demonstrated. Two of eight prepared stress derivatives were evaluated; they are not real electric/band recordings or a blind test.

The collapsed **Recheck a short passage** panel accepts 0.5–90 seconds and offers selected-segment / next-doubt shortcuts. Dense 125 ms scanning reuses existing evidence in the durable shared queue, with existing ownership, retry, daily and concurrency limits. Preview and loop audition precede explicit confirmation into a separate local_review method. Original methods, key and private TAB remain intact. Source fingerprints and independent outside/manual/coverage validation reject stale or destructive proposals; an existing manual local version cannot be overwritten from another method. Unapplied proposals are hidden from other public viewers and exports.

TAB adds Auto / Connected melody / Stable accompaniment role costs, without filtering pitches or overriding valid manual fingerings. Confirmed slide/hammer-on/pull-off annotations persist privately and display s/h/p; same-string/direction constraints guide allocation and flag conflicts. These are manually confirmed techniques, not an automatic technique classifier or proof of the original fingering.

## Diverse and controlled-stress references

The original six-clip pilot remains immutable. A new --diverse --count 12 selection balances GuitarSet's BN/Funk/Jazz/Rock/SS, comp/solo and six performers, with performer-disjoint development/regression groups. Metrics separate exact chord labels, roots, base qualities and 250 ms-tolerant change boundaries; unsupported rich Harte exact labels are reported rather than silently treated as simpler chords.

tools/corpus_stress.py produces deterministic soft-clipped acoustic and procedural-drum-mix cases without pitch/timing changes. These are robustness derivatives, NOT real electric guitar or band recordings, and not independent reference samples. [Source registry](benchmarks/reference_sources.json) records provenance and licensing: EGDB/EGDB-PG remains unimported pending clear data rights and a suitable small aligned subset. GuitarSet overlap with existing training data remains possible/known, so neither this expansion nor synthetic robustness establishes blind real-song accuracy. Live recheck tests generate proposals only and never apply them.

## Attribution

- Basic Pitch: Spotify AB, Apache-2.0.
- NNLS Chroma / Chordino: Matthias Mauch and Chris Cannam; downloaded from the official Vamp plugin distribution with a pinned checksum.
- Demucs: Meta Research, MIT license.
- faster-whisper: SYSTRAN, MIT license; Whisper model weights originate from OpenAI's Whisper project.
- Noto Sans TC: Google, SIL Open Font License 1.1. The bundled license is stored at `vendor/fonts/OFL.txt`.
- The checksum-pinned no-root Chordino installation approach follows the MIT-licensed ChordFlask project by bkl2000.
