# Changelog

All notable changes to M4B to MP3 Batch Converter are listed here, newest first.

---

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
