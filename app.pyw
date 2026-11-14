"""Windows desktop interface for YouTube Clip Downloader."""

from pathlib import Path
from queue import Empty, Queue
import os
import subprocess
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, font, ttk
import webbrowser

from downloader import (Cancelled, DownloadError, Downloader, QUALITIES, ROOT,
                        WINDOW_FLAGS, YT_DLP_DOWNLOAD, dependencies, install_ytdlp,
                        parse_clips, timestamp, youtube_url)


BG, PANEL, LINE = "#101722", "#172233", "#2e3e53"
FG, MUTED, ACCENT, ERROR = "#eef4fc", "#adbdce", "#9eecc9", "#ffb1b3"
DEFAULT_FOLDER = ROOT / "downloads"


class App:
    def __init__(self, window):
        self.window = window
        self.events = Queue()
        self.cancelled = Event()
        self.worker = None
        self.video = None
        self.video_url = None
        self.closing = False
        self.url = tk.StringVar()
        self.quality = tk.StringVar(value="Up to 1080p")
        self.folder = tk.StringVar(value=str(DEFAULT_FOLDER))
        self.include_full = tk.BooleanVar()
        self.video_details = tk.StringVar(value="")
        self.status = tk.StringVar(value="Ready")
        self.tools_status = tk.StringVar()
        self.tools = {}
        self.last_log = None
        self.controls = []
        self.font = "Inter" if "Inter" in font.families(window) else "Segoe UI"
        self.configure_styles()
        self.build()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.after(75, self.drain_events)
        self.window.after(100, self.check_setup)

    def configure_styles(self):
        self.window.title("YouTube Clip Downloader")
        self.window.geometry("1024x635")
        self.window.minsize(880, 590)
        self.window.configure(bg=BG)
        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure("TButton", font=(self.font, 10, "bold"), padding=(12, 7),
                        background=PANEL, foreground=FG, bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL)
        style.map("TButton", background=[("active", LINE)], foreground=[("disabled", "#8391a2")])
        style.configure("Primary.TButton", background=ACCENT, foreground=BG, bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Primary.TButton", background=[("active", "#c5f8e1"), ("disabled", LINE)],
                  foreground=[("disabled", MUTED)])
        style.configure("TEntry", padding=(8, 7), fieldbackground=BG, foreground=FG,
                        bordercolor=LINE, lightcolor=BG, darkcolor=BG, insertcolor=FG)
        style.configure("TCombobox", padding=(7, 6), fieldbackground=BG, background=PANEL, foreground=FG,
                        bordercolor=LINE, lightcolor=BG, darkcolor=BG, arrowcolor=MUTED)
        style.map("TCombobox", fieldbackground=[("readonly", BG)], selectbackground=[("readonly", BG)],
                  selectforeground=[("readonly", FG)], foreground=[("readonly", FG)])
        style.configure("TCheckbutton", background=PANEL, foreground=FG, font=(self.font, 11),
                        indicatorcolor=BG, indicatordiameter=15)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", MUTED)],
                  indicatorcolor=[("selected", ACCENT)])
        style.configure("Horizontal.TProgressbar", troughcolor=BG, background=ACCENT,
                        bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT, thickness=4)
        self.window.option_add("*TCombobox*Listbox.background", BG)
        self.window.option_add("*TCombobox*Listbox.foreground", FG)
        self.window.option_add("*TCombobox*Listbox.selectBackground", LINE)

    def label(self, parent, *, text=None, var=None, size=11, bold=False, color=FG, bg=PANEL, **options):
        return tk.Label(parent, text=text, textvariable=var, bg=bg, fg=color, anchor="w", justify="left",
                        font=(self.font, size, "bold" if bold else "normal"), **options)

    def button(self, parent, text, command, primary=False, lock=True):
        button = ttk.Button(parent, text=text, command=command,
                            style="Primary.TButton" if primary else "TButton")
        if lock:
            self.controls.append(button)
        return button

    def text_box(self, parent, height):
        return tk.Text(parent, height=height, width=1, wrap="word", bg=BG, fg=FG, insertbackground=FG,
                       selectbackground=LINE, relief="flat", padx=10, pady=8, highlightthickness=1,
                       highlightbackground=LINE, highlightcolor=ACCENT, undo=True,
                       font=("Cascadia Mono", 11))

    def build(self):
        page = tk.Frame(self.window, bg=BG, padx=28, pady=22)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=3, uniform="columns")
        page.columnconfigure(1, weight=2, uniform="columns")
        page.rowconfigure(1, weight=1)

        self.label(page, text="YouTube Clip Downloader", size=24, bold=True, bg=BG).grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        editor = tk.Frame(page, bg=PANEL, padx=18, pady=15, highlightthickness=1, highlightbackground=LINE)
        editor.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(5, weight=1)

        self.label(editor, text="YouTube link", bold=True).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        link_row = tk.Frame(editor, bg=PANEL)
        link_row.grid(row=1, column=0, sticky="ew")
        link_row.columnconfigure(0, weight=1)
        url_field = ttk.Entry(link_row, textvariable=self.url, font=(self.font, 11))
        url_field.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.controls.append(url_field)
        self.button(link_row, "Load video", self.load_video).grid(row=0, column=1)
        url_field.bind("<Return>", lambda event: self.load_video())
        url_field.focus_set()
        self.url.trace_add("write", self.clear_video)
        details = self.label(editor, var=self.video_details, color=ACCENT, wraplength=470)
        details.grid(row=2, column=0, sticky="ew", pady=(4, 5))
        editor.bind("<Configure>", lambda event: details.configure(wraplength=max(180, event.width - 40)))

        self.label(editor, text="Clip ranges", bold=True).grid(row=3, column=0, sticky="ew")
        self.label(editor, text="One per line. Add | and a name to set the filename.\n00:26–00:31 | Opening Hook",
                   color=MUTED, size=10, wraplength=370).grid(row=4, column=0, sticky="ew", pady=(2, 5))
        clip_area = tk.Frame(editor, bg=PANEL)
        clip_area.grid(row=5, column=0, sticky="nsew", pady=(0, 9))
        self.clip_box = self.text_box(clip_area, 5)
        clip_scroll = ttk.Scrollbar(clip_area, command=self.clip_box.yview)
        self.clip_box.configure(yscrollcommand=clip_scroll.set)
        clip_scroll.pack(side="right", fill="y")
        self.clip_box.pack(side="left", fill="both", expand=True)
        self.full_checkbox = ttk.Checkbutton(editor, text="Include the full video", variable=self.include_full)
        self.full_checkbox.grid(row=6, column=0, sticky="w", pady=(0, 7))
        self.controls.append(self.full_checkbox)

        quality_row = tk.Frame(editor, bg=PANEL)
        quality_row.grid(row=7, column=0, sticky="ew", pady=(0, 9))
        self.label(quality_row, text="Quality", bold=True).pack(side="left", padx=(0, 10))
        combo = ttk.Combobox(quality_row, textvariable=self.quality, values=list(QUALITIES),
                             state="readonly", width=20, font=(self.font, 11))
        combo.pack(side="left")
        self.controls.append(combo)

        self.label(editor, text="Save MP4s to", bold=True).grid(row=8, column=0, sticky="ew", pady=(0, 5))
        destination = tk.Frame(editor, bg=PANEL)
        destination.grid(row=9, column=0, sticky="ew", pady=(0, 13))
        destination.columnconfigure(0, weight=1)
        folder_field = ttk.Entry(destination, textvariable=self.folder, font=(self.font, 10))
        folder_field.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.controls.append(folder_field)
        self.button(destination, "Browse…", self.choose_folder).grid(row=0, column=1)

        actions = tk.Frame(editor, bg=PANEL)
        actions.grid(row=10, column=0, sticky="ew")
        self.button(actions, "Export MP4", self.export, primary=True).pack(side="left", padx=(0, 7))
        self.stop = self.button(actions, "Cancel", self.cancel, lock=False)
        self.stop.state(["disabled"])
        self.stop.pack(side="left")

        activity = tk.Frame(page, bg=PANEL, padx=18, pady=15, highlightthickness=1, highlightbackground=LINE)
        activity.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(6, weight=1)
        self.label(activity, text="Export activity", size=15, bold=True).grid(row=0, column=0, sticky="ew")
        status = self.label(activity, var=self.status, color=MUTED, wraplength=300)
        status.grid(row=1, column=0, sticky="ew", pady=(7, 8))
        activity.bind("<Configure>", lambda event: status.configure(wraplength=max(180, event.width - 40)))
        self.progress = ttk.Progressbar(activity, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 11))
        log_area = tk.Frame(activity, bg=PANEL)
        log_area.grid(row=6, column=0, sticky="nsew", pady=(9, 11))
        self.log = self.text_box(log_area, 9)
        log_scroll = ttk.Scrollbar(log_area, command=self.log.yview)
        self.log.configure(state="disabled", cursor="arrow", undo=False, yscrollcommand=log_scroll.set)
        self.log.tag_configure("file", foreground=ACCENT)
        self.log.tag_configure("error", foreground=ERROR)
        log_scroll.pack(side="right", fill="y")
        self.log.pack(side="left", expand=True, fill="both")
        self.tools_label = self.label(activity, var=self.tools_status, color=MUTED, size=10, wraplength=290)
        self.tools_label.grid(row=3, column=0, sticky="ew", pady=(0, 5))
        tool_actions = tk.Frame(activity, bg=PANEL)
        tool_actions.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        self.button(tool_actions, "Set up tools", self.setup).pack(side="left")
        self.manual_tools = tk.Frame(activity, bg=PANEL)
        self.manual_tools.grid(row=5, column=0, sticky="ew")
        self.button(self.manual_tools, "Get yt-dlp.exe", self.open_ytdlp_download).pack(side="left", padx=(0, 7))
        self.button(self.manual_tools, "Select yt-dlp.exe…", self.choose_ytdlp).pack(side="left")
        self.manual_tools.grid_remove()
        self.button(activity, "Open output folder", self.open_folder, lock=False).grid(row=7, column=0, sticky="w")

    def add_log(self, message, tag=""):
        if (message, tag) == self.last_log:
            return
        self.last_log = message, tag
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def check_setup(self):
        try:
            self.tools = dependencies()
            missing = [name for name, path in self.tools.items() if not path]
            self.tools_status.set("Needed: " + ", ".join(missing) if missing else "Download tools ready")
            self.tools_label.configure(fg=MUTED if missing else ACCENT)
            if self.tools["yt-dlp"]:
                self.manual_tools.grid_remove()
            else:
                self.manual_tools.grid()
        except (OSError, subprocess.SubprocessError) as error:
            self.tools = {}
            self.tools_status.set("Could not check download tools")
            self.add_log(str(error), "error")

    def tools_ready(self):
        self.check_setup()
        if self.tools and all(self.tools.values()):
            return True
        self.status.set("Download tools need setup")
        if not self.tools.get("yt-dlp"):
            message = "yt-dlp is missing. Click Set up tools, or get and select the official yt-dlp.exe below."
        else:
            message = "Click Set up tools to install the missing download tools."
        self.add_log(message, "error")
        return False

    def setup(self):
        missing_ytdlp = not self.tools.get("yt-dlp")

        def task(emit):
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(ROOT / "Setup-Tools.ps1")], cwd=ROOT, text=True, encoding="utf-8",
                                    errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    creationflags=WINDOW_FLAGS, check=False)
            emit("setup", None)
            if result.returncode:
                detail = result.stdout.strip() or "Setup failed. See README.md for manual setup."
                if missing_ytdlp:
                    detail += "\nUse Get yt-dlp.exe and Select yt-dlp.exe to install it manually."
                raise DownloadError(detail)
            emit("status", "Setup finished. Check the tool status below.")

        self.start(task, "Setting up download tools…", can_cancel=False)

    def open_ytdlp_download(self):
        if not webbrowser.open(YT_DLP_DOWNLOAD):
            self.add_log("Open the official Windows download in your browser:\n" + YT_DLP_DOWNLOAD)

    def choose_ytdlp(self):
        selected = filedialog.askopenfilename(title="Select the official yt-dlp.exe",
                                             filetypes=[("Windows executable", "*.exe")])
        if not selected:
            return

        def task(emit):
            version = install_ytdlp(Path(selected))
            emit("setup", None)
            emit("status", f"yt-dlp {version} installed")

        self.start(task, "Installing the selected yt-dlp…", can_cancel=False)

    def clear_video(self, *_):
        self.video = None
        self.video_url = None
        self.video_details.set("")

    def choose_folder(self):
        selected = filedialog.askdirectory(initialdir=self.folder.get())
        if selected:
            self.folder.set(selected)

    def output_folder(self):
        value = self.folder.get().strip().strip('"')
        if not value:
            raise DownloadError("Choose where to save the MP4 files.")
        return Path(value).expanduser().resolve()

    def open_folder(self):
        try:
            path = self.output_folder()
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except (DownloadError, ValueError, OSError) as error:
            self.add_log(str(error), "error")

    def start(self, task, message, can_cancel=True):
        if self.worker:
            return
        self.cancelled.clear()
        self.can_cancel = can_cancel
        self.status.set(message)
        self.progress.start(12)
        for control in self.controls:
            control.state(["disabled"])
        self.clip_box.configure(state="disabled")
        self.stop.state(["!disabled"] if can_cancel else ["disabled"])

        def emit(kind, payload):
            self.events.put((kind, payload))

        def run():
            try:
                task(emit)
            except Cancelled:
                emit("status", "Cancelled. Completed files are still available.")
            except Exception as error:
                emit("error", str(error))
            finally:
                emit("finished", None)

        self.worker = Thread(target=run, daemon=True)
        self.worker.start()

    def load_video(self):
        if self.worker:
            return
        try:
            url = youtube_url(self.url.get())
        except DownloadError as error:
            self.add_log(str(error), "error")
            return
        if not self.tools_ready():
            return

        def task(emit):
            downloader = Downloader(tools, emit, self.cancelled)
            emit("video", (url, downloader.inspect(url)))
            emit("status", "Video loaded")

        tools = self.tools
        self.start(task, "Loading video details…")

    def export(self):
        if self.worker:
            return
        try:
            url = youtube_url(self.url.get())
            clips = parse_clips(self.clip_box.get("1.0", "end"))
            include_full = self.include_full.get()
            if not clips and not include_full:
                raise DownloadError("Enter at least one clip range or select Include the full video.")
            folder = self.output_folder()
            quality = QUALITIES[self.quality.get()]
        except (DownloadError, ValueError, OSError) as error:
            self.add_log(str(error), "error")
            return
        if not self.tools_ready():
            return
        video = self.video if self.video_url == url else None
        tools = self.tools

        def task(emit):
            downloader = Downloader(tools, emit, self.cancelled)
            info = video or downloader.inspect(url)
            emit("video", (url, info))
            saved, failed = downloader.export(url, info, clips, include_full, quality, folder)
            summary = f"{saved} MP4 {'saved' if saved == 1 else 'files saved'}"
            if failed:
                summary += f"  ·  {failed} failed"
            emit("status", summary)

        self.start(task, "Preparing export…")

    def cancel(self):
        self.cancelled.set()
        self.stop.state(["disabled"])
        self.status.set("Cancelling…")

    def close(self):
        if self.worker:
            self.closing = True
            if self.can_cancel:
                self.cancel()
        else:
            self.window.destroy()

    def drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "video":
                    self.video_url, self.video = payload
                    title = self.video.title
                    if len(title) > 160:
                        title = title[:157].rstrip() + "…"
                    self.video_details.set(f"{title}  ·  {timestamp(self.video.duration)}")
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "file":
                    self.add_log(payload, "file")
                elif kind == "log":
                    self.add_log(payload)
                elif kind == "error":
                    self.status.set("Could not finish")
                    self.add_log(payload, "error")
                elif kind == "setup":
                    self.check_setup()
                elif kind == "finished":
                    self.worker = None
                    if self.closing:
                        self.window.destroy()
                        return
                    self.progress.stop()
                    for control in self.controls:
                        control.state(["!disabled"])
                    self.clip_box.configure(state="normal")
                    self.stop.state(["disabled"])
        except Empty:
            pass
        self.window.after(75, self.drain_events)


if __name__ == "__main__":
    window = tk.Tk()
    App(window)
    window.mainloop()
