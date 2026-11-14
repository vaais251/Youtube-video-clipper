# YouTube Clip Downloader

A Windows downloader with a Chrome side panel and a standalone desktop app. Both export a full video, multiple clips, or both as separate MP4s.

## Chrome side panel on Windows

1. Extract this project into a folder you will keep. If you already installed the downloader, extract the update into that same folder so it can reuse the tools there.
2. Double-click **Install Chrome Helper.cmd**. This registers the local downloader for your Windows account without administrator access.
3. Open `chrome://extensions` in Chrome, turn on **Developer mode**, choose **Load unpacked**, and select the project's `chrome-extension` folder. If it is already loaded, use **Reload** on its extension card.
4. Open a YouTube video or Short. Click **YouTube Clip Downloader** in Chrome's Extensions menu to open its side panel. Pin it if you want the icon on the toolbar.
5. Drag the green timeline handles or drag across the track to select a clip. Click the track to seek, use **+** to zoom in, or use **Set start here** and **Set end here** to mark the YouTube playhead. The time fields support milliseconds. Select **Play selection** to preview the cut in the YouTube player.
6. Enter a filename and click **Add clip**. Repeat to queue more clips. Click a queued clip to edit its range or name. Choose quality and **Include full video** as needed, then click **Download MP4s**.

The panel saves MP4s in the project's `downloads` folder. Download progress and filenames appear under **Export activity**. Click **Open folder** to view the files. A batch keeps running if you close the side panel while Chrome stays open. The clip list is saved in Chrome for each video.

If the panel reports missing tools, launch **Start Downloader.cmd**, click **Set up tools**, and then click **Reconnect** in Chrome. If you move this project to a new folder, run **Install Chrome Helper.cmd** from the new folder and load the extension there again. To unregister the helper, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Register-Chrome-Helper.ps1 -Uninstall`. Remove the unpacked extension in `chrome://extensions` when you no longer need it.

## Standalone Windows app

1. Extract the ZIP if you downloaded a copy of the project. Double-click **Start Downloader.cmd**.
2. Click **Set up tools** on the first run if the app shows missing tools. This downloads yt-dlp and FFmpeg to the project folder. Wait for **Download tools ready**.
3. Paste a YouTube link. Click **Load video** if you want to check the title and duration before exporting.
4. Paste one start–end pair per line. Add `|` followed by a name to set that clip's filename. Select **Include the full video** to also save the source, or leave the ranges blank and select it for a full-video-only download.
5. Choose the quality and destination. Click **Export MP4**. **Open output folder** opens the destination directly.

Example batch:

```text
00:26-00:31 | Opening Hook
01:06.500-01:20 | GPU Demo.mp4
00:02:57-00:03:12.250
```

The first two files are saved as `Opening Hook.mp4` and `GPU Demo.mp4`. With just a range, the app uses the YouTube title and timestamps. You can also use plain seconds, such as `26-31`. The end of each range must be within the video's duration. Reusing an existing filename creates a numbered copy, such as `Opening Hook (2).mp4`.

Standard videos, Shorts, and completed livestreams share the same workflow. Availability depends on what YouTube serves to the downloader. YouTube's terms govern downloading and reusing videos. Use the app for material you're permitted to download and use. The app doesn't read browser sign-ins or cookies.

## Quality and download behavior

- The quality selector prefers the highest available resolution up to the chosen setting. The resolution follows the source orientation. The app calls yt-dlp's resolution sorter, which selects the smallest available resolution when all formats are above the target setting.
- Clips are re-encoded with H.264 video and AAC audio when audio is present. Cut accuracy is limited by the source frame rate. The full video preserves the downloaded codecs, which may be VP9 or AV1 at higher resolutions.
- Clip-only jobs try to fetch the selected ranges. If that fails, the app can fetch a temporary full copy once and cut the remaining ranges locally. When the full video is included, the app uses that download for all clips. Allow enough disk space for the source and the finished exports.
- **Cancel** stops the active job. Completed exports remain in the destination. The app removes temporary files when the job exits normally or is cancelled from the app.

## Requirements and manual setup

The launcher needs Python 3.10+ with Tkinter. The download tools need internet access and Node.js 22+ or Deno 2.3+. Windows 10 or later is required for the current official yt-dlp executable.

If in-app setup is unavailable, place `yt-dlp.exe`, `ffmpeg.exe`, and `ffprobe.exe` in a `tools` folder beside `app.pyw`, or add them to your `PATH`. Keep FFmpeg and FFprobe in the same directory. Install Node.js or Deno and reopen the application. Official sources:

- [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases/latest)
- [FFmpeg Windows Essentials ZIP](https://www.gyan.dev/ffmpeg/builds/)
- [Node.js downloads](https://nodejs.org/en/download/)
- [Python for Windows](https://www.python.org/downloads/windows/)

If **yt-dlp** is the only missing tool, use **Get yt-dlp.exe** beside Export activity, then **Select yt-dlp.exe…** and choose the downloaded file. You can also download the [official Windows executable](https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe) and save it directly as `tools\yt-dlp.exe`. On the next **Load video** or **Export MP4**, the app checks for the file again.

If the GitHub download is unavailable and Python 3.11 or newer is installed, you can install yt-dlp through PyPI. Run `py -3 -m pip install --upgrade "yt-dlp[default]"` in PowerShell. **Start Downloader.cmd** uses the same Python launcher and can pick up the installed module.

If previously working YouTube links start failing, close the app and run this in PowerShell from the project folder to refresh yt-dlp:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup-Tools.ps1 -Update
```
