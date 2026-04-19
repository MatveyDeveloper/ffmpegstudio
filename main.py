"""
FFmpeg Studio - CapCut-style GUI for FFmpeg
Auto-downloads FFmpeg on first run. Requires Python 3.8+

Install dependencies:
    pip install customtkinter pillow
"""

import os
import sys
import json
import shutil
import platform
import threading
import subprocess
import urllib.request
import zipfile
import tarfile
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import customtkinter as ctk
from PIL import Image, ImageTk
import time
import re

# ─── Theme ───────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG        = "#0f0f13"
PANEL     = "#16161d"
CARD      = "#1e1e2a"
ACCENT    = "#6c63ff"
ACCENT2   = "#ff6584"
TEXT      = "#e8e8f0"
MUTED     = "#6b6b80"
SUCCESS   = "#43d97b"
WARNING   = "#ffd166"
DANGER    = "#ef476f"
BORDER    = "#2a2a3a"

# ─── FFmpeg downloader ───────────────────────────────────────────────────────
FFMPEG_DIR = os.path.join(os.path.expanduser("~"), ".ffmpeg_studio")

FFMPEG_URLS = {
    "Windows": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "bin": ["ffmpeg.exe", "ffprobe.exe"],
        "strip": 2,
    },
    "Darwin": {
        "url": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "bin_ffmpeg": "ffmpeg",
        "url_probe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
        "bin_probe": "ffprobe",
    },
    "Linux": {
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "bin": ["ffmpeg", "ffprobe"],
        "strip": 1,
    },
}

def ffmpeg_path():
    ext = ".exe" if platform.system() == "Windows" else ""
    return os.path.join(FFMPEG_DIR, "bin", f"ffmpeg{ext}")

def ffprobe_path():
    ext = ".exe" if platform.system() == "Windows" else ""
    return os.path.join(FFMPEG_DIR, "bin", f"ffprobe{ext}")

def ffmpeg_available():
    return os.path.isfile(ffmpeg_path()) and os.path.isfile(ffprobe_path())

def download_ffmpeg(progress_cb=None, status_cb=None):
    """Download and extract FFmpeg binaries."""
    os.makedirs(os.path.join(FFMPEG_DIR, "bin"), exist_ok=True)
    system = platform.system()

    def report(msg):
        if status_cb:
            status_cb(msg)

    def reporthook(count, block_size, total_size):
        if progress_cb and total_size > 0:
            pct = min(count * block_size / total_size, 1.0)
            progress_cb(pct)

    if system == "Windows":
        info = FFMPEG_URLS["Windows"]
        report("Downloading FFmpeg for Windows…")
        tmp = os.path.join(FFMPEG_DIR, "ffmpeg.zip")
        urllib.request.urlretrieve(info["url"], tmp, reporthook)
        report("Extracting…")
        with zipfile.ZipFile(tmp) as z:
            for name in z.namelist():
                base = os.path.basename(name)
                if base in info["bin"]:
                    data = z.read(name)
                    dest = os.path.join(FFMPEG_DIR, "bin", base)
                    with open(dest, "wb") as f:
                        f.write(data)
        os.remove(tmp)

    elif system == "Darwin":
        info = FFMPEG_URLS["Darwin"]
        for url, fname in [(info["url"], "ffmpeg"), (info["url_probe"], "ffprobe")]:
            report(f"Downloading {fname} for macOS…")
            tmp = os.path.join(FFMPEG_DIR, f"{fname}.zip")
            urllib.request.urlretrieve(url, tmp, reporthook)
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():
                    if os.path.basename(name) == fname:
                        data = z.read(name)
                        dest = os.path.join(FFMPEG_DIR, "bin", fname)
                        with open(dest, "wb") as f:
                            f.write(data)
                        os.chmod(dest, 0o755)
            os.remove(tmp)

    elif system == "Linux":
        info = FFMPEG_URLS["Linux"]
        report("Downloading FFmpeg for Linux…")
        tmp = os.path.join(FFMPEG_DIR, "ffmpeg.tar.xz")
        urllib.request.urlretrieve(info["url"], tmp, reporthook)
        report("Extracting…")
        with tarfile.open(tmp) as t:
            for member in t.getmembers():
                base = os.path.basename(member.name)
                if base in info["bin"]:
                    member.name = base
                    t.extract(member, os.path.join(FFMPEG_DIR, "bin"))
                    os.chmod(os.path.join(FFMPEG_DIR, "bin", base), 0o755)
        os.remove(tmp)
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    report("FFmpeg ready!")

# ─── FFprobe helpers ─────────────────────────────────────────────────────────
def probe_file(path):
    cmd = [
        ffprobe_path(), "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)

def get_duration(path):
    info = probe_file(path)
    if info and "format" in info:
        return float(info["format"].get("duration", 0))
    return 0

def seconds_to_hms(s):
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"

def hms_to_seconds(hms):
    parts = hms.strip().split(":")
    if len(parts) == 3:
        return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0])*60 + float(parts[1])
    return float(parts[0])

