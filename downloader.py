"""YouTube download and timestamped MP4 export."""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
YT_DLP_DOWNLOAD = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
QUALITIES = {"Best available": None, "Up to 2160p (4K)": 2160,
             "Up to 1080p": 1080, "Up to 720p": 720, "Up to 480p": 480}
WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_DEVICE_NAME = re.compile(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³]", re.IGNORECASE)


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def youtube_url(value):
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return f"https://www.youtube.com/watch?v={value}"
    if "://" not in value:
        value = f"https://{value}"
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError as error:
        raise DownloadError("Enter a YouTube video link.") from error
    path = parts.path.strip("/").split("/")
    video_id = ""
    if parts.scheme in {"https", "http"} and parts.username is None and parts.password is None:
        if host in {"youtu.be", "www.youtu.be"} and len(path) == 1:
            video_id = path[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                      "youtube-nocookie.com", "www.youtube-nocookie.com"}:
            if path == ["watch"]:
                video_id = parse_qs(parts.query).get("v", [""])[0]
            elif len(path) == 2 and path[0] in {"shorts", "live", "embed", "v"}:
                video_id = path[1]
    if not VIDEO_ID.fullmatch(video_id):
        raise DownloadError("Enter a link to one YouTube video, Short, or completed livestream.")
    return f"https://www.youtube.com/watch?v={video_id}"


def seconds(value):
    if not re.fullmatch(r"(?:[0-9]+:){0,2}[0-9]+(?:\.[0-9]{1,3})?", value):
        raise DownloadError(f"Invalid timestamp {value!r}. Use seconds, M:SS, or H:MM:SS.")
    parts = value.split(":")
    try:
        total = Decimal(0)
        for index, part in enumerate(parts):
            number = Decimal(part)
            if index and number >= 60:
                raise DownloadError(f"Invalid timestamp {value!r}. Minutes and seconds after a colon must be under 60.")
            total = total * 60 + number
    except InvalidOperation as error:
        raise DownloadError(f"Invalid timestamp {value!r}.") from error
    return total


def timestamp(value, file_safe=False):
    total = int(Decimal(str(value)) * 1000)
    minutes, remainder = divmod(total, 60_000)
    hours, minutes = divmod(minutes, 60)
    whole, fraction = divmod(remainder, 1000)
    separator = "-" if file_safe else ":"
    clock = separator.join((f"{hours:02}", f"{minutes:02}", f"{whole:02}"))
    return f"{clock}.{fraction:03}" if fraction else clock


@dataclass(frozen=True)
class Clip:
    start: Decimal
    end: Decimal
    name: str | None = None

    @property
    def duration(self):
        return self.end - self.start

    @property
    def label(self):
        return f"{timestamp(self.start)} – {timestamp(self.end)}"


def clip_name(value):
    name = value.strip()
    if name.lower().endswith(".mp4"):
        name = name[:-4].rstrip()
    if not name or name.endswith(".") or INVALID_FILENAME_CHARS.search(name):
        raise DownloadError('Enter a filename without < > : " / \\ | ? * or a trailing period.')
    if WINDOWS_DEVICE_NAME.fullmatch(name.partition(".")[0].rstrip()):
        raise DownloadError(f"{name!r} is reserved by Windows. Choose a different filename.")
    if len(name.encode("utf-16-le")) > 2 * (255 - len(".mp4")):
        raise DownloadError("The filename is too long. Shorten the clip name.")
    return name


def parse_clips(value):
    clips = []
    for line_number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        try:
            time_range, separator, name = line.partition("|")
            parts = re.split(r"\s*[-–—,]\s*", time_range.strip())
            if len(parts) != 2:
                raise DownloadError("Enter one start–end range on this line.")
            start, end = (seconds(part) for part in parts)
            if start >= end:
                raise DownloadError("The end must be after the start.")
            clips.append(Clip(start, end, clip_name(name) if separator else None))
        except DownloadError as error:
            raise DownloadError(f"Line {line_number}: {error}") from error
    return clips


