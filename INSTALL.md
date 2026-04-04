# Installation

Choose the option that works best for you.

---

## Option A — Microsoft Store (recommended)

**[🪟 Get it from the Microsoft Store](https://apps.microsoft.com/search?query=M4B+to+MP3+Batch+Converter&hl=en-US&gl=CA)**

The easiest option. Installs cleanly on Windows 10/11 with no SmartScreen
warning, no Python required, and updates automatically.

> If you don't see it, search for **"M4B to MP3 Batch Converter"** in the Store app.

---

## Option B — ZIP bundle (no Python required)

**[⬇ Download latest release](https://gitlab.com/vdimitrov_73/m4b_to_mp3/-/releases/permalink/latest)**

1. Download and unzip anywhere (e.g. `C:\Tools\m4b_converter\`)
2. Install **ffmpeg** (see below)
3. Run `inaudible_batch.exe`
4. On first launch, verify the ffmpeg and ffprobe paths in the GUI

> **Windows SmartScreen warning?** Click **"More info"** then **"Run anyway"**.
> This warning appears because the executable is not signed with a paid EV
> certificate. The source code is fully open — you can review it or build
> the `.exe` yourself (see Option C).

---

## Option C — Python (run from source)

1. Install **Python 3.9 or later** from [python.org/downloads](https://www.python.org/downloads/)
   — check **"Add Python to PATH"** before clicking Install
2. Download and extract the **[source ZIP](https://gitlab.com/vdimitrov_73/m4b_to_mp3/-/archive/main/m4b_to_mp3-main.zip)**
3. Open a Command Prompt in the extracted folder and run:
   ```
   python install_shortcut.py
   ```
   This places **M4B to MP3 Batch Converter** on your Desktop.
4. Double-click the shortcut, or run `pythonw inaudible_batch.py` directly.

---

## Installing ffmpeg

The converter requires **ffmpeg** (and optionally **ffprobe**) for Windows.

**Recommended:** download a pre-built Windows binary from
[https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
(choose the **release essentials** ZIP).

1. Extract the ZIP — it contains a folder like `ffmpeg-7.x-essentials_build\`
2. Inside that folder, find `bin\ffmpeg.exe` and `bin\ffprobe.exe`
3. Copy the entire `bin\` folder (or the whole extracted folder) somewhere
   permanent, e.g. `C:\ffmpeg\`
4. The default paths in the GUI are:
   ```
   C:\ffmpeg\bin\ffmpeg.exe
   C:\ffmpeg\bin\ffprobe.exe
   ```
   If you installed elsewhere, update the paths in the GUI using the Browse buttons.

ffprobe is optional but recommended — it enables accurate source bitrate
detection ("Match source" mode) and chapter metadata.

---

## Verifying the download (optional)

The SHA-256 hash of `inaudible_batch.exe` is listed in each
[release](https://gitlab.com/vdimitrov_73/m4b_to_mp3/-/releases).

To verify:
```
certutil -hashfile inaudible_batch.exe SHA256
```