# ─── FFmpeg runner ────────────────────────────────────────────────────────────
def run_ffmpeg(args, progress_cb=None, done_cb=None, log_cb=None):
    cmd = [ffmpeg_path()] + args
    if log_cb:
        log_cb(" ".join(cmd))

    duration_re = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
    time_re     = re.compile(r"time=\s*(\d+):(\d+):([\d.]+)")
    total_sec   = [0]

    def worker():
        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
            universal_newlines=True, bufsize=1
        )
        for line in proc.stderr:
            if log_cb:
                log_cb(line.rstrip())
            m = duration_re.search(line)
            if m and total_sec[0] == 0:
                h, mi, s = m.groups()
                total_sec[0] = int(h)*3600 + int(mi)*60 + float(s)
            m2 = time_re.search(line)
            if m2 and total_sec[0] > 0 and progress_cb:
                h, mi, s = m2.groups()
                cur = int(h)*3600 + int(mi)*60 + float(s)
                progress_cb(min(cur / total_sec[0], 1.0))
        proc.wait()
        if done_cb:
            done_cb(proc.returncode)

    threading.Thread(target=worker, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════════
#  SPLASH / DOWNLOAD SCREEN
# ═══════════════════════════════════════════════════════════════════════════════
class SplashWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FFmpeg Studio — Setup")
        self.geometry("520x340")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        ctk.CTkLabel(self, text="[ FFMPEG ]", font=("Courier", 32, "bold"), text_color=ACCENT).pack(pady=(36, 0))
        ctk.CTkLabel(self, text="FFmpeg Studio",
                     font=ctk.CTkFont("Helvetica", 28, "bold"),
                     text_color=ACCENT).pack()
        ctk.CTkLabel(self, text="Professional video editing powered by FFmpeg",
                     font=ctk.CTkFont("Helvetica", 13),
                     text_color=MUTED).pack(pady=(4, 28))

        self.status = ctk.CTkLabel(self, text="Checking for FFmpeg…",
                                   font=ctk.CTkFont("Helvetica", 12),
                                   text_color=TEXT)
        self.status.pack()

        self.bar = ctk.CTkProgressBar(self, width=400,
                                      progress_color=ACCENT,
                                      fg_color=CARD)
        self.bar.set(0)
        self.bar.pack(pady=14)

        self.log = ctk.CTkLabel(self, text="", font=ctk.CTkFont("Courier", 10),
                                text_color=MUTED)
        self.log.pack()

        self.after(200, self._check)

    def _check(self):
        if ffmpeg_available():
            self.status.configure(text="FFmpeg found ✓", text_color=SUCCESS)
            self.bar.set(1)
            self.after(800, self._launch)
        else:
            self.status.configure(text="FFmpeg not found — downloading…")
            threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        try:
            download_ffmpeg(
                progress_cb=lambda p: self.after(0, lambda: self.bar.set(p)),
                status_cb=lambda s: self.after(0, lambda: self.status.configure(text=s))
            )
            self.after(0, lambda: self.after(600, self._launch))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Download Failed", str(e)))

    def _launch(self):
        self.destroy()
        app = FFmpegStudio()
        app.mainloop()

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════
class FFmpegStudio(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FFmpeg Studio")
        self.geometry("1280x800")
        self.minsize(960, 600)
        self.configure(fg_color=BG)

        self.input_file  = tk.StringVar()
        self.output_file = tk.StringVar()
        self.duration    = 0
        self.media_info  = None

        self._build_ui()

    # ─── Layout ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Top bar
        self._topbar()
        # Main area
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=0, pady=0)
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # Content area MUST be created before sidebar (sidebar calls _switch_page)
        self.content = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        # Sidebar (will call _switch_page -> _page_io automatically)
        self._sidebar(main)

    def _topbar(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, height=52, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text=">> FFmpeg Studio",
                     font=ctk.CTkFont("Helvetica", 17, "bold"),
                     text_color=ACCENT).pack(side="left", padx=20)

        # Input file row
        ctk.CTkButton(bar, text="Open File", width=100, height=32,
                      fg_color=ACCENT, hover_color="#574fd6",
                      command=self._open_file).pack(side="left", padx=4, pady=10)

        self.inp_label = ctk.CTkLabel(bar, textvariable=self.input_file,
                                      text_color=MUTED,
                                      font=ctk.CTkFont("Courier", 11),
                                      width=420, anchor="w")
        self.inp_label.pack(side="left", padx=8)

        ctk.CTkLabel(bar, text="FFprobe",
                     font=ctk.CTkFont("Helvetica", 12),
                     text_color=MUTED).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="Media Info", width=100, height=32,
                      fg_color=CARD, border_width=1, border_color=BORDER,
                      hover_color=BORDER,
                      command=self._show_media_info).pack(side="right", padx=4)

    def _sidebar(self, parent):
        sb = ctk.CTkFrame(parent, fg_color=CARD, width=170, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.pack_propagate(False)

        ctk.CTkLabel(sb, text="TOOLS", font=ctk.CTkFont("Helvetica", 10, "bold"),
                     text_color=MUTED).pack(pady=(20, 6), padx=16, anchor="w")

        self._pages = {}
        self._active_btn = None

        tools = [
            ("[+]  I/O & Export",   "io",       self._page_io),
            ("[x]  Trim & Cut",     "trim",     self._page_trim),
            ("[~]  Filters",        "filters",  self._page_filters),
            ("[v]  Audio",          "audio",    self._page_audio),
            ("[>]  Speed & Time",   "speed",    self._page_speed),
            ("[c]  Convert",        "convert",  self._page_convert),
            ("[s]  Scale & Crop",   "scale",    self._page_scale),
            ("[t]  Subtitles",      "subs",     self._page_subs),
            ("[i]  Thumbnail",      "thumb",    self._page_thumb),
            ("[?]  Probe / Info",   "probe",    self._page_probe),
            ("[#]  Custom Command", "custom",   self._page_custom),
        ]

        for label, key, fn in tools:
            btn = ctk.CTkButton(
                sb, text=label, anchor="w", height=36,
                fg_color="transparent", hover_color=BORDER,
                text_color=TEXT, font=ctk.CTkFont("Helvetica", 12),
                command=lambda f=fn, k=key, b=None: self._switch_page(f, k)
            )
            btn.pack(fill="x", padx=8, pady=1)
            self._pages[key] = btn

        # Activate first
        self._switch_page(self._page_io, "io")

    def _switch_page(self, fn, key):
        if self._active_btn:
            self._active_btn.configure(fg_color="transparent", text_color=TEXT)
        btn = self._pages[key]
        btn.configure(fg_color=ACCENT, text_color="#ffffff")
        self._active_btn = btn
        # Destroy old page children
        for w in self.content.winfo_children():
            w.destroy()
        fn()

    # ─── Common helpers ───────────────────────────────────────────────────────
    def _open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Media Files",
                        "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v "
                        "*.mp3 *.aac *.wav *.flac *.ogg *.m4a"),
                       ("All Files", "*.*")])
        if path:
            self.input_file.set(path)
            self.duration = get_duration(path)
            self.media_info = probe_file(path)

    def _pick_output(self, var, ext="mp4"):
        path = filedialog.asksaveasfilename(
            defaultextension=f".{ext}",
            filetypes=[(ext.upper(), f"*.{ext}"), ("All Files", "*.*")])
        if path:
            var.set(path)

    def _scrollable(self):
        """Return a scrollable frame inside self.content."""
        canvas = tk.Canvas(self.content, bg=PANEL, highlightthickness=0)
        vsb = ctk.CTkScrollbar(self.content, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ctk.CTkFrame(canvas, fg_color=PANEL)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _resize(e):
            canvas.itemconfig(win, width=canvas.winfo_width())
        def _scroll(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.bind("<Configure>", _resize)
        inner.bind("<Configure>", _scroll)
        inner.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        return inner

    def _section(self, parent, title):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        f.pack(fill="x", padx=20, pady=(12, 0))
        ctk.CTkLabel(f, text=title,
                     font=ctk.CTkFont("Helvetica", 13, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=16, pady=(12, 6))
        return f

    def _run_btn(self, parent, cmd_builder, label="▶  Run"):
        bar_var = ctk.DoubleVar(value=0)
        log_box = ctk.CTkTextbox(parent, height=90, fg_color="#0a0a10",
                                  font=ctk.CTkFont("Courier", 10),
                                  text_color=MUTED)
        log_box.pack(fill="x", padx=20, pady=(8, 0))

        bar = ctk.CTkProgressBar(parent, variable=bar_var,
                                  progress_color=SUCCESS, fg_color=CARD)
        bar.pack(fill="x", padx=20, pady=4)

        def run():
            if not self.input_file.get():
                messagebox.showwarning("No Input", "Please open an input file first.")
                return
            args = cmd_builder()
            if args is None:
                return
            log_box.delete("1.0", "end")
            bar_var.set(0)

            def log(msg):
                self.after(0, lambda: (log_box.insert("end", msg+"\n"),
                                       log_box.see("end")))
            def progress(p):
                self.after(0, lambda: bar_var.set(p))
            def done(code):
                col = SUCCESS if code == 0 else DANGER
                msg = "✓ Done!" if code == 0 else f"✗ Error (code {code})"
                self.after(0, lambda: log(msg))
                self.after(0, lambda: bar.configure(progress_color=col))

            run_ffmpeg(["-y"] + args,
                       progress_cb=progress, done_cb=done, log_cb=log)

        ctk.CTkButton(parent, text=label, height=38,
                      fg_color=ACCENT, hover_color="#574fd6",
                      font=ctk.CTkFont("Helvetica", 13, "bold"),
                      command=run).pack(padx=20, pady=8, fill="x")

    # ═══════════════════════════════════════════════════════════════════════════
    #  PAGES
    # ═══════════════════════════════════════════════════════════════════════════

    # ─── I/O & Export ────────────────────────────────────────────────────────
    def _page_io(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="I/O & Export",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        # Output
        sec = self._section(p, "Output File")
        out_var = tk.StringVar()
        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkEntry(row, textvariable=out_var, placeholder_text="output.mp4",
                     width=380).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row, text="Browse", width=80,
                      command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        # Containers
        sec2 = self._section(p, "Container / Remux")
        fmt_var = tk.StringVar(value="mp4")
        fmts = ["mp4","mkv","mov","avi","webm","flv","ts","m4v","ogg","mp3","aac","wav","flac","opus","gif"]
        ctk.CTkLabel(sec2, text="Format:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec2, values=fmts, variable=fmt_var, width=200).pack(anchor="w", padx=16, pady=(0,12))

        # Video codec
        sec3 = self._section(p, "Video Codec")
        vc_var = tk.StringVar(value="copy")
        vcodecs = ["copy","libx264","libx265","libvpx-vp9","libaom-av1","mpeg4","libxvid","prores","dnxhd","rawvideo","gif"]
        ctk.CTkComboBox(sec3, values=vcodecs, variable=vc_var, width=200).pack(anchor="w", padx=16, pady=(0, 4))
        crf_var = tk.StringVar(value="23")
        ctk.CTkLabel(sec3, text="CRF (quality, lower=better):", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec3, textvariable=crf_var, width=80).pack(anchor="w", padx=16, pady=(0,4))
        preset_var = tk.StringVar(value="medium")
        presets = ["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"]
        ctk.CTkLabel(sec3, text="Preset:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec3, values=presets, variable=preset_var, width=200).pack(anchor="w", padx=16, pady=(0,12))

        # Audio codec
        sec4 = self._section(p, "Audio Codec")
        ac_var = tk.StringVar(value="copy")
        acodecs = ["copy","aac","mp3","libopus","flac","pcm_s16le","ac3","eac3","libvorbis"]
        ctk.CTkComboBox(sec4, values=acodecs, variable=ac_var, width=200).pack(anchor="w", padx=16, pady=(0, 4))
        abr_var = tk.StringVar(value="192k")
        ctk.CTkLabel(sec4, text="Audio bitrate:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec4, textvariable=abr_var, width=100).pack(anchor="w", padx=16, pady=(0,12))

        def build():
            if not out_var.get():
                messagebox.showwarning("No Output", "Set an output file path.")
                return None
            args = ["-i", self.input_file.get()]
            if vc_var.get() != "copy":
                args += ["-c:v", vc_var.get(), "-crf", crf_var.get(),
                         "-preset", preset_var.get()]
            else:
                args += ["-c:v", "copy"]
            if ac_var.get() != "copy":
                args += ["-c:a", ac_var.get(), "-b:a", abr_var.get()]
            else:
                args += ["-c:a", "copy"]
            args.append(out_var.get())
            return args

        self._run_btn(p, build, "▶  Export")

    # ─── Trim & Cut ───────────────────────────────────────────────────────────
    def _page_trim(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Trim & Cut",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Trim / Clip Range")
        ss_var = tk.StringVar(value="00:00:00")
        to_var = tk.StringVar(value="00:00:10")
        out_var = tk.StringVar()

        grid = ctk.CTkFrame(sec, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0,4))
        ctk.CTkLabel(grid, text="Start:", text_color=MUTED, width=60).grid(row=0, column=0, sticky="w")
        ctk.CTkEntry(grid, textvariable=ss_var, width=120).grid(row=0, column=1, padx=4, pady=4)
        ctk.CTkLabel(grid, text="End:", text_color=MUTED, width=60).grid(row=1, column=0, sticky="w")
        ctk.CTkEntry(grid, textvariable=to_var, width=120).grid(row=1, column=1, padx=4, pady=4)

        # Duration hint
        dur_lbl = ctk.CTkLabel(sec, text="", text_color=MUTED,
                               font=ctk.CTkFont("Helvetica", 11))
        dur_lbl.pack(anchor="w", padx=16)

        def refresh_dur(*_):
            try:
                s = hms_to_seconds(ss_var.get())
                e = hms_to_seconds(to_var.get())
                dur_lbl.configure(text=f"Clip duration: {seconds_to_hms(e-s)}")
            except Exception:
                pass
        ss_var.trace_add("write", refresh_dur)
        to_var.trace_add("write", refresh_dur)

        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4,12))
        ctk.CTkEntry(row, textvariable=out_var, placeholder_text="output.mp4", width=320).pack(side="left")
        ctk.CTkButton(row, text="Browse", width=80,
                      command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        # Segment split
        sec2 = self._section(p, "Split into Segments (every N seconds)")
        seg_var = tk.StringVar(value="60")
        out2_var = tk.StringVar(value="segment_%03d.mp4")
        ctk.CTkLabel(sec2, text="Segment duration (seconds):", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec2, textvariable=seg_var, width=100).pack(anchor="w", padx=16, pady=(0,4))
        ctk.CTkLabel(sec2, text="Output pattern (e.g. segment_%03d.mp4):", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec2, textvariable=out2_var, width=280).pack(anchor="w", padx=16, pady=(0,12))

        def build():
            if not out_var.get():
                messagebox.showwarning("No Output", "Set an output file."); return None
            return ["-i", self.input_file.get(),
                    "-ss", ss_var.get(), "-to", to_var.get(),
                    "-c", "copy", out_var.get()]

        def build_seg():
            return ["-i", self.input_file.get(),
                    "-c", "copy",
                    "-f", "segment",
                    "-segment_time", seg_var.get(),
                    "-reset_timestamps", "1",
                    out2_var.get()]

        self._run_btn(p, build, "▶  Trim Clip")

        ctk.CTkLabel(p, text="— OR —", text_color=MUTED).pack(pady=4)

        ctk.CTkButton(p, text="▶  Split into Segments", height=38,
                      fg_color=CARD, border_width=1, border_color=ACCENT,
                      text_color=ACCENT, hover_color=BORDER,
                      command=lambda: run_ffmpeg(["-y"] + build_seg(),
                          log_cb=lambda m: None, done_cb=lambda c:
                          messagebox.showinfo("Done", "Segments created!" if c==0 else f"Error {c}")
                      )).pack(padx=20, pady=4, fill="x")

    # ─── Filters ──────────────────────────────────────────────────────────────
    def _page_filters(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Video Filters",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        filters = {}

        # Brightness / Contrast / Saturation / Gamma
        sec = self._section(p, "Color Correction (eq filter)")
        for name, default, lo, hi in [
            ("brightness", 0, -1, 1),
            ("contrast",   1,  0, 3),
            ("saturation", 1,  0, 3),
            ("gamma",      1, 0.1, 10),
        ]:
            var = tk.DoubleVar(value=default)
            filters[name] = var
            row = ctk.CTkFrame(sec, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(row, text=f"{name.capitalize()}:", width=100, text_color=MUTED).pack(side="left")
            ctk.CTkSlider(row, from_=lo, to=hi, variable=var, width=260).pack(side="left", padx=6)
            ctk.CTkLabel(row, textvariable=var, width=50, text_color=TEXT).pack(side="left")
        ctk.CTkFrame(sec, fg_color="transparent", height=10).pack()

        # Hue / Color balance
        sec2 = self._section(p, "Hue & Color (hue filter)")
        hue_var = tk.DoubleVar(value=0)
        filters["hue"] = hue_var
        row2 = ctk.CTkFrame(sec2, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row2, text="Hue shift (°):", width=100, text_color=MUTED).pack(side="left")
        ctk.CTkSlider(row2, from_=-180, to=180, variable=hue_var, width=260).pack(side="left", padx=6)
        ctk.CTkLabel(row2, textvariable=hue_var, width=50, text_color=TEXT).pack(side="left")
        ctk.CTkFrame(sec2, fg_color="transparent", height=6).pack()

        # Blur / Sharpen
        sec3 = self._section(p, "Blur & Sharpen")
        blur_var  = tk.DoubleVar(value=0)
        sharp_var = tk.DoubleVar(value=0)
        filters["blur"]   = blur_var
        filters["sharp"]  = sharp_var
        for label, var, lo, hi in [("Blur radius:", blur_var, 0, 20),
                                    ("Sharpen:",     sharp_var, 0, 5)]:
            row = ctk.CTkFrame(sec3, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(row, text=label, width=100, text_color=MUTED).pack(side="left")
            ctk.CTkSlider(row, from_=lo, to=hi, variable=var, width=260).pack(side="left", padx=6)
            ctk.CTkLabel(row, textvariable=var, width=50, text_color=TEXT).pack(side="left")
        ctk.CTkFrame(sec3, fg_color="transparent", height=6).pack()

        # LUT / Vignette / Denoise / Rotate / Flip
        sec4 = self._section(p, "Transform & Effects")
        rot_var    = tk.StringVar(value="none")
        flip_var   = tk.StringVar(value="none")
        vignette   = tk.BooleanVar(value=False)
        denoise    = tk.BooleanVar(value=False)
        grayscale  = tk.BooleanVar(value=False)
        negate_var = tk.BooleanVar(value=False)
        fade_var   = tk.BooleanVar(value=False)
        fadein_var = tk.StringVar(value="2")

        opts_frame = ctk.CTkFrame(sec4, fg_color="transparent")
        opts_frame.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(opts_frame, text="Rotate:", text_color=MUTED, width=70).grid(row=0, column=0, sticky="w")
        ctk.CTkComboBox(opts_frame, values=["none","90CW","90CCW","180"], variable=rot_var, width=120).grid(row=0, column=1, padx=4)
        ctk.CTkLabel(opts_frame, text="Flip:", text_color=MUTED, width=70).grid(row=0, column=2, sticky="w", padx=(12,0))
        ctk.CTkComboBox(opts_frame, values=["none","horizontal","vertical","both"], variable=flip_var, width=120).grid(row=0, column=3, padx=4)

        checks = ctk.CTkFrame(sec4, fg_color="transparent")
        checks.pack(fill="x", padx=16, pady=(4,12))
        for i, (label, var) in enumerate([("Vignette", vignette), ("Denoise (hqdn3d)", denoise),
                                           ("Grayscale", grayscale), ("Negate", negate_var)]):
            ctk.CTkCheckBox(checks, text=label, variable=var,
                            checkmark_color=ACCENT, fg_color=ACCENT).grid(row=0, column=i, padx=10)
        fade_row = ctk.CTkFrame(sec4, fg_color="transparent")
        fade_row.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkCheckBox(fade_row, text="Fade-in (seconds):", variable=fade_var,
                        checkmark_color=ACCENT, fg_color=ACCENT).pack(side="left")
        ctk.CTkEntry(fade_row, textvariable=fadein_var, width=60).pack(side="left", padx=6)

        out_var = tk.StringVar()
        row_out = ctk.CTkFrame(p, fg_color="transparent")
        row_out.pack(fill="x", padx=20, pady=(12, 0))
        ctk.CTkEntry(row_out, textvariable=out_var, placeholder_text="filtered_output.mp4", width=360).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row_out, text="Browse", width=80, command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        def build():
            if not out_var.get():
                messagebox.showwarning("No Output", "Set output."); return None
            vf_parts = []
            # eq
            br = round(filters["brightness"].get(), 3)
            co = round(filters["contrast"].get(), 3)
            sa = round(filters["saturation"].get(), 3)
            ga = round(filters["gamma"].get(), 3)
            if br!=0 or co!=1 or sa!=1 or ga!=1:
                vf_parts.append(f"eq=brightness={br}:contrast={co}:saturation={sa}:gamma={ga}")
            # hue
            hue = round(filters["hue"].get(), 1)
            if hue != 0:
                vf_parts.append(f"hue=h={hue}")
            # blur
            bl = round(filters["blur"].get(), 1)
            if bl > 0:
                rad = max(1, int(bl)*2+1)
                vf_parts.append(f"boxblur={bl}:1")
            # sharpen
            sh = round(filters["sharp"].get(), 2)
            if sh > 0:
                vf_parts.append(f"unsharp=5:5:{sh}:5:5:0")
            # rotate
            rot = rot_var.get()
            if rot == "90CW":   vf_parts.append("transpose=1")
            elif rot == "90CCW": vf_parts.append("transpose=2")
            elif rot == "180":   vf_parts.append("transpose=1,transpose=1")
            # flip
            flip = flip_var.get()
            if flip == "horizontal": vf_parts.append("hflip")
            elif flip == "vertical": vf_parts.append("vflip")
            elif flip == "both":     vf_parts.append("hflip,vflip")
            # extras
            if vignette.get():  vf_parts.append("vignette")
            if denoise.get():   vf_parts.append("hqdn3d=4:4:3:3")
            if grayscale.get(): vf_parts.append("hue=s=0")
            if negate_var.get(): vf_parts.append("negate")
            if fade_var.get():
                vf_parts.append(f"fade=t=in:st=0:d={fadein_var.get()}")

            args = ["-i", self.input_file.get()]
            if vf_parts:
                args += ["-vf", ",".join(vf_parts)]
            args += ["-c:a", "copy", out_var.get()]
            return args

        self._run_btn(p, build, "▶  Apply Filters")

    # ─── Audio ────────────────────────────────────────────────────────────────
    def _page_audio(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Audio Tools",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Volume & Normalization")
        vol_var    = tk.DoubleVar(value=1.0)
        norm_var   = tk.BooleanVar(value=False)
        loudnorm   = tk.BooleanVar(value=False)
        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text="Volume multiplier:", width=150, text_color=MUTED).pack(side="left")
        ctk.CTkSlider(row, from_=0, to=4, variable=vol_var, width=240).pack(side="left", padx=6)
        ctk.CTkLabel(row, textvariable=vol_var, width=50, text_color=TEXT).pack(side="left")
        ctk.CTkCheckBox(sec, text="Normalize (dynaudnorm)", variable=norm_var,
                        checkmark_color=ACCENT, fg_color=ACCENT).pack(anchor="w", padx=16, pady=2)
        ctk.CTkCheckBox(sec, text="Loudness normalize (EBU R128 -23 LUFS)", variable=loudnorm,
                        checkmark_color=ACCENT, fg_color=ACCENT).pack(anchor="w", padx=16, pady=(2,12))

        sec2 = self._section(p, "Channels & Sample Rate")
        ch_var  = tk.StringVar(value="unchanged")
        sr_var  = tk.StringVar(value="unchanged")
        ctk.CTkLabel(sec2, text="Channels:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec2, values=["unchanged","1 (mono)","2 (stereo)","5.1"], variable=ch_var, width=180).pack(anchor="w", padx=16, pady=(0,4))
        ctk.CTkLabel(sec2, text="Sample rate:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec2, values=["unchanged","8000","16000","22050","44100","48000","96000"], variable=sr_var, width=180).pack(anchor="w", padx=16, pady=(0,12))

        sec3 = self._section(p, "Strip / Extract / Merge")
        strip_var   = tk.BooleanVar(value=False)
        ext_aud_var = tk.StringVar(value="audio_out.mp3")
        add_aud_var = tk.StringVar()
        ctk.CTkCheckBox(sec3, text="Strip all audio (video only)", variable=strip_var,
                        checkmark_color=ACCENT, fg_color=ACCENT).pack(anchor="w", padx=16, pady=4)
        row_e = ctk.CTkFrame(sec3, fg_color="transparent")
        row_e.pack(fill="x", padx=16, pady=2)
        ctk.CTkLabel(row_e, text="Extract audio to:", width=130, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_e, textvariable=ext_aud_var, width=200).pack(side="left")
        row_a = ctk.CTkFrame(sec3, fg_color="transparent")
        row_a.pack(fill="x", padx=16, pady=(2,12))
        ctk.CTkLabel(row_a, text="Replace audio with:", width=130, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_a, textvariable=add_aud_var, placeholder_text="new_audio.mp3", width=200).pack(side="left")
        ctk.CTkButton(row_a, text="Browse", width=70,
                      command=lambda: add_aud_var.set(filedialog.askopenfilename())).pack(side="left", padx=4)

        out_var = tk.StringVar()
        row_out = ctk.CTkFrame(p, fg_color="transparent")
        row_out.pack(fill="x", padx=20, pady=(12,0))
        ctk.CTkEntry(row_out, textvariable=out_var, placeholder_text="output.mp4", width=360).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row_out, text="Browse", width=80, command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        def build():
            if not out_var.get(): messagebox.showwarning("No Output","Set output."); return None
            af = []
            v = round(vol_var.get(), 3)
            if v != 1.0: af.append(f"volume={v}")
            if norm_var.get(): af.append("dynaudnorm")
            if loudnorm.get(): af.append("loudnorm=I=-23:TP=-1.5:LRA=11")

            args = ["-i", self.input_file.get()]
            if add_aud_var.get():
                args += ["-i", add_aud_var.get(), "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0"]

            if af: args += ["-af", ",".join(af)]
            if strip_var.get(): args += ["-an"]

            ch = ch_var.get()
            if ch != "unchanged": args += ["-ac", ch.split()[0]]
            sr = sr_var.get()
            if sr != "unchanged": args += ["-ar", sr]

            args.append(out_var.get())
            return args

        self._run_btn(p, build, "▶  Process Audio")

        # Extract button
        ctk.CTkButton(p, text="▶  Extract Audio Now",
                      height=38, fg_color=CARD, border_width=1,
                      border_color=ACCENT2, text_color=ACCENT2, hover_color=BORDER,
                      command=lambda: run_ffmpeg(
                          ["-y", "-i", self.input_file.get(), "-vn", ext_aud_var.get()],
                          done_cb=lambda c: messagebox.showinfo("Done","Audio extracted!" if c==0 else f"Error {c}"),
                          log_cb=lambda m: None
                      )).pack(padx=20, pady=4, fill="x")

    # ─── Speed & Time ─────────────────────────────────────────────────────────
    def _page_speed(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Speed & Time",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Playback Speed")
        sp_var = tk.DoubleVar(value=1.0)
        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(row, text="Speed multiplier:", width=140, text_color=MUTED).pack(side="left")
        ctk.CTkSlider(row, from_=0.25, to=4.0, variable=sp_var, width=240).pack(side="left", padx=6)
        ctk.CTkLabel(row, textvariable=sp_var, width=50, text_color=TEXT).pack(side="left")
        ctk.CTkLabel(sec, text="0.25x = slow-mo  |  2x = fast forward  |  Values >2 may affect audio",
                     text_color=MUTED, font=ctk.CTkFont("Helvetica", 10)).pack(anchor="w", padx=16, pady=(0,12))

        sec2 = self._section(p, "Reverse Video")
        rev_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(sec2, text="Reverse video (and audio)", variable=rev_var,
                        checkmark_color=ACCENT, fg_color=ACCENT).pack(anchor="w", padx=16, pady=(4,12))

        sec3 = self._section(p, "Frame Rate")
        fps_var = tk.StringVar(value="30")
        ctk.CTkLabel(sec3, text="Output FPS:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec3, values=["23.976","24","25","29.97","30","50","59.94","60","120","240"], variable=fps_var, width=140).pack(anchor="w", padx=16, pady=(0,12))

        sec4 = self._section(p, "Time-lapse / Freeze Frame")
        timelapse_var = tk.StringVar(value="4")
        freeze_var    = tk.StringVar(value="5")
        ctk.CTkLabel(sec4, text="Time-lapse (keep 1/N frames):", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec4, textvariable=timelapse_var, width=80).pack(anchor="w", padx=16, pady=(0,4))
        ctk.CTkLabel(sec4, text="Freeze last frame for N seconds:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec4, textvariable=freeze_var, width=80).pack(anchor="w", padx=16, pady=(0,12))

        out_var = tk.StringVar()
        row_out = ctk.CTkFrame(p, fg_color="transparent")
        row_out.pack(fill="x", padx=20, pady=(12,0))
        ctk.CTkEntry(row_out, textvariable=out_var, placeholder_text="output.mp4", width=360).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row_out, text="Browse", width=80, command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        def build():
            if not out_var.get(): messagebox.showwarning("No Output","Set output."); return None
            sp = round(sp_var.get(), 3)
            args = ["-i", self.input_file.get()]
            vf, af = [], []
            if rev_var.get(): vf.append("reverse"); af.append("areverse")
            if sp != 1.0:
                vf.append(f"setpts={1/sp:.4f}*PTS")
                # atempo only supports 0.5-2.0; chain for extremes
                if sp <= 2.0:
                    af.append(f"atempo={sp:.3f}")
                elif sp <= 4.0:
                    af += [f"atempo=2.0", f"atempo={sp/2:.3f}"]
                else:
                    af += [f"atempo=2.0", "atempo=2.0", f"atempo={sp/4:.3f}"]
            if vf: args += ["-vf", ",".join(vf)]
            if af: args += ["-af", ",".join(af)]
            args += ["-r", fps_var.get(), out_var.get()]
            return args

        self._run_btn(p, build, "▶  Apply Speed / Time")

    # ─── Convert ─────────────────────────────────────────────────────────────
    def _page_convert(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Format Convert",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Quick Convert")
        presets = {
            "MP4 (H.264 + AAC)":     ["-c:v","libx264","-crf","23","-c:a","aac","-b:a","192k"],
            "MP4 (H.265/HEVC)":      ["-c:v","libx265","-crf","28","-c:a","aac"],
            "WebM (VP9 + Opus)":     ["-c:v","libvpx-vp9","-b:v","0","-crf","33","-c:a","libopus"],
            "GIF (palette)":         ["-vf","fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"],
            "MP3 (320kbps)":         ["-vn","-c:a","libmp3lame","-b:a","320k"],
            "AAC (256kbps)":         ["-vn","-c:a","aac","-b:a","256k"],
            "FLAC (lossless)":       ["-vn","-c:a","flac"],
            "WAV (PCM)":             ["-vn","-c:a","pcm_s16le"],
            "Opus (96kbps)":         ["-vn","-c:a","libopus","-b:a","96k"],
            "Image sequence (PNG)":  ["-vf","fps=1","%04d.png"],
            "ProRes 422":            ["-c:v","prores_ks","-profile:v","2","-c:a","pcm_s16le"],
            "Remux (copy codecs)":   ["-c","copy"],
        }

        preset_var = tk.StringVar(value=list(presets.keys())[0])
        out_var    = tk.StringVar()

        ctk.CTkLabel(sec, text="Select preset:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec, values=list(presets.keys()), variable=preset_var, width=320).pack(anchor="w", padx=16, pady=(0,12))

        row_out = ctk.CTkFrame(sec, fg_color="transparent")
        row_out.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkEntry(row_out, textvariable=out_var, placeholder_text="output.mp4", width=320).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row_out, text="Browse", width=80, command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        sec2 = self._section(p, "Batch Convert (same folder)")
        batch_dir  = tk.StringVar()
        batch_ext  = tk.StringVar(value="mp4")
        batch_out  = tk.StringVar(value="mp4")
        row_b = ctk.CTkFrame(sec2, fg_color="transparent")
        row_b.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_b, text="Folder:", width=60, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_b, textvariable=batch_dir, width=300).pack(side="left")
        ctk.CTkButton(row_b, text="Browse", width=70,
                      command=lambda: batch_dir.set(filedialog.askdirectory())).pack(side="left", padx=4)
        row_b2 = ctk.CTkFrame(sec2, fg_color="transparent")
        row_b2.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkLabel(row_b2, text="Input ext:", width=70, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_b2, textvariable=batch_ext, width=80).pack(side="left", padx=4)
        ctk.CTkLabel(row_b2, text="→ Output ext:", text_color=MUTED).pack(side="left", padx=4)
        ctk.CTkEntry(row_b2, textvariable=batch_out, width=80).pack(side="left")

        def build():
            if not out_var.get(): messagebox.showwarning("No Output","Set output."); return None
            extra = presets[preset_var.get()]
            if extra[-1].endswith(".png") and "%04d" in extra[-1]:
                return ["-i", self.input_file.get()] + extra[:-1] + [out_var.get()]
            return ["-i", self.input_file.get()] + extra + [out_var.get()]

        def batch_run():
            d = batch_dir.get()
            if not d: messagebox.showwarning("No Folder","Pick a folder."); return
            files = [f for f in os.listdir(d) if f.endswith(f".{batch_ext.get()}")]
            if not files: messagebox.showinfo("None found", f"No .{batch_ext.get()} files."); return
            for f in files:
                inp = os.path.join(d, f)
                out = os.path.join(d, f.rsplit(".", 1)[0] + f".{batch_out.get()}")
                run_ffmpeg(["-y","-i",inp,"-c:v","copy","-c:a","copy",out],
                           log_cb=lambda m: None, done_cb=lambda c: None)
            messagebox.showinfo("Batch", f"Started {len(files)} conversions.")

        self._run_btn(p, build, "▶  Convert")
        ctk.CTkButton(p, text="▶  Batch Convert Folder", height=38,
                      fg_color=CARD, border_width=1, border_color=WARNING,
                      text_color=WARNING, hover_color=BORDER,
                      command=batch_run).pack(padx=20, pady=4, fill="x")

    # ─── Scale & Crop ─────────────────────────────────────────────────────────
    def _page_scale(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Scale & Crop",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Scale / Resize")
        w_var = tk.StringVar(value="1280")
        h_var = tk.StringVar(value="-1")
        keep_var = tk.BooleanVar(value=True)
        algo_var = tk.StringVar(value="lanczos")
        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row, text="Width:", width=60, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row, textvariable=w_var, width=100).pack(side="left", padx=4)
        ctk.CTkLabel(row, text="Height:", text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row, textvariable=h_var, width=100).pack(side="left", padx=4)
        ctk.CTkLabel(row, text="(-1 = keep ratio)", text_color=MUTED, font=ctk.CTkFont("Helvetica",10)).pack(side="left")
        ctk.CTkLabel(sec, text="Scale algorithm:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec, values=["lanczos","bicubic","bilinear","nearest","sinc"], variable=algo_var, width=180).pack(anchor="w", padx=16, pady=(0,12))

        sec2 = self._section(p, "Crop")
        cw_var = tk.StringVar(value="1280")
        ch_var = tk.StringVar(value="720")
        cx_var = tk.StringVar(value="0")
        cy_var = tk.StringVar(value="0")
        pad_var    = tk.BooleanVar(value=False)
        padw_var   = tk.StringVar(value="1920")
        padh_var   = tk.StringVar(value="1080")
        padcol_var = tk.StringVar(value="black")

        grid = ctk.CTkFrame(sec2, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=4)
        for i, (lbl, var) in enumerate([("Width:", cw_var), ("Height:", ch_var),
                                          ("X:", cx_var), ("Y:", cy_var)]):
            ctk.CTkLabel(grid, text=lbl, text_color=MUTED, width=60).grid(row=i//2, column=(i%2)*2, sticky="w", pady=2)
            ctk.CTkEntry(grid, textvariable=var, width=100).grid(row=i//2, column=(i%2)*2+1, padx=4, pady=2)

        ctk.CTkFrame(sec2, fg_color="transparent", height=4).pack()
        ctk.CTkCheckBox(sec2, text="Pad to size:", variable=pad_var,
                        checkmark_color=ACCENT, fg_color=ACCENT).pack(anchor="w", padx=16)
        pad_row = ctk.CTkFrame(sec2, fg_color="transparent")
        pad_row.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkEntry(pad_row, textvariable=padw_var, width=90).pack(side="left", padx=2)
        ctk.CTkLabel(pad_row, text="x", text_color=MUTED).pack(side="left")
        ctk.CTkEntry(pad_row, textvariable=padh_var, width=90).pack(side="left", padx=2)
        ctk.CTkLabel(pad_row, text="Color:", text_color=MUTED).pack(side="left", padx=4)
        ctk.CTkEntry(pad_row, textvariable=padcol_var, width=100).pack(side="left")

        sec3 = self._section(p, "Aspect Ratio & Letterbox")
        ar_var = tk.StringVar(value="none")
        ctk.CTkLabel(sec3, text="Force aspect ratio:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkComboBox(sec3, values=["none","16:9","4:3","1:1","9:16","21:9","2.35:1"], variable=ar_var, width=180).pack(anchor="w", padx=16, pady=(0,12))

        out_var = tk.StringVar()
        row_out = ctk.CTkFrame(p, fg_color="transparent")
        row_out.pack(fill="x", padx=20, pady=(12,0))
        ctk.CTkEntry(row_out, textvariable=out_var, placeholder_text="output.mp4", width=360).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row_out, text="Browse", width=80, command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        def build():
            if not out_var.get(): messagebox.showwarning("No Output","Set output."); return None
            vf = []
            vf.append(f"scale={w_var.get()}:{h_var.get()}:flags={algo_var.get()}")
            vf.append(f"crop={cw_var.get()}:{ch_var.get()}:{cx_var.get()}:{cy_var.get()}")
            if pad_var.get():
                vf.append(f"pad={padw_var.get()}:{padh_var.get()}:(ow-iw)/2:(oh-ih)/2:{padcol_var.get()}")
            if ar_var.get() != "none":
                vf.append(f"setdar={ar_var.get().replace(':','/')}")
            return ["-i", self.input_file.get(), "-vf", ",".join(vf), "-c:a", "copy", out_var.get()]

        self._run_btn(p, build, "▶  Scale / Crop")

    # ─── Subtitles ────────────────────────────────────────────────────────────
    def _page_subs(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Subtitles",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Burn-in Subtitles")
        sub_var  = tk.StringVar()
        out_var  = tk.StringVar()
        row_s = ctk.CTkFrame(sec, fg_color="transparent")
        row_s.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_s, text="Subtitle file (.srt/.ass):", width=170, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_s, textvariable=sub_var, width=240).pack(side="left")
        ctk.CTkButton(row_s, text="Browse", width=70,
                      command=lambda: sub_var.set(filedialog.askopenfilename(
                          filetypes=[("Subtitles","*.srt *.ass *.ssa *.vtt")]))).pack(side="left", padx=4)

        sec2 = self._section(p, "Extract Subtitles from Container")
        ext_sub_var = tk.StringVar(value="subtitles_out.srt")
        stream_var  = tk.StringVar(value="0")
        row_e = ctk.CTkFrame(sec2, fg_color="transparent")
        row_e.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_e, text="Subtitle stream index:", width=160, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_e, textvariable=stream_var, width=50).pack(side="left")
        row_e2 = ctk.CTkFrame(sec2, fg_color="transparent")
        row_e2.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkLabel(row_e2, text="Output file:", width=90, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row_e2, textvariable=ext_sub_var, width=200).pack(side="left")
        ctk.CTkButton(row_e2, text="Extract Now", width=100, fg_color=CARD,
                      border_width=1, border_color=ACCENT, text_color=ACCENT,
                      command=lambda: run_ffmpeg(
                          ["-y","-i",self.input_file.get(),
                           "-map", f"0:s:{stream_var.get()}",
                           ext_sub_var.get()],
                          log_cb=lambda m: None,
                          done_cb=lambda c: messagebox.showinfo("Done","Extracted!" if c==0 else f"Error {c}")
                      )).pack(side="left", padx=6)

        row_out = ctk.CTkFrame(p, fg_color="transparent")
        row_out.pack(fill="x", padx=20, pady=(12,0))
        ctk.CTkEntry(row_out, textvariable=out_var, placeholder_text="output_with_subs.mp4", width=360).pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row_out, text="Browse", width=80, command=lambda: self._pick_output(out_var)).pack(side="left", padx=6)

        def build():
            if not sub_var.get(): messagebox.showwarning("No Subtitle","Pick a subtitle file."); return None
            if not out_var.get(): messagebox.showwarning("No Output","Set output."); return None
            # Escape Windows paths for subtitles filter
            sub_path = sub_var.get().replace("\\", "/").replace(":", "\\:")
            return ["-i", self.input_file.get(),
                    "-vf", f"subtitles='{sub_path}'",
                    "-c:a", "copy", out_var.get()]

        self._run_btn(p, build, "▶  Burn-in Subtitles")

    # ─── Thumbnail ────────────────────────────────────────────────────────────
    def _page_thumb(self):
        p = self._scrollable()
        ctk.CTkLabel(p, text="Thumbnails & Frames",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        sec = self._section(p, "Extract Single Frame")
        ts_var  = tk.StringVar(value="00:00:05")
        out_var = tk.StringVar(value="thumbnail.jpg")
        qv_var  = tk.StringVar(value="2")
        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row, text="Timestamp:", width=90, text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row, textvariable=ts_var, width=120).pack(side="left", padx=4)
        ctk.CTkLabel(row, text="Quality (1-31):", text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row, textvariable=qv_var, width=50).pack(side="left", padx=4)
        row2 = ctk.CTkFrame(sec, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0,12))
        ctk.CTkEntry(row2, textvariable=out_var, placeholder_text="thumbnail.jpg", width=280).pack(side="left")
        ctk.CTkButton(row2, text="Browse", width=70, command=lambda: self._pick_output(out_var, "jpg")).pack(side="left", padx=4)

        sec2 = self._section(p, "Extract Frame Sequence")
        fps2_var = tk.StringVar(value="1")
        pat_var  = tk.StringVar(value="frame_%04d.jpg")
        ctk.CTkLabel(sec2, text="FPS to extract (1 = 1 frame/sec):", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec2, textvariable=fps2_var, width=80).pack(anchor="w", padx=16, pady=(0,4))
        ctk.CTkLabel(sec2, text="Output pattern:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec2, textvariable=pat_var, width=220).pack(anchor="w", padx=16, pady=(0,12))

        sec3 = self._section(p, "Create Video from Images")
        img_glob_var = tk.StringVar(value="frame_%04d.jpg")
        img_fps_var  = tk.StringVar(value="24")
        img_out_var  = tk.StringVar(value="slideshow.mp4")
        ctk.CTkLabel(sec3, text="Image pattern (e.g. frame_%04d.jpg):", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec3, textvariable=img_glob_var, width=280).pack(anchor="w", padx=16, pady=(0,4))
        ctk.CTkLabel(sec3, text="FPS:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec3, textvariable=img_fps_var, width=80).pack(anchor="w", padx=16, pady=(0,4))
        ctk.CTkLabel(sec3, text="Output:", text_color=MUTED).pack(anchor="w", padx=16)
        ctk.CTkEntry(sec3, textvariable=img_out_var, width=280).pack(anchor="w", padx=16, pady=(0,12))

        def build_single():
            if not out_var.get(): messagebox.showwarning("No Output","Set output."); return None
            return ["-ss", ts_var.get(), "-i", self.input_file.get(),
                    "-frames:v", "1", "-q:v", qv_var.get(), out_var.get()]

        def build_seq():
            return ["-i", self.input_file.get(), "-vf", f"fps={fps2_var.get()}", pat_var.get()]

        def build_imgs():
            return ["-framerate", img_fps_var.get(), "-i", img_glob_var.get(),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", img_out_var.get()]

        self._run_btn(p, build_single, "▶  Extract Single Frame")
        ctk.CTkButton(p, text="▶  Extract Frame Sequence", height=38,
                      fg_color=CARD, border_width=1, border_color=ACCENT, text_color=ACCENT, hover_color=BORDER,
                      command=lambda: run_ffmpeg(["-y"]+build_seq(), log_cb=lambda m:None,
                          done_cb=lambda c: messagebox.showinfo("Done","Frames extracted!" if c==0 else f"Error {c}")
                      )).pack(padx=20, pady=4, fill="x")
        ctk.CTkButton(p, text="▶  Images → Video", height=38,
                      fg_color=CARD, border_width=1, border_color=WARNING, text_color=WARNING, hover_color=BORDER,
                      command=lambda: run_ffmpeg(["-y"]+build_imgs(), log_cb=lambda m:None,
                          done_cb=lambda c: messagebox.showinfo("Done","Slideshow created!" if c==0 else f"Error {c}")
                      )).pack(padx=20, pady=4, fill="x")

    # ─── Probe / Info ─────────────────────────────────────────────────────────
    def _page_probe(self):
        p = self.content
        ctk.CTkLabel(p, text="FFprobe -- Media Inspector",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        ctk.CTkButton(p, text="[?] Probe Current File", height=38,
                      fg_color=ACCENT, hover_color="#574fd6",
                      command=self._show_media_info).pack(padx=20, pady=8, fill="x")

        out = ctk.CTkTextbox(p, fg_color="#0a0a10", text_color=TEXT,
                             font=ctk.CTkFont("Courier", 11))
        out.pack(fill="both", expand=True, padx=20, pady=(0,20))

        def probe_now():
            if not self.input_file.get():
                out.insert("end", "Open a file first (use 'Open File' button above).")
                return
            info = probe_file(self.input_file.get())
            if info:
                out.delete("1.0","end")
                out.insert("end", json.dumps(info, indent=2))
            else:
                out.insert("end","Error running ffprobe.")

        probe_now()

    def _show_media_info(self):
        if not self.input_file.get():
            messagebox.showwarning("No File","Open a file first."); return
        info = probe_file(self.input_file.get())
        if not info:
            messagebox.showerror("Error","FFprobe failed."); return
        win = ctk.CTkToplevel(self)
        win.title("Media Info")
        win.geometry("700x500")
        win.configure(fg_color=BG)
        box = ctk.CTkTextbox(win, fg_color="#0a0a10", text_color=TEXT,
                             font=ctk.CTkFont("Courier", 11))
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("end", json.dumps(info, indent=2))

    # ─── Custom Command ───────────────────────────────────────────────────────
    def _page_custom(self):
        p = self.content
        ctk.CTkLabel(p, text="Custom FFmpeg Command",
                     font=ctk.CTkFont("Helvetica", 22, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 4))

        ctk.CTkLabel(p, text="Full command (without 'ffmpeg' at start):",
                     text_color=MUTED).pack(anchor="w", padx=20)
        cmd_box = ctk.CTkTextbox(p, height=80, fg_color=CARD,
                                 font=ctk.CTkFont("Courier", 12), text_color=TEXT)
        cmd_box.pack(fill="x", padx=20, pady=6)
        if self.input_file.get():
            cmd_box.insert("end", f'-i "{self.input_file.get()}" -c copy output.mp4')

        ctk.CTkLabel(p, text="Tip: Use {input} to reference the opened file.",
                     text_color=MUTED, font=ctk.CTkFont("Helvetica",10)).pack(anchor="w", padx=20)

        log_box = ctk.CTkTextbox(p, fg_color="#0a0a10", text_color=MUTED,
                                 font=ctk.CTkFont("Courier", 10))
        log_box.pack(fill="both", expand=True, padx=20, pady=(6,0))

        bar_var = ctk.DoubleVar()
        bar = ctk.CTkProgressBar(p, variable=bar_var, progress_color=SUCCESS, fg_color=CARD)
        bar.pack(fill="x", padx=20, pady=4)

        def run():
            raw = cmd_box.get("1.0","end").strip()
            raw = raw.replace("{input}", self.input_file.get() or "INPUT")
            import shlex
            try:
                args = shlex.split(raw)
            except Exception as e:
                messagebox.showerror("Parse Error", str(e)); return
            log_box.delete("1.0","end")
            bar_var.set(0)

            def log(m): self.after(0, lambda: (log_box.insert("end",m+"\n"), log_box.see("end")))
            def prog(v): self.after(0, lambda: bar_var.set(v))
            def done(c):
                self.after(0, lambda: log("✓ Done!" if c==0 else f"✗ Error {c}"))
                self.after(0, lambda: bar.configure(progress_color=SUCCESS if c==0 else DANGER))

            run_ffmpeg(["-y"] + args, progress_cb=prog, done_cb=done, log_cb=log)

        ctk.CTkButton(p, text="▶  Run Command", height=38,
                      fg_color=ACCENT, hover_color="#574fd6",
                      font=ctk.CTkFont("Helvetica",13,"bold"),
                      command=run).pack(padx=20, pady=8, fill="x")


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    splash = SplashWindow()
    splash.mainloop()