def find_tool(name):
    filename = f"{name}.exe" if os.name == "nt" else name
    local = TOOLS_DIR / filename
    return str(local) if local.is_file() else shutil.which(filename)


def install_ytdlp(source):
    """Install a user-selected release without replacing a tool that already works on failure."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    target = TOOLS_DIR / "yt-dlp.exe"
    with TemporaryDirectory(prefix=".yt-dlp-", dir=TOOLS_DIR) as staging:
        candidate = Path(staging) / target.name
        with source.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise DownloadError("Choose the yt-dlp.exe file from the official Windows release.")
        shutil.copy2(source, candidate)
        try:
            check = subprocess.run([str(candidate), "--ignore-config", "--no-plugin-dirs", "--version"],
                                   capture_output=True, text=True, errors="replace", timeout=30,
                                   creationflags=WINDOW_FLAGS, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DownloadError(f"Windows could not start yt-dlp: {error}") from error
        version = check.stdout.strip()
        if check.returncode or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(?:[.\w+-]*)", version):
            raise DownloadError("This file did not report a yt-dlp version. Select the official yt-dlp.exe release.")
        candidate.replace(target)
    return version


def dependencies():
    configured = TOOLS_DIR / "ffmpeg-location.txt"
    ffmpeg = find_tool("ffmpeg")
    if configured.is_file():
        folder = Path(configured.read_text(encoding="utf-8-sig").strip())
        candidate = folder / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if candidate.is_file():
            ffmpeg = str(candidate.resolve())
    ffprobe = None
    if ffmpeg:
        neighbor = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        ffprobe = str(neighbor) if neighbor.is_file() else None
    dlp = find_tool("yt-dlp")
    if not dlp and find_spec("yt_dlp"):
        python = Path(sys.executable)
        console_python = python.with_name("python.exe")
        if python.name.lower() == "pythonw.exe" and console_python.is_file():
            python = console_python
        dlp = (str(python), "-m", "yt_dlp")
    return {"yt-dlp": dlp, "FFmpeg": ffmpeg,
            "FFprobe": ffprobe, "Node.js 22+ or Deno 2.3+": javascript_runtime()}


def javascript_runtime():
    for name, pattern, minimum in (("node", r"v(\d+)\.(\d+)", (22, 0)),
                                   ("deno", r"deno (\d+)\.(\d+)", (2, 3))):
        runtime = find_tool(name)
        if not runtime:
            continue
        try:
            candidate = subprocess.run([runtime, "--version"], capture_output=True, text=True,
                                       timeout=5, creationflags=WINDOW_FLAGS, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = re.match(pattern, candidate.stdout)
        if version and tuple(map(int, version.groups())) >= minimum:
            return f"{name}:{runtime}"
    return None


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    duration: Decimal

    @property
    def filename(self):
        title = INVALID_FILENAME_CHARS.sub("_", self.title)
        title = title.encode("utf-16-le")[:160].decode("utf-16-le", errors="ignore").strip(" .")
        return f"{title or 'YouTube video'} [{self.id}]"


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=WINDOW_FLAGS, check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()


class Downloader:
    def __init__(self, tools, emit, cancelled):
        missing = [name for name, path in tools.items() if not path]
        if missing:
            raise DownloadError(f"Set up the missing tools first: {', '.join(missing)}.")
        self.dlp = tools["yt-dlp"]
        self.ffmpeg = tools["FFmpeg"]
        self.ffprobe = tools["FFprobe"]
        self.runtime = tools["Node.js 22+ or Deno 2.3+"]
        self.emit = emit
        self.cancelled = cancelled

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def run(self, command, folder, progress_callback=None, timeout=None):
        self.check_cancelled()
        output = deque(maxlen=10)
        with subprocess.Popen(command, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                              creationflags=WINDOW_FLAGS) as process:
            # A silent child can block readline, so observe cancellation separately.
            finished = Event()
            timed_out = Event()

            def watch():
                while not finished.wait(0.15):
                    if self.cancelled.is_set():
                        stop_process(process)
                        return

            watcher = Thread(target=watch, daemon=True)
            watcher.start()
            if timeout is not None:
                from threading import Timer

                def expire():
                    if process.poll() is None:
                        timed_out.set()
                        stop_process(process)

                timer = Timer(timeout, expire)
                timer.daemon = True
                timer.start()
            try:
                for raw in process.stdout:
                    line = raw.strip()
                    if line and not (progress_callback and progress_callback(line)):
                        output.append(line)
                return_code = process.wait()
            finally:
                if timeout is not None:
                    timer.cancel()
                finished.set()
                watcher.join()
        self.check_cancelled()
        if timed_out.is_set():
            raise DownloadError("Loading the video timed out. Check your connection and try again.")
        if return_code != 0:
            errors = [line for line in output if "ERROR:" in line]
            raise DownloadError("\n".join((errors or list(output))[-3:]) or f"Tool exited with code {return_code}.")
        return list(output)

    def yt_command(self):
        executable = [self.dlp] if isinstance(self.dlp, str) else list(self.dlp)
        return executable + ["--ignore-config", "--no-plugin-dirs", "--no-playlist",
                "--encoding", "utf-8", "--socket-timeout", "20", "--retries", "3",
                "--no-js-runtimes", "--js-runtimes", self.runtime,
                "--ffmpeg-location", str(Path(self.ffmpeg).parent)]

    def inspect(self, url):
        result = self.run(self.yt_command() + ["--skip-download", "--ignore-no-formats-error",
                          "--print", "%(.{id,title,duration,live_status})j", "--", url], ROOT, timeout=90)
        data = next((json.loads(line) for line in reversed(result) if line.startswith("{")), None)
        if not data or not VIDEO_ID.fullmatch(data.get("id") or ""):
            raise DownloadError("Could not read the video information.")
        if data.get("live_status") in {"is_live", "is_upcoming", "post_live"} or not data.get("duration"):
            raise DownloadError("This video has no fixed duration yet. Try again once the replay is available.")
        return Video(data["id"], data.get("title") or "YouTube video", Decimal(str(data["duration"])))

    def fetch(self, url, quality, folder, basename, label, clip=None):
        format_sort = "vcodec:h264,acodec:aac,ext:mp4:m4a"
        if quality:
            format_sort = f"res:{quality},{format_sort}"
        else:
            format_sort = f"res,{format_sort}"
        args = self.yt_command() + ["--format", "bv*+ba/b/bv*", "--format-sort", format_sort,
                                    "--merge-output-format", "mp4/mkv", "--remux-video", "mp4",
                                    "--no-simulate", "--progress", "--newline",
                                    "--progress-template", "download:clip-progress %(progress._percent_str)s",
                                    "-o", f"{basename}.%(ext)s"]
        if clip:
            args += ["--download-sections", f"*{clip.start:f}-{clip.end:f}", "--force-keyframes-at-cuts",
                     "--downloader-args", "ffmpeg_o:-c:v libx264 -preset fast -crf 19 -pix_fmt yuv420p "
                     "-c:a aac -b:a 192k -movflags +faststart -f mp4"]

        def show_progress(line):
            if line.startswith("clip-progress "):
                self.emit("status", f"{label}  ·  {line.removeprefix('clip-progress ').strip()}")
                return True
            if line.startswith(("[Merger]", "[VideoRemuxer]")):
                self.emit("status", f"{label}  ·  preparing MP4")
            return False

        self.run(args + ["--", url], folder, show_progress)
        result = folder / f"{basename}.mp4"
        if not clip:
            self.media_duration(result)
        return result

    def media_duration(self, media):
        if not media.is_file() or not media.stat().st_size:
            raise DownloadError("The download did not produce a usable MP4.")
        result = self.run([self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=codec_name:format=duration", "-of", "default=noprint_wrappers=1",
                           media.name], media.parent)
        fields = dict(line.split("=", 1) for line in result if "=" in line)
        try:
            duration = Decimal(fields.get("duration", "0"))
        except InvalidOperation:
            duration = Decimal(0)
        if not fields.get("codec_name") or not duration.is_finite() or duration <= 0:
            raise DownloadError("The MP4 has no readable video stream or duration.")
        return duration

    def cut(self, source, clip, target, label):
        args = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{clip.start:f}",
                "-i", str(source), "-t", f"{clip.duration:f}", "-map", "0:v:0", "-map", "0:a:0?",
                "-map_chapters", "-1", "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", target.name]

        def show_progress(line):
            if line.startswith("out_time_us="):
                value = line.partition("=")[2]
                if value.isdigit():
                    fraction = min(100, int(Decimal(value) / 10_000 / clip.duration))
                    self.emit("status", f"{label}  ·  {fraction}%")
            return "=" in line and line.split("=", 1)[0].replace("_", "").isalnum()

        self.run(args, target.parent, show_progress)

    def publish(self, source, output, stem):
        self.check_cancelled()
        attempt = 1
        encoded_stem = stem.encode("utf-16-le")
        while True:
            suffix = f" ({attempt}).mp4" if attempt > 1 else ".mp4"
            limit = 2 * (255 - len(suffix))
            filename_stem = encoded_stem[:limit].decode("utf-16-le", errors="ignore")
            destination = output / f"{filename_stem}{suffix}"
            try:
                if os.name == "nt":
                    source.rename(destination)
                else:
                    os.link(source, destination)
                    source.unlink()
            except FileExistsError:
                attempt += 1
                continue
            self.emit("file", destination.name)
            return destination

    def export(self, url, video, clips, include_full, quality, output):
        for clip in clips:
            if clip.end > video.duration:
                raise DownloadError(f"{clip.label} ends after the video ({timestamp(video.duration)}).")
        output.mkdir(parents=True, exist_ok=True)
        saved = 0
        failed = 0
        with TemporaryDirectory(prefix=".clip-export-", dir=output) as scratch:
            folder = Path(scratch)
            full = None
            tried_full = include_full
            if include_full:
                try:
                    self.emit("status", "Downloading full video…")
                    full = self.fetch(url, quality, folder, "full", "Full video")
                    full = self.publish(full, output, video.filename)
                    saved += 1
                except (DownloadError, OSError) as error:
                    full = None
                    failed += 1
                    self.emit("log", f"Full video failed. {error}")
            for index, clip in enumerate(clips, 1):
                label = f"Clip {index} of {len(clips)}"
                self.emit("status", f"{label}  ·  {clip.label}")
                basename = f"clip-{index}"
                target = folder / f"{basename}.mp4"
                try:
                    if not full:
                        try:
                            self.fetch(url, quality, folder, basename, label, clip)
                            self.validate_clip(target, clip)
                        except DownloadError as error:
                            if tried_full:
                                raise
                            tried_full = True
                            self.emit("log", f"{label}: direct clipping failed. Trying a temporary full download. {error}")
                            target.unlink(missing_ok=True)
                            self.emit("status", "Downloading a temporary source for the clips…")
                            full = self.fetch(url, quality, folder, "source", "Temporary source")
                    if full:
                        self.cut(full, clip, target, label)
                        self.validate_clip(target, clip)
                    stem = clip.name
                    if stem is None:
                        start = timestamp(clip.start, file_safe=True)
                        end = timestamp(clip.end, file_safe=True)
                        stem = f"{video.filename} - {start} to {end}"
                    self.publish(target, output, stem)
                    saved += 1
                except (DownloadError, OSError) as error:
                    failed += 1
                    self.emit("log", f"{label} ({clip.label}) failed. {error}")
                finally:
                    target.unlink(missing_ok=True)
        return saved, failed

    def validate_clip(self, target, clip):
        if abs(self.media_duration(target) - clip.duration) > Decimal("0.25"):
            raise DownloadError("The clip length did not match the requested range.")
