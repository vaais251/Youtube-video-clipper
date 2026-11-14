[CmdletBinding()]
param([switch]$Update)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$clipToolsDir = Join-Path $PSScriptRoot 'tools'
$clipStaging = Join-Path $clipToolsDir ('.setup-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $clipStaging -Force

function Get-ToolDownload([string]$Url, [string]$Destination) {
    Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 120 -OutFile $Destination
}

function Confirm-ToolHash([string]$File, [string]$Expected) {
    if ($Expected -notmatch '^[0-9a-fA-F]{64}$' -or (Get-FileHash -LiteralPath $File).Hash -ne $Expected) {
        throw "The checksum could not be verified for $([IO.Path]::GetFileName($File))."
    }
}

try {
    $clipDownloader = Join-Path $clipToolsDir 'yt-dlp.exe'
    if ($Update -or -not ((Test-Path -LiteralPath $clipDownloader) -or (Get-Command yt-dlp.exe -ErrorAction SilentlyContinue))) {
        Write-Output 'Downloading yt-dlp from its official GitHub release...'
        $clipLatest = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download'
        $clipNewDownloader = Join-Path $clipStaging 'yt-dlp.exe'
        $clipHashes = Join-Path $clipStaging 'SHA2-256SUMS'
        Get-ToolDownload "$clipLatest/yt-dlp.exe" $clipNewDownloader
        Get-ToolDownload "$clipLatest/SHA2-256SUMS" $clipHashes
        $clipExpected = ''
        foreach ($clipHashLine in Get-Content -LiteralPath $clipHashes) {
            if ($clipHashLine -match '^([0-9a-fA-F]{64})\s+\*?yt-dlp\.exe\s*$') {
                $clipExpected = $Matches[1]
                break
            }
        }
        Confirm-ToolHash $clipNewDownloader $clipExpected
        Move-Item -LiteralPath $clipNewDownloader -Destination $clipDownloader -Force
    }

    $clipFfmpegLocation = Join-Path $clipToolsDir 'ffmpeg-location.txt'
    $clipFfmpegFolder = $clipToolsDir
    if (Test-Path -LiteralPath $clipFfmpegLocation) {
        $clipFfmpegFolder = (Get-Content -LiteralPath $clipFfmpegLocation -Raw).Trim()
    } elseif (-not (Test-Path -LiteralPath (Join-Path $clipToolsDir 'ffmpeg.exe'))) {
        $clipFfmpegPath = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
        if ($clipFfmpegPath) { $clipFfmpegFolder = Split-Path -Parent $clipFfmpegPath.Source }
    }
    if (-not ((Test-Path -LiteralPath (Join-Path $clipFfmpegFolder 'ffmpeg.exe')) -and
              (Test-Path -LiteralPath (Join-Path $clipFfmpegFolder 'ffprobe.exe')))) {
        Write-Output 'Downloading FFmpeg and FFprobe...'
        $clipFfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
        $clipZip = Join-Path $clipStaging 'ffmpeg.zip'
        $clipZipHash = Join-Path $clipStaging 'ffmpeg.sha256'
        Get-ToolDownload $clipFfmpegUrl $clipZip
        Get-ToolDownload "$clipFfmpegUrl.sha256" $clipZipHash
        $clipExpected = ((Get-Content -LiteralPath $clipZipHash -Raw).Trim() -split '\s+')[0]
        Confirm-ToolHash $clipZip $clipExpected
        $clipExpanded = Join-Path $clipStaging 'ffmpeg'
        Expand-Archive -LiteralPath $clipZip -DestinationPath $clipExpanded
        foreach ($clipExe in @('ffmpeg.exe', 'ffprobe.exe')) {
            $clipBinary = Get-ChildItem -LiteralPath $clipExpanded -Recurse -Filter $clipExe -File | Select-Object -First 1
            if (-not $clipBinary) { throw "$clipExe was missing from the FFmpeg archive." }
            Move-Item -LiteralPath $clipBinary.FullName -Destination (Join-Path $clipToolsDir $clipExe) -Force
        }
        if (Test-Path -LiteralPath $clipFfmpegLocation) {
            Remove-Item -LiteralPath $clipFfmpegLocation
        }
    }

    $clipNode = Get-Command node.exe -ErrorAction SilentlyContinue
    $clipDeno = Get-Command deno.exe -ErrorAction SilentlyContinue
    if (-not (($clipNode -and ((& $clipNode.Source --version) -match '^v(2[2-9]|[3-9][0-9]|[0-9]{3,})\.')) -or $clipDeno -or
              (Test-Path -LiteralPath (Join-Path $clipToolsDir 'node.exe')) -or
              (Test-Path -LiteralPath (Join-Path $clipToolsDir 'deno.exe')))) {
        throw 'Install Node.js 22 or newer from https://nodejs.org/, then reopen the app.'
    }
    Write-Output 'Download tools are ready.'
} catch {
    [Console]::Error.WriteLine("Setup could not finish. $($_.Exception.Message)")
    exit 1
} finally {
    $clipResolved = (Resolve-Path -LiteralPath $clipStaging).Path
    $clipParent = (Resolve-Path -LiteralPath $clipToolsDir).Path
    if ((Split-Path -Parent $clipResolved) -eq $clipParent -and (Split-Path -Leaf $clipResolved) -match '^\.setup-[a-f0-9]{32}$') {
        Remove-Item -LiteralPath $clipResolved -Recurse -Force
    }
}
