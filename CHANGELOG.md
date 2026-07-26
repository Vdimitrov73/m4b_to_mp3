# Changelog

All notable changes to M4B to MP3 Batch Converter are listed here, newest first.

---
## v1.0.4 — 2026-07-26
fix: preserve completed chapters on stop, harden process cleanup (v1.0.4)
- fix critical data-loss bug: stopping mid chapter-split no longer deletes
  chapters that had already finished converting — only unfinished or
  failed chapter files are cleaned up
- clear the ffmpeg process handle even if a forced kill doesn't exit
  before the follow-up wait times out, so Stop can't silently stop working
- log unexpected errors from the UI queue-polling loop instead of
  silently discarding them

## v1.0.3 — 2026-05-27

fix: apply validated QA patches (v1.0.3)

- handle permission-denied dirs in find_m4b_files
- add timeout/exception handling around ffmpeg read loop and wait()
- fix stop race in split-by-chapters and clean up orphaned chapter files
- delete partial MP3/cover files on errors
- clamp chapter duration end<=start to avoid encoding to EOF
- bound detail log and queue size to prevent memory growth

## v1.0.2 — 2026-05-23

### Bug fixes

- **Critical** — Fixed a race condition in `_run_ffmpeg_with_progress` where
  clicking Stop in the ~100ms window after ffmpeg finished but before the
  worker processed completion caused a valid, fully-converted MP3 to be
  deleted and reported as stopped. Return code is now checked before the
  stop-event flag.
- **Critical** — Added `timeout=30` to both `subprocess.run` calls in
  `probe_metadata_and_chapters` (ffprobe JSON path and ffmpeg stderr-scrape
  fallback). Without a timeout, a corrupt file or slow network drive would
  freeze the worker thread — and the entire batch — indefinitely.
- **High** — Added `timeout=15` to the ffmpeg `subprocess.run` call in
  `_extract_cover`. A hung cover extraction would stall the whole batch.
  Any partial cover file written before the timeout is now cleaned up
  automatically.
- **Medium** — Replaced bare `except Exception: pass` in the ffmpeg metadata
  scrape fallback with explicit `subprocess.TimeoutExpired` → `OSError` →
  `Exception` handlers to document the expected failure modes while keeping
  the non-fatal, continue-on-error design intact.

## v1.0.1 — 2026-04-04

- Added a checkable file list so you can choose exactly which scanned `.m4b`
  files to convert
- Scan now populates a "Files to convert" checklist instead of a plain log
  listing
- Added **Select All** / **Clear All** buttons next to Scan for quick
  bulk selection
- Summary line now shows how many files are selected (e.g. "Found 5 .m4b files
  — 3 selected")
- Start Conversion now runs only on the checked files and warns if nothing
  is selected
  
## v1.0.0 — 2026-04-04

- Initial public release
- Batch-converts DRM-free `.m4b` audiobook files to MP3 using ffmpeg
- GUI built with Python/Tkinter — no browser or web server required
- Bitrate: Match source (reads source bitrate via ffprobe, rounds to nearest
  standard CBR step), CBR (32k–192k), or VBR (quality 0–9)
- Sample rate: same as source by default; optional override (44100 / 48000 /
  22050 / 16000 Hz)
- Channels: auto-detect stereo by default; optional force mono
- Normalize: optional loudnorm filter; automatically disabled when
  Split by chapters is on
- Chapter support: embed MP3 chapters (ID3), or split into one MP3 per chapter
  using `Name - Chapter N.mp3` naming
- Output filename patterns: Author - Title, Title, Title - Author, Author
- Cover art extracted and saved as a separate JPEG alongside the MP3
- Metadata (tags + chapters) copied from source file via ffprobe/ffmpeg
- Dual progress bar: Total (all files) or Current file, with numeric percent
- Detailed ffmpeg log available via Logs… button (separate window)
- Stop button immediately terminates the running ffmpeg process; partial
  output file is deleted automatically
- DRM detection: files that cannot be decoded are flagged as likely
  DRM-protected and skipped; conversion continues with remaining files
- Batch summary at end: processed / converted / protected / failed counts
- Desktop shortcut installer (`install_shortcut.py`) — places a `.lnk`
  on the Windows Desktop pointing to `pythonw` (no console window)
- ffprobe optional: tool falls back to ffmpeg stderr tag scraping when
  ffprobe is not available
