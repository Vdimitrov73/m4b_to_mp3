"""
M4B to MP3 Batch Converter

Batch-converts all DRM-free .m4b audiobook files found under a chosen root directory
to MP3 using ffmpeg on Windows.

Features:
- Codec: MP3 (LAME), fixed
- Bitrate: Match source by default, with options: / 32k / 64k / 96k / 128k CBR / VBR slider
- Sample rate: same as source by default, can force 44100 / 48000 / 22050 / 16000
- Channels: same as source (auto-detect stereo) by default, optional mono
- Chapters: copied where ffmpeg exposes them; can disable chapter embedding
- Normalize: off by default, optional loudnorm filter (disabled when split-by-chapters)
- Output filename pattern: Author - Title (default), Title, Title - Author, Author
- Multithreading: on by default (ffmpeg -threads 0)
- Optional split by chapters into separate MP3s: "Name - Chapter N" style

The main log shows high-level tasks; the detailed ffmpeg output is available via Logs button
"""

import os
import sys
import subprocess
import threading
import time
import queue
import json
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox


FFMPEG_EXE_DEFAULT = r"C:\ffmpeg\bin\ffmpeg.exe"
FFPROBE_EXE_DEFAULT = r"C:\ffmpeg\bin\ffprobe.exe"

# Metadata keys that are valid tag names (used to filter ffmpeg stderr scrape).
_KNOWN_TAG_KEYS = {"title", "artist", "author", "album", "album_artist", "performer"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_m4b_files(root_dir):
    """Return a sorted list of all .m4b files under root_dir (recursive)."""
    results = []
    for dirpath, _dirs, files in os.walk(root_dir, onerror=lambda e: None):
        for fname in files:
            if fname.lower().endswith(".m4b"):
                results.append(os.path.join(dirpath, fname))
    return sorted(results)


def sanitize_filename(name):
    """Sanitize a string so it is safe to use as a Windows filename."""
    invalid = set('<>:"/\\|?*')
    cleaned = "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in name)
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "output"


def probe_metadata_and_chapters(ffmpeg_path, ffprobe_path, m4b_path):
    """Return (tags, duration_seconds, chapters, source_bitrate).

    tags           : dict of lowercase metadata tags
    duration       : float seconds or None
    chapters       : list of (index, start_sec, end_sec, title_str)
    source_bitrate : int nearest standard CBR kbps (e.g. 128), or None if
                     ffprobe is unavailable or the field is missing
    """
    tags           = {}
    duration       = None
    chapters       = []
    source_bitrate = None

    # --- primary: ffprobe JSON -------------------------------------------------
    if ffprobe_path and os.path.isfile(ffprobe_path):
        try:
            cmd = [
                ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_chapters",
                m4b_path,
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                fmt = data.get("format", {})
                t = fmt.get("tags", {})
                if isinstance(t, dict):
                    tags = {k.lower(): v for k, v in t.items()}
                try:
                    duration = float(fmt.get("duration", "0") or 0.0)
                except Exception:
                    duration = None

                # bit_rate is the overall container bitrate in bps (string).
                # Round to nearest standard MP3 CBR step so LAME gets a clean
                # value (e.g. 127,813 bps -> "128k").
                try:
                    raw_bps = int(fmt.get("bit_rate") or 0)
                    if raw_bps > 0:
                        kbps = raw_bps / 1000.0
                        standards = [32, 40, 48, 56, 64, 80, 96, 112, 128,
                                     160, 192, 224, 256, 320]
                        source_bitrate = min(standards, key=lambda s: abs(s - kbps))
                except Exception:
                    source_bitrate = None

                for i, ch in enumerate(data.get("chapters", []), start=1):
                    start = float(ch.get("start_time", "0") or 0.0)
                    end   = float(ch.get("end_time",   "0") or 0.0)
                    ctags = ch.get("tags", {}) or {}
                    title = ctags.get("title") or ("Chapter %d" % i)
                    chapters.append((i, start, end, title))
        except subprocess.TimeoutExpired:
            # ffprobe timed out — non-fatal; fall through to ffmpeg scrape
            pass
        except Exception:
            # ffprobe failure is non-fatal; fall through to ffmpeg scrape
            pass

    # --- fallback: scrape basic tags from ffmpeg stderr -----------------------
    if not tags:
        try:
            r = subprocess.run(
                [ffmpeg_path, "-i", m4b_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            for line in (r.stderr or "").splitlines():
                line = line.strip()
                if ":" not in line:
                    continue
                key, _sep, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key not in _KNOWN_TAG_KEYS:
                    continue
                # Skip values that look like hh:mm:ss timestamps
                parts = val.split(":")
                if len(parts) >= 2 and all(p.strip().isdigit() for p in parts):
                    continue
                if val:
                    tags[key] = val
        except subprocess.TimeoutExpired:
            # ffmpeg scrape timed out — continue with empty tags
            pass
        except OSError as exc:
            # ffmpeg itself may not be available — non-fatal
            pass
        except Exception:
            # Any other failure is non-fatal; continue with empty tags
            pass

    return tags, duration, chapters, source_bitrate


def build_output_paths(m4b_path, tags, pattern):
    """Build base output paths from metadata and name pattern.

    pattern: 'author_title' | 'title' | 'title_author' | 'author'
    Returns (mp3_path, cover_path, base_name).
    """
    base_dir = os.path.dirname(m4b_path)
    stem = os.path.splitext(os.path.basename(m4b_path))[0]

    author = (
        tags.get("artist")
        or tags.get("author")
        or tags.get("album_artist")
        or tags.get("performer")
        or ""
    )
    title = tags.get("title") or stem

    if pattern == "author_title":
        base = ("%s - %s" % (author, title)) if author else title
    elif pattern == "title":
        base = title
    elif pattern == "title_author":
        base = ("%s - %s" % (title, author)) if author else title
    elif pattern == "author":
        base = author or title
    else:
        base = title

    base       = sanitize_filename(base)
    mp3_path   = os.path.join(base_dir, base + ".mp3")
    cover_path = os.path.join(base_dir, base + " cover.jpg")
    return mp3_path, cover_path, base


def is_likely_protected(text):
    """Heuristic: does ffmpeg output suggest a DRM-protected or unreadable file?"""
    keywords = [
        "drm",
        "protected",
        "encryption",
        "encrypted",
        "invalid data found when processing input",
        "error reading header",
        "failed to open",
        "unknown format",
        "operation not permitted",
    ]
    t = (text or "").lower()
    return any(k in t for k in keywords)


def build_ffmpeg_cmd(ffmpeg, src, dst, settings, start=None, end=None):
    """Build an ffmpeg command for one output file according to settings."""
    cmd = [ffmpeg, "-y"]

    # optional trimming (placed before -i for fast seek)
    if start is not None:
        cmd += ["-ss", "%.3f" % float(start)]
    if start is not None and end is not None:
        cmd += ["-t", "%.3f" % max(0.0, float(end - start))]

    cmd += ["-i", src]

    # sample rate
    if settings["sample_rate"] != "source":
        cmd += ["-ar", settings["sample_rate"]]

    # channels
    if settings["mono"]:
        cmd += ["-ac", "1"]

    # threads
    cmd += ["-threads", "0" if settings["multithread"] else "1"]

    # audio codec / bitrate
    cmd += ["-c:a", "libmp3lame"]
    mode = settings["bitrate_mode"]
    if mode == "cbr":
        cmd += ["-b:a", settings["cbr_bitrate"]]
    elif mode == "vbr":
        q = max(0, min(9, int(round(float(settings["vbr_q"])))))
        cmd += ["-q:a", str(q)]
    elif mode == "auto":
        # Use the bitrate read from the source file by ffprobe.
        # Fall back to 128k CBR if ffprobe was unavailable or returned nothing.
        br = settings.get("source_bitrate")
        if br:
            cmd += ["-b:a", "%dk" % br]
        else:
            cmd += ["-b:a", "128k"]

    # audio stream only, metadata, and optionally chapters
    cmd += [
        "-map", "0:a",
        "-id3v2_version", "3",
        "-write_id3v2", "1",
        "-map_metadata", "0",
    ]

    if settings["embed_chapters"]:
        cmd += ["-map_chapters", "0"]
    else:
        cmd += ["-map_chapters", "-1"]

    if settings["normalize"] and not settings.get("split_chapters", False):
        cmd += ["-af", "loudnorm"]

    cmd.append(dst)
    return cmd


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("M4B to MP3 Batch Converter")
        self.resizable(True, True)
        self.minsize(840, 640)

        self._queue        = queue.Queue()
        self._thread       = None
        self._stop_event   = threading.Event()
        self._files        = []
        self._file_checks  = []   # list of BooleanVar, one per scanned file
        self._current_proc = None   # ffmpeg Popen; killed immediately on Stop

        # progress state
        self._overall_total  = 0
        self._overall_done   = 0
        self._file_fraction  = 0.0

        # detailed log state
        self._detail_log    = []
        self._detail_window = None
        self._detail_text   = None

        # audio settings (defaults)
        self._bitrate_mode = tk.StringVar(value="auto")   # auto | cbr | vbr
        self._cbr_bitrate  = tk.StringVar(value="128k")  # 64k / 128k
        self._vbr_q        = tk.IntVar(value=5)          # 0..9

        self._sample_rate  = tk.StringVar(value="source")
        self._auto_stereo  = tk.BooleanVar(value=True)
        self._mono         = tk.BooleanVar(value=False)

        self._normalize       = tk.BooleanVar(value=False)
        self._embed_chapters  = tk.BooleanVar(value=True)
        self._split_chapters  = tk.BooleanVar(value=False)
        self._multithread     = tk.BooleanVar(value=True)

        self._name_pattern    = tk.StringVar(value="author_title")
        self._progress_mode   = tk.StringVar(value="overall")
        self._progress_text   = tk.StringVar(value="")

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        PAD = {"padx": 8, "pady": 4}

        # Root directory
        r1 = ttk.Frame(self)
        r1.pack(fill=tk.X, **PAD)
        ttk.Label(r1, text="Root directory:").pack(side=tk.LEFT)
        self._dir_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Downloads")
        )
        ttk.Entry(r1, textvariable=self._dir_var, width=60).pack(
            side=tk.LEFT, padx=(4, 0), expand=True, fill=tk.X
        )
        ttk.Button(r1, text="Browse…", command=self._browse_dir).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        # ffmpeg
        r2 = ttk.Frame(self)
        r2.pack(fill=tk.X, **PAD)
        ttk.Label(r2, text="ffmpeg.exe:").pack(side=tk.LEFT)
        self._ffmpeg_var = tk.StringVar(value=FFMPEG_EXE_DEFAULT)
        ttk.Entry(r2, textvariable=self._ffmpeg_var, width=60).pack(
            side=tk.LEFT, padx=(4, 0), expand=True, fill=tk.X
        )
        ttk.Button(r2, text="Browse…", command=self._browse_ffmpeg).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        # ffprobe
        r3 = ttk.Frame(self)
        r3.pack(fill=tk.X, **PAD)
        ttk.Label(r3, text="ffprobe.exe (optional):").pack(side=tk.LEFT)
        self._ffprobe_var = tk.StringVar(value=FFPROBE_EXE_DEFAULT)
        ttk.Entry(r3, textvariable=self._ffprobe_var, width=60).pack(
            side=tk.LEFT, padx=(4, 0), expand=True, fill=tk.X
        )
        ttk.Button(r3, text="Browse…", command=self._browse_ffprobe).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        # Audio settings frame
        sf = ttk.LabelFrame(self, text="Audio settings")
        sf.pack(fill=tk.X, **PAD)

        # Bitrate row
        br = ttk.Frame(sf)
        br.pack(fill=tk.X, pady=2)
        ttk.Label(br, text="Bitrate:").pack(side=tk.LEFT)

        auto_rb = ttk.Radiobutton(
            br, text="Match source", value="auto", variable=self._bitrate_mode
        )
        auto_rb.pack(side=tk.LEFT, padx=(4, 0))
        ToolTip(
            auto_rb,
            "Use the source file's bitrate (read by ffprobe) as CBR output.\n"
            "Falls back to 128k CBR if ffprobe is unavailable.",
        )

        ttk.Radiobutton(
            br, text="CBR", value="cbr", variable=self._bitrate_mode
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Combobox(
            br,
            width=6,
            state="readonly",
            textvariable=self._cbr_bitrate,
            values=["32k", "48k", "64k", "96k", "128k", "160k", "192k"],
        ).pack(side=tk.LEFT, padx=(2, 0))

        ttk.Radiobutton(
            br, text="VBR", value="vbr", variable=self._bitrate_mode
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._vbr_label = tk.StringVar(value="VBR mode: 5 (lower = higher quality)")
        ttk.Label(br, textvariable=self._vbr_label).pack(side=tk.LEFT, padx=(8, 0))
        self._vbr_scale = ttk.Scale(
            br,
            from_=0,
            to=9,
            orient=tk.HORIZONTAL,
            variable=self._vbr_q,
            command=self._on_vbr_change,
        )
        self._vbr_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        ToolTip(
            self._vbr_scale,
            "VBR quality setting 0–9.\n"
            "Lower = higher quality, larger files.\n"
            "Higher = lower quality, smaller files.",
        )

        # Sample rate / channels row
        sr = ttk.Frame(sf)
        sr.pack(fill=tk.X, pady=2)
        ttk.Label(sr, text="Sample rate:").pack(side=tk.LEFT)
        ttk.Combobox(
            sr,
            width=10,
            state="readonly",
            textvariable=self._sample_rate,
            values=["source", "44100", "48000", "22050", "16000"],
        ).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(sr, text="Channels:").pack(side=tk.LEFT, padx=(12, 0))
        self._auto_stereo_cb = ttk.Checkbutton(
            sr,
            text="Auto detect Stereo",
            variable=self._auto_stereo,
            command=self._update_channel_state,
        )
        self._auto_stereo_cb.pack(side=tk.LEFT, padx=(4, 0))
        ToolTip(self._auto_stereo_cb, "Keep channels as in source (auto detect stereo).")

        self._mono_cb = ttk.Checkbutton(sr, text="Mono", variable=self._mono)
        self._mono_cb.pack(side=tk.LEFT, padx=(4, 0))
        ToolTip(self._mono_cb, "Force mono output when Auto detect Stereo is off.")

        # Toggles row
        toggles = ttk.Frame(sf)
        toggles.pack(fill=tk.X, pady=2)

        self._normalize_cb = ttk.Checkbutton(
            toggles,
            text="Normalize",
            variable=self._normalize,
            command=self._on_normalize_or_split_change,
        )
        self._normalize_cb.pack(side=tk.LEFT)
        ToolTip(
            self._normalize_cb,
            "Apply loudnorm filter for consistent volume.\n"
            "Disabled when Split by chapters is on\n"
            "(each chapter would be normalized independently).",
        )

        ttk.Checkbutton(
            toggles, text="Embed MP3 chapters", variable=self._embed_chapters
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._split_cb = ttk.Checkbutton(
            toggles,
            text="Split by chapters (Name - Chapter N)",
            variable=self._split_chapters,
            command=self._on_normalize_or_split_change,
        )
        self._split_cb.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Checkbutton(
            toggles, text="Multithreading (ffmpeg)", variable=self._multithread
        ).pack(side=tk.LEFT, padx=(8, 0))

        # Name pattern row
        names = ttk.Frame(sf)
        names.pack(fill=tk.X, pady=2)
        ttk.Label(names, text="Output name:").pack(side=tk.LEFT)
        ttk.Combobox(
            names,
            width=25,
            state="readonly",
            textvariable=self._name_pattern,
            values=["author_title", "title", "title_author", "author"],
        ).pack(side=tk.LEFT, padx=(4, 0))

        # Scan row — Scan / Select All / Clear All / summary
        r4 = ttk.Frame(self)
        r4.pack(fill=tk.X, **PAD)
        ttk.Button(r4, text="Scan", command=self._scan).pack(side=tk.LEFT)
        ttk.Button(r4, text="Select All", command=self._select_all).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(r4, text="Clear All", command=self._clear_all).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        self._summary_var = tk.StringVar(value="")
        ttk.Label(r4, textvariable=self._summary_var, foreground="navy").pack(
            side=tk.LEFT, padx=(10, 0)
        )

        # Progress bar + mode toggle
        prog_frame = ttk.Frame(self)
        prog_frame.pack(fill=tk.X, **PAD)
        self._progress = ttk.Progressbar(
            prog_frame, orient=tk.HORIZONTAL, mode="determinate"
        )
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        mode_frame = ttk.Frame(prog_frame)
        mode_frame.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Total",
            value="overall",
            variable=self._progress_mode,
            command=self._refresh_progressbar,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            mode_frame,
            text="Current file",
            value="file",
            variable=self._progress_mode,
            command=self._refresh_progressbar,
        ).pack(side=tk.LEFT, padx=(4, 0))

        # Status label
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self._status_var, anchor=tk.W).pack(
            fill=tk.X, padx=8
        )

        # Percent label centred under the bar
        ttk.Label(self, textvariable=self._progress_text, anchor=tk.CENTER).pack(
            fill=tk.X
        )

        # ── File checklist ────────────────────────────────────────────────
        fl = ttk.LabelFrame(self, text="Files to convert")
        fl.pack(fill=tk.X, **PAD)

        # Scrollable inner frame for the checkboxes
        fl_canvas = tk.Canvas(fl, height=90, highlightthickness=0)
        fl_sb     = ttk.Scrollbar(fl, orient=tk.VERTICAL, command=fl_canvas.yview)
        fl_canvas.configure(yscrollcommand=fl_sb.set)
        fl_sb.pack(side=tk.RIGHT, fill=tk.Y)
        fl_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._check_frame = ttk.Frame(fl_canvas)
        self._check_frame_id = fl_canvas.create_window(
            (0, 0), window=self._check_frame, anchor="nw"
        )
        self._fl_canvas = fl_canvas

        def _on_frame_configure(event):
            fl_canvas.configure(scrollregion=fl_canvas.bbox("all"))

        def _on_canvas_configure(event):
            fl_canvas.itemconfig(self._check_frame_id, width=event.width)

        self._check_frame.bind("<Configure>", _on_frame_configure)
        fl_canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse-wheel scrolling inside the checklist
        def _on_mousewheel(event):
            fl_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        fl_canvas.bind("<MouseWheel>", _on_mousewheel)

        # ── Main log (high level) ─────────────────────────────────────────
        self._log = scrolledtext.ScrolledText(
            self, state=tk.DISABLED, height=12, font=("Consolas", 9)
        )
        self._log.pack(fill=tk.BOTH, expand=True, **PAD)
        self._log.tag_config("ok",   foreground="green")
        self._log.tag_config("err",  foreground="red")
        self._log.tag_config("info", foreground="navy")
        self._log.tag_config("warn", foreground="darkorange")

        # Bottom buttons
        bot = ttk.Frame(self)
        bot.pack(fill=tk.X, **PAD)
        self._start_btn = ttk.Button(
            bot, text="Start Conversion", command=self._start, state=tk.DISABLED
        )
        self._start_btn.pack(side=tk.LEFT)
        self._stop_btn = ttk.Button(
            bot, text="Stop", command=self._stop, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bot, text="Clear Log", command=self._clear_log).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(bot, text="Logs…", command=self._open_logs).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(bot, text="Quit", command=self.destroy).pack(side=tk.RIGHT)

        # initial widget states
        self._update_channel_state()
        self._on_normalize_or_split_change()

    # ------------------------------------------------------------------
    def _refresh_progressbar(self):
        mode    = self._progress_mode.get()
        max_val = max(self._overall_total, 1)

        if mode == "overall":
            value = min(self._overall_done + self._file_fraction, max_val)
            self._progress["maximum"] = max_val
            self._progress["value"]   = value
            pct = int(round((value / max_val) * 100)) if max_val > 0 else 0
        else:
            value = int(self._file_fraction * 100)
            self._progress["maximum"] = 100
            self._progress["value"]   = value
            pct = value

        self._progress_text.set("%d%%" % pct)

    # ------------------------------------------------------------------
    def _open_logs(self):
        if self._detail_window is not None and self._detail_window.winfo_exists():
            self._detail_window.lift()
            return

        win  = tk.Toplevel(self)
        win.title("Detailed log")
        win.minsize(800, 500)
        text = scrolledtext.ScrolledText(win, state=tk.NORMAL, font=("Consolas", 9))
        text.pack(fill=tk.BOTH, expand=True)

        self._detail_window = win
        self._detail_text   = text

        for line in self._detail_log:
            text.insert(tk.END, line)
        text.see(tk.END)
        text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    _DETAIL_LOG_MAX = 50000  # ~50k lines ≈ 10–20 MB depending on line length

    def _append_detail(self, text):
        self._detail_log.append(text)
        if len(self._detail_log) > self._DETAIL_LOG_MAX:
            self._detail_log = self._detail_log[-self._DETAIL_LOG_MAX // 2:]
        if (
            self._detail_text is not None
            and self._detail_window is not None
            and self._detail_window.winfo_exists()
        ):
            self._detail_text.config(state=tk.NORMAL)
            self._detail_text.insert(tk.END, text)
            self._detail_text.see(tk.END)
            self._detail_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    def _update_channel_state(self):
        """Enable/disable Mono checkbox based on Auto detect Stereo."""
        if self._auto_stereo.get():
            self._mono.set(False)
            self._mono_cb.state(["disabled"])
        else:
            self._mono_cb.state(["!disabled"])

    def _on_normalize_or_split_change(self):
        """Disable Normalize when Split by chapters is on, and vice-versa."""
        if self._split_chapters.get():
            if self._normalize.get():
                self._normalize.set(False)
            self._normalize_cb.state(["disabled"])
        else:
            self._normalize_cb.state(["!disabled"])

    # ------------------------------------------------------------------
    def _on_vbr_change(self, value):
        """Snap VBR scale to integer positions and update label."""
        try:
            v = int(round(float(value)))
        except Exception:
            v = self._vbr_q.get()
        v = max(0, min(9, v))
        if v != self._vbr_q.get():
            self._vbr_q.set(v)
        self._vbr_label.set("VBR mode: %d (lower = higher quality)" % v)

    # ------------------------------------------------------------------
    def _browse_dir(self):
        d = filedialog.askdirectory(
            title="Select root directory", initialdir=self._dir_var.get()
        )
        if d:
            self._dir_var.set(d)

    def _browse_ffmpeg(self):
        f = filedialog.askopenfilename(
            title="Select ffmpeg.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if f:
            self._ffmpeg_var.set(f)

    def _browse_ffprobe(self):
        f = filedialog.askopenfilename(
            title="Select ffprobe.exe (optional)",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if f:
            self._ffprobe_var.set(f)

    # ------------------------------------------------------------------
    def _populate_checklist(self):
        """Rebuild the file checklist from self._files (all checked by default)."""
        for widget in self._check_frame.winfo_children():
            widget.destroy()
        self._file_checks = []
        for path in self._files:
            var = tk.BooleanVar(value=True)
            self._file_checks.append(var)
            cb = ttk.Checkbutton(
                self._check_frame,
                text=path,
                variable=var,
                command=self._update_summary,
            )
            cb.pack(anchor=tk.W, padx=4, pady=1)
        self._fl_canvas.yview_moveto(0)

    def _selected_files(self):
        """Return the subset of self._files that are checked."""
        return [f for f, v in zip(self._files, self._file_checks) if v.get()]

    def _update_summary(self):
        n_total    = len(self._files)
        n_selected = len(self._selected_files())
        if n_total == 0:
            self._summary_var.set("")
        elif n_selected == n_total:
            self._summary_var.set("Found %d .m4b file%s — all selected." % (
                n_total, "s" if n_total != 1 else ""))
        else:
            self._summary_var.set("Found %d .m4b file%s — %d selected." % (
                n_total, "s" if n_total != 1 else "", n_selected))
        self._start_btn.config(state=tk.NORMAL if n_selected > 0 else tk.DISABLED)

    def _select_all(self):
        for v in self._file_checks:
            v.set(True)
        self._update_summary()

    def _clear_all(self):
        for v in self._file_checks:
            v.set(False)
        self._update_summary()

    # ------------------------------------------------------------------
    def _scan(self):
        root = self._dir_var.get().strip()
        if not os.path.isdir(root):
            messagebox.showerror("Error", "Directory not found\n" + root)
            return

        self._files         = find_m4b_files(root)
        n                   = len(self._files)
        self._overall_total = n
        self._overall_done  = 0
        self._file_fraction = 0.0
        self._refresh_progressbar()
        self._populate_checklist()
        self._update_summary()
        self._log_append("Scanned: %s\nFound %d .m4b file(s).\n" % (root, n), "info")
        for f in self._files:
            self._log_append("  " + f + "\n")
        self._start_btn.config(state=tk.NORMAL if n > 0 else tk.DISABLED)

    # ------------------------------------------------------------------
    def _start(self):
        ffmpeg  = self._ffmpeg_var.get().strip()
        ffprobe = self._ffprobe_var.get().strip()

        if not os.path.isfile(ffmpeg):
            messagebox.showerror("ffmpeg not found", "Cannot find ffmpeg.exe at\n" + ffmpeg)
            return
        if not self._files:
            messagebox.showinfo("Nothing to do", "No .m4b files found. Run Scan first.")
            return

        selected = self._selected_files()
        if not selected:
            messagebox.showinfo("Nothing to do", "No files selected. Check at least one file.")
            return
        if ffprobe and not os.path.isfile(ffprobe):
            if not messagebox.askyesno(
                "ffprobe not found",
                "ffprobe.exe not found at\n%s\n\nContinue without it?" % ffprobe,
            ):
                return
            ffprobe = ""

        settings = {
            "bitrate_mode":   self._bitrate_mode.get(),
            "cbr_bitrate":    self._cbr_bitrate.get(),
            "vbr_q":          float(self._vbr_q.get()),
            "sample_rate":    self._sample_rate.get(),
            "mono":           bool(self._mono.get()),
            "normalize":      bool(self._normalize.get()),
            "embed_chapters": bool(self._embed_chapters.get()),
            "split_chapters": bool(self._split_chapters.get()),
            "multithread":    bool(self._multithread.get()),
            "name_pattern":   self._name_pattern.get(),
        }

        self._stop_event.clear()
        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._overall_total = len(selected)
        self._overall_done  = 0
        self._file_fraction = 0.0
        self._refresh_progressbar()

        self._thread = threading.Thread(
            target=self._worker,
            args=(selected, ffmpeg, ffprobe, settings),
            daemon=True,
        )
        self._thread.start()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    def _stop(self):
        self._stop_event.set()
        proc = self._current_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            self._log_append("Stop requested — terminating current ffmpeg job…\n", "warn")
        else:
            self._log_append("Stop requested.\n", "warn")
        self._stop_btn.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    def _clear_log(self):
        self._log.config(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.config(state=tk.DISABLED)
        self._detail_log.clear()
        if self._detail_text is not None:
            self._detail_text.config(state=tk.NORMAL)
            self._detail_text.delete("1.0", tk.END)
            self._detail_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    def _worker(self, files, ffmpeg, ffprobe, settings):
        total           = len(files)
        errors          = []
        successes       = 0
        protected_count = 0
        processed       = 0

        for idx, m4b in enumerate(files, start=1):
            if self._stop_event.is_set():
                self._queue.put(("warn", "Stopped by user.\n"))
                break

            self._queue.put(("info", "\n[%d/%d] %s\n" % (idx, total, os.path.basename(m4b))))
            self._queue.put(("info", "       %s\n" % m4b))
            self._queue.put(("status", "Converting %d/%d: %s" % (idx, total, os.path.basename(m4b))))

            processed += 1
            tags, duration, chapters, source_bitrate = probe_metadata_and_chapters(ffmpeg, ffprobe, m4b)
            # Inject per-file source bitrate so build_ffmpeg_cmd can use it
            # when "Match source" (auto) mode is selected.
            settings["source_bitrate"] = source_bitrate
            if settings["bitrate_mode"] == "auto":
                if source_bitrate:
                    self._queue.put(("info", "  Source bitrate: %dk (match source)\n" % source_bitrate))
                else:
                    self._queue.put(("warn", "  Source bitrate unknown (ffprobe unavailable) — using 128k\n"))
            mp3_path, cover_path, base_name = build_output_paths(
                m4b, tags, settings["name_pattern"]
            )
            self._queue.put(("info", "  -> %s\n" % mp3_path))

            split = settings["split_chapters"] and bool(chapters)

            if settings["split_chapters"] and not chapters:
                self._queue.put((
                    "warn",
                    "  No chapter data available — converting as single file.\n",
                ))

            chap_files = []
            file_status = "ok"
            try:
                if split:
                    self._queue.put(("info", "  Splitting by %d chapter(s)…\n" % len(chapters)))
                    for chap_idx, start, end, chap_title in chapters:
                        if self._stop_event.is_set():
                            break
                        chap_base = sanitize_filename(
                            "%s - %s" % (base_name, chap_title or ("Chapter %d" % chap_idx))
                        )
                        chap_mp3 = os.path.join(os.path.dirname(mp3_path), chap_base + ".mp3")
                        chap_files.append(chap_mp3)
                        cmd = build_ffmpeg_cmd(ffmpeg, m4b, chap_mp3, settings, start=start, end=end)
                        status = self._run_ffmpeg_with_progress(cmd, None, chap_mp3)
                        if self._stop_event.is_set():
                            self._current_proc and self._current_proc.terminate()
                            status = "stopped"
                        if status != "ok" and file_status == "ok":
                            file_status = status
                else:
                    cmd = build_ffmpeg_cmd(ffmpeg, m4b, mp3_path, settings)
                    file_status = self._run_ffmpeg_with_progress(cmd, duration, mp3_path)

            except FileNotFoundError:
                self._queue.put(("err", "  ffmpeg.exe not found: %s\n" % ffmpeg))
                errors.append((m4b, "ffmpeg.exe not found"))
                break
            except Exception as exc:
                self._queue.put(("err", "  Exception: %s\n" % exc))
                errors.append((m4b, str(exc)))
                file_status = "error"
                if not split and mp3_path and os.path.exists(mp3_path):
                    try:
                        os.remove(mp3_path)
                    except OSError:
                        pass

            if file_status == "stopped" and chap_files:
                for cf in chap_files:
                    try:
                        if os.path.exists(cf):
                            os.remove(cf)
                    except OSError:
                        pass

            if file_status == "ok":
                successes += 1
                self._extract_cover(ffmpeg, m4b, cover_path)
            elif file_status == "protected":
                protected_count += 1
                errors.append((m4b, "DRM/protected"))
            elif file_status == "error":
                errors.append((m4b, "conversion failed"))
            # "stopped" → user-initiated, not counted as error

            self._queue.put(("progress", idx))

        failed = max(0, len(errors) - protected_count)
        self._queue.put(("info", "\n--- Batch complete -------------------------------------------\n"))
        self._queue.put((
            "info",
            "  Processed : %d\n"
            "  Converted : %d\n"
            "  Protected : %d (skipped)\n"
            "  Failed    : %d\n"
            % (processed, successes, protected_count, failed),
        ))
        if errors:
            self._queue.put(("warn", "\nFiles with issues:\n"))
            for path, reason in errors:
                self._queue.put(("err", "  %s\n    (%s)\n" % (path, reason)))
        else:
            self._queue.put(("ok", "\nAll files converted successfully.\n"))
        self._queue.put(("done", None))

    # ------------------------------------------------------------------
    def _run_ffmpeg_with_progress(self, cmd, duration, dst):
        """Run ffmpeg, stream output to the detail log, and emit progress.
        dst: output file path — deleted if the job is stopped mid-way to
             avoid leaving a corrupt partial MP3 on disk.
        Returns one of: 'ok', 'protected', 'error'.
        """
        t0 = time.time()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        self._current_proc = proc

        out_lines  = []
        last_frac  = 0.0

        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.rstrip("\r\n")
                if not line:
                    continue
                out_lines.append(line)
                if self._queue.qsize() < 500:
                    self._queue.put(("plain", "    " + line + "\n"))

                if duration and duration > 0 and "time=" in line:
                    try:
                        t_str   = line.split("time=", 1)[1].split()[0]
                        h, m, s = t_str.split(":")
                        seconds = float(h) * 3600 + float(m) * 60 + float(s)
                        frac    = max(0.0, min(1.0, seconds / duration))
                        if frac - last_frac >= 0.01:
                            last_frac = frac
                            self._queue.put(("file_progress", frac))
                    except Exception:
                        pass
        except Exception as exc:
            self._current_proc = None
            try:
                proc.terminate()
            except Exception:
                pass
            self._queue.put(("err", "  ffmpeg read error: %s\n" % exc))
            self._queue.put(("file_progress", 0.0))
            return "error"

        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        self._current_proc = None
        elapsed     = time.time() - t0
        stderr_text = "\n".join(out_lines)

        # Check return code FIRST: if ffmpeg completed successfully, keep the
        # output even if a stop-request raced past (the kill signal arrived too
        # late and the output is valid).
        if proc.returncode == 0:
            self._queue.put(("ok", "  Done in %.1fs\n" % elapsed))
            self._queue.put(("file_progress", 1.0))
            return "ok"

        if self._stop_event.is_set():
            # Remove the partial output file left by the killed process.
            try:
                if dst and os.path.exists(dst):
                    os.remove(dst)
                    self._queue.put(("warn", "  Stopped — partial file deleted: %s\n" % os.path.basename(dst)))
                else:
                    self._queue.put(("warn", "  Stopped — no partial file to clean up.\n"))
            except OSError as exc:
                self._queue.put(("warn", "  Stopped — could not delete partial file: %s\n" % exc))
            self._queue.put(("file_progress", 0.0))
            return "stopped"

        if is_likely_protected(stderr_text):
            self._queue.put((
                "warn",
                "  WARNING: Likely DRM-protected — skipped (exit %d, %.1fs)\n"
                % (proc.returncode, elapsed),
            ))
            self._queue.put(("file_progress", 0.0))
            return "protected"

        self._queue.put((
            "err",
            "  ERROR: ffmpeg failed — exit %d after %.1fs\n" % (proc.returncode, elapsed),
        ))
        self._queue.put(("file_progress", 0.0))
        return "error"

    # ------------------------------------------------------------------
    def _extract_cover(self, ffmpeg, m4b, cover_path):
        """Extract cover art as JPEG using ffmpeg (best-effort)."""
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            cmd = [
                ffmpeg, "-y", "-i", m4b,
                "-an", "-vcodec", "mjpeg", "-frames:v", "1",
                cover_path,
            ]
            r = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                timeout=15,
            )
            if r.returncode == 0:
                self._queue.put(("ok", "  Cover art saved.\n"))
            else:
                self._queue.put(("warn", "  No cover art found or extraction failed.\n"))
        except subprocess.TimeoutExpired:
            self._queue.put(("warn", "  Cover extraction timed out (15 s).\n"))
            try:
                if os.path.exists(cover_path):
                    os.remove(cover_path)
            except OSError:
                pass
        except Exception as exc:
            self._queue.put(("warn", "  Cover extraction error: %s\n" % exc))
            try:
                if os.path.exists(cover_path):
                    os.remove(cover_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self._queue.get_nowait()
                if msg_type == "done":
                    self._status_var.set("Done.")
                    self._start_btn.config(state=tk.NORMAL)
                    self._stop_btn.config(state=tk.DISABLED)
                    self._file_fraction = 1.0
                    self._refresh_progressbar()
                    return
                elif msg_type == "status":
                    self._status_var.set(payload)
                elif msg_type == "progress":
                    self._overall_done = payload
                    self._refresh_progressbar()
                elif msg_type == "file_progress":
                    self._file_fraction = payload
                    self._refresh_progressbar()
                elif msg_type == "plain":
                    self._append_detail(payload)
                else:
                    tag_map = {"ok": "ok", "err": "err", "info": "info", "warn": "warn"}
                    self._log_append(payload, tag_map.get(msg_type))
                    self._append_detail(payload)
        except queue.Empty:
            pass
        except Exception:
            pass
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    def _log_append(self, text, tag=None):
        self._log.config(state=tk.NORMAL)
        if tag:
            self._log.insert(tk.END, text, tag)
        else:
            self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# Tooltip helper
# ---------------------------------------------------------------------------

class ToolTip:
    """Minimal hover tooltip for Tk widgets."""

    def __init__(self, widget, text):
        self.widget     = widget
        self.text       = text
        self.tipwindow  = None
        widget.bind("<Enter>",   self._show)
        widget.bind("<Leave>",   self._hide)
        widget.bind("<Destroy>", self._hide)

    def _show(self, event=None):
        if self.tipwindow is not None:
            return
        x  = self.widget.winfo_rootx() + 20
        y  = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+%d+%d" % (x, y))
        tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 8),
        ).pack(ipadx=4, ipady=2)
        self.tipwindow = tw

    def _hide(self, event=None):
        tw = self.tipwindow
        if tw is not None:
            tw.destroy()
            self.tipwindow = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = ConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
