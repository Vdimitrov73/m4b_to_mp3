# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

M4B to MP3 Batch Converter — a Windows desktop GUI app that batch-converts DRM-free `.m4b` audiobook files to MP3 using ffmpeg. Built with Python/Tkinter.

## Commands

```powershell
# Run from source (no console window — recommended)
pythonw inaudible_batch.py

# Run from source (with console window — for debugging)
python inaudible_batch.py

# Build standalone .exe with PyInstaller
pyinstaller --onefile --windowed --name inaudible_batch --version-file version.txt inaudible_batch.py

# Install desktop shortcut
python install_shortcut.py
```

## Architecture

The entire application lives in **`inaudible_batch.py`** (~1150 lines) with no other Python source files. There are no tests, no linters, and no type-checking configuration.

### Key structural sections

1. **Helper functions** (lines ~43–270): `find_m4b_files`, `sanitize_filename`, `probe_metadata_and_chapters`, `build_output_paths`, `is_likely_protected`, `build_ffmpeg_cmd`
2. **`ConverterApp(tk.Tk)` class** (lines ~276–1093): Main GUI window with directory input, ffmpeg/ffprobe paths, audio settings (bitrate, sample rate, channels, normalize, chapters, naming, threads), scan/select/clear buttons, scrollable file checklist, progress bar, color-coded main log, detailed ffmpeg log button, start/stop/clear/quit controls
3. **`ToolTip` class** (lines ~1099–1133): Hover tooltip helper
4. **Entry point** (lines ~1140–1146): `main()` creates `ConverterApp` and calls `app.mainloop()`

### Threading model

- Conversion runs in a **daemon thread** (`_worker`)
- Progress is reported back to the main thread via a **`queue.Queue`**
- Main thread polls the queue with `_poll_queue` (calls `.after()` to reschedule)
- Stop support: terminates the running ffmpeg process and deletes partial output

### Metadata probing

- `probe_metadata_and_chapters` uses **ffprobe** (JSON output) to read tags, duration, chapters, and source bitrate
- Falls back to **ffmpeg stderr scraping** when ffprobe is unavailable (parses `_KNOWN_TAG_KEYS`)
- Runs executable checks at startup to warn users if ffmpeg/ffprobe aren't found

### ffmpeg command building

`build_ffmpeg_cmd` constructs a complex ffmpeg command line with:
- MP3/LAME codec (fixed)
- Configurable bitrate (match source, fixed CBR 32–128k, or VBR 0–9)
- Sample rate conversion, mono downmix, loudnorm filter
- Chapter metadata embedding (or splitting into per-chapter files)
- `-threads 0` for multithreading (default on)

### Color-coded logging

- **Blue**: informational (found files, task start/completion)
- **Green**: success (file converted OK)
- **Red**: errors (DRM, conversion failures)
- **Orange**: warnings (ffmpeg/ffprobe not found)
- **Purple**: stop notifications

### Distribution targets

| Method | Mechanism |
|--------|-----------|
| Microsoft Store | `m4b-converter_msix/` — MSIX package with AppxManifest.xml |
| Standalone ZIP | PyInstaller `.exe` in `dist/`, bundled via CI |
| Source | `pythonw inaudible_batch.py` |

### CI/CD

- **GitHub Actions** (`.github/workflows/build_exe.yml`): triggers on `v*.*.*` tags, builds .exe, creates ZIP, publishes GitHub Release with SHA-256
- **GitLab CI** (`.gitlab-ci.yml`): same pipeline for GitLab Releases
- Both use PyInstaller with `--onefile --windowed`

## Key patterns to follow

- **No test/lint infrastructure exists** — don't assume pytest, flake8, or mypy are available
- **Windows-only** — all paths, line endings, and assumptions are Windows-native
- **Single-file pattern** — keep changes within `inaudible_batch.py` unless adding a new distribution concern
- **Queue-based threading** — never touch Tk widgets from worker threads; always post to the queue
- **ffprobe JSON is preferred** for metadata; ffmpeg stderr scraping is a fallback — preserve this priority
