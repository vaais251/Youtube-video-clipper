"""Native messaging entry point for the Chrome extension."""

import json
import os
from pathlib import Path
import struct
import sys
from threading import Event, Lock, Thread

from downloader import (Cancelled, Clip, DownloadError, Downloader, QUALITIES, ROOT, VIDEO_ID,
                        clip_name, dependencies, seconds, youtube_url)


ORIGIN = "chrome-extension://jfgookoafadehmiokegdjnigpdmohfhp/"
OUTPUT = ROOT / "downloads"
MAX_MESSAGE = 1024 * 1024


class Host:
    def __init__(self, source, destination):
        self.source = source
        self.destination = destination
        self.write_lock = Lock()
        self.cancelled = Event()
        self.worker = None

    def read(self):
        header = self.source.read(4)
        if not header:
            return None
        if len(header) != 4:
            raise ValueError("Incomplete message header.")
        size, = struct.unpack("<I", header)
        if not 0 < size <= MAX_MESSAGE:
            raise ValueError("Unsupported message size.")
        payload = self.source.read(size)
        if len(payload) != size:
            raise ValueError("Incomplete message.")
        message = json.loads(payload)
        if not isinstance(message, dict):
            raise ValueError("Expected a message object.")
        return message

    def send(self, **message):
        payload = json.dumps(message, ensure_ascii=True).encode("utf-8")
        with self.write_lock:
            self.destination.write(struct.pack("<I", len(payload)) + payload)
            self.destination.flush()

    def emit(self, kind, message):
        self.send(kind=kind, message=message[:3500])

    def export(self, request):
        try:
            url, clips, include_full, quality = selection(request)
            worker = Downloader(dependencies(), self.emit, self.cancelled)
            self.emit("status", "Checking video availability…")
            video = worker.inspect(url)
            saved, failed = worker.export(url, video, clips, include_full, quality, OUTPUT)
            self.send(kind="result", saved=saved, failed=failed)
        except Cancelled:
            self.emit("cancelled", "Export cancelled. Completed files are still available.")
        except (DownloadError, OSError, ValueError) as error:
            self.emit("error", str(error))

    def handle(self, request):
        operation = request.get("type")
        if operation == "ping":
            tools = dependencies()
            self.send(output=str(OUTPUT), missing=[name for name, path in tools.items() if not path])
        elif operation == "openFolder":
            OUTPUT.mkdir(parents=True, exist_ok=True)
            os.startfile(OUTPUT)
            self.send(output=str(OUTPUT))
        elif operation == "start" and self.worker is None:
            self.worker = Thread(target=self.export, args=(request,))
            self.worker.start()
        elif operation == "cancel":
            self.cancelled.set()

    def serve(self):
        try:
            while (request := self.read()) is not None:
                self.handle(request)
        except (BrokenPipeError, EOFError):
            pass
        except (OSError, ValueError) as error:
            if self.worker:
                self.emit("error", str(error))
            else:
                self.send(error=str(error))
        finally:
            self.cancelled.set()
            if self.worker:
                self.worker.join()


def selection(request):
    video = request.get("videoId")
    quality = request.get("quality")
    include_full = request.get("includeFull")
    ranges = request.get("clips")
    if (not isinstance(video, str) or not isinstance(quality, str) or quality not in QUALITIES
            or type(include_full) is not bool or not isinstance(ranges, list)):
        raise DownloadError("The export selection is invalid.")
    clips = []
    for index, item in enumerate(ranges, 1):
        if not isinstance(item, dict):
            raise DownloadError(f"Clip {index} has an invalid range.")
        start, end, name = item.get("start"), item.get("end"), item.get("name", "")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end
                or len(str(end)) > 12 or not isinstance(name, str)):
            raise DownloadError(f"Clip {index} needs a valid start, end, and filename.")
        try:
            start_seconds = seconds(f"{start // 1000}.{start % 1000:03}")
            end_seconds = seconds(f"{end // 1000}.{end % 1000:03}")
            clips.append(Clip(start_seconds, end_seconds, clip_name(name) if name.strip() else None))
        except DownloadError as error:
            raise DownloadError(f"Clip {index}: {error}") from error
    if not clips and not include_full:
        raise DownloadError("Add a clip or include the full video.")
    if not VIDEO_ID.fullmatch(video):
        raise DownloadError("Open a YouTube video before exporting.")
    return youtube_url(video), clips, include_full, QUALITIES[quality]


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == ORIGIN:
    Host(sys.stdin.buffer, sys.stdout.buffer).serve()
