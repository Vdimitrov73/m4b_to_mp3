# M4B to MP3 Batch Converter

Batch-converts DRM-free .M4B audiobook files to MP3 using **ffmpeg** on Windows.

## Defaults and settings

The main settings with default options:

- **Codec**: MP3 (LAME) — fixed.
- **Bitrate**:
  - Default mode: **Match source** (reads source bitrate via `ffprobe` and uses the nearest standard CBR; falls back to 128k CBR if unavailable).
  - Modes: Match source / CBR / VBR.
  - CBR: selectable steps (32k–192k, e.g. 32k, 64k, 96k, 128k, 160k, 192k).
  - VBR: slider 0–9 (0 = highest quality, 9 = lowest).
- **Sample rate**:
  - Default: same as source.
  - Options: 44100, 48000, 22050, 16000 Hz.
- **Channels**:
  - Default: same as source (auto-detect stereo).
  - Option: force mono (enabled when Auto detect Stereo is off).
- **Normalize**:
  - Default: off.
  - When enabled, applies `loudnorm` for volume normalization.
  - Automatically disabled when **Split by chapters** is on so each chapter is not normalized independently.
- **Chapters**:
  - Default: embed MP3 chapters (where ffmpeg/ffprobe exposes them).
  - Option: turn chapter embedding off.
  - Optional **Split by chapters** creates one MP3 per chapter using the pattern `Name - Chapter N.mp3`.
  - If split is requested but no chapter data is available, the file is converted as a single MP3 and a warning is logged.
- **Metadata**:
  - Copied from the source file (tags + chapters when enabled).
- **Output filename pattern**:
  - Default: `Author - Title`.
  - Options: `Author - Title`, `Title`, `Title - Author`, `Author`.
- **Multithreading**:
  - Default: enabled (ffmpeg `-threads 0`).
  - Can be turned off for debugging or reproducibility.
- **Progress display**:
  - Progress bar can show **Total** progress (all files combined) or **Current file** progress, with a numeric percentage label below it.

If a file cannot be converted (for example because it is DRM-protected), a warning is logged and the tool continues with the next file. Stopping the conversion from the GUI cleanly terminates the current `ffmpeg` process and skips to the batch summary.

## Requirements

- Windows 10/11.
- **ffmpeg** for Windows (ffmpeg + ffprobe) — see [INSTALL.md](INSTALL.md) for setup.
- Python 3.9 or later is only needed for the source/Python install option.

## Installation

Three options — see [INSTALL.md](INSTALL.md) for full details.

| Option | Best for |
|---|---|
| 🪟 **Microsoft Store** | Easiest — no Python, no SmartScreen, auto-updates |
| ⬇ **ZIP bundle** | Offline or portable install, no Python required |
| 🐍 **Python source** | Developers, or if you want to run directly from source |

**Microsoft Store** (recommended):
Search for **"M4B to MP3 Batch Converter"** in the Microsoft Store app, or
[click here](https://apps.microsoft.com/search?query=M4B+to+MP3+Batch+Converter&hl=en-US&gl=CA).

All three options require **ffmpeg** to be installed separately —
see the [Installing ffmpeg](INSTALL.md#installing-ffmpeg) section in INSTALL.md.

## Usage

1. Double-click the Desktop shortcut  
   (or run `pythonw inaudible_batch.py` from the tool folder).

2. In the GUI:

   - Set **Root directory** — defaults to your Downloads folder.
   - Verify **ffmpeg.exe** and (optionally) **ffprobe.exe** paths.
   - Adjust **Audio settings** (bitrate, sample rate, mono, normalize, chapters, output naming, multithreading) as desired.
   - Choose whether the progress bar shows **Total** or **Current file** progress.

3. Click **Scan** — the tool recursively finds all `.m4b` files under the root.

4. Click **Start Conversion**.

   - The **main log** shows high-level steps and per-file status.
   - The **Logs…** button opens a separate window with the full ffmpeg console output.
   - The percent label under the progress bar shows the current overall or per‑file completion.

5. You can click **Stop** at any time:

   - The running `ffmpeg` process is terminated.
   - The current file is treated as stopped (partial output discarded).
   - Remaining files in the list are not processed.

6. At the end, the tool prints a summary:

   - Total processed.
   - Converted successfully.
   - Protected/skipped (likely DRM).
   - Failed (with reasons).

## Output details

For each `.m4b` file, the converter:

- Reads tags, chapters, duration, and (when available) source bitrate using `ffprobe` (falls back to ffmpeg stderr for basic tags).
- Builds the output filename from the selected pattern and tags.
- Writes an MP3 with:

  ```text
  - Codec: libmp3lame
  - Bitrate:
      - Match source: nearest standard CBR to source bitrate (via ffprobe),
        or 128k CBR if unknown
      - CBR: selected fixed rate (e.g. 32k, 64k, 96k, 128k, 160k, 192k)
      - VBR: quality level 0–9
  - Sample rate: same as source, unless overridden
  - Channels: same as source (auto-detect stereo), unless forced mono
  - Metadata: copied from the source file
  - Chapters: embedded when enabled
  ```

- Saves cover art as a separate JPEG by extracting a frame from the attached picture stream when present.

Existing MP3 or cover files with the same name are overwritten.
