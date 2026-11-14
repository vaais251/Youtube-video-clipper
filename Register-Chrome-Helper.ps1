[CmdletBinding()]
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$clipHostName = 'com.vaais.youtube_clip_downloader'
$clipRegistryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$clipHostName"
$clipToolDir = Join-Path $PSScriptRoot 'tools'
$clipManifest = Join-Path $clipToolDir "$clipHostName.json"

if ($Uninstall) {
    if (Test-Path -LiteralPath $clipRegistryPath) {
        Remove-Item -LiteralPath $clipRegistryPath
    }
    Write-Host 'The Chrome helper is unregistered.'
    exit
}

if ($PSScriptRoot.Contains('%')) {
    throw 'Move the project to a folder with no percent sign in its path, then retry.'
}

$clipPython = $null
foreach ($clipCandidate in @('py.exe', 'python.exe')) {
    $clipCommand = Get-Command $clipCandidate -ErrorAction SilentlyContinue
    if (-not $clipCommand) { continue }
    $clipArgs = @('-c', 'import sys; assert sys.version_info >= (3, 10); print(sys.executable)')
    if ($clipCandidate -eq 'py.exe') { $clipArgs = @('-3') + $clipArgs }
    $clipFound = & $clipCommand.Source @clipArgs 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $clipFound -PathType Leaf)) {
        $clipPython = $clipFound
        break
    }
}
if (-not $clipPython) { throw 'Install Python 3.10 or newer before registering the Chrome helper.' }
if ($clipPython.Contains('%')) { throw 'Use a Python installation with no percent sign in its path.' }

$clipExtension = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'chrome-extension\manifest.json') -Raw | ConvertFrom-Json
$clipHasher = [Security.Cryptography.SHA256]::Create()
try { $clipHash = $clipHasher.ComputeHash([Convert]::FromBase64String($clipExtension.key)) }
finally { $clipHasher.Dispose() }
$clipHex = [BitConverter]::ToString($clipHash, 0, 16).Replace('-', '')
$clipAlphabet = 'abcdefghijklmnop'
$clipExtensionId = -join ($clipHex.ToCharArray() | ForEach-Object { $clipAlphabet[[Convert]::ToInt32([string]$_, 16)] })

$null = New-Item -ItemType Directory -Path $clipToolDir -Force
$clipLauncher = Join-Path $clipToolDir 'chrome-helper.cmd'
$clipUtf8 = [System.Text.UTF8Encoding]::new($false)
$clipLauncherText = '@echo off' + "`r`n" + 'setlocal' + "`r`n" + 'chcp 65001 >nul' + "`r`n" +
    '"' + $clipPython + '" -u "%~dp0..\chrome-host.py" %*' + "`r`n"
[IO.File]::WriteAllText($clipLauncher, $clipLauncherText, $clipUtf8)
$clipConfig = @{
    name = $clipHostName
    description = 'Windows export helper for YouTube Clip Downloader'
    path = $clipLauncher
    type = 'stdio'
    allowed_origins = @("chrome-extension://$clipExtensionId/")
}
[IO.File]::WriteAllText($clipManifest, ($clipConfig | ConvertTo-Json), $clipUtf8)
try {
    $null = New-Item -Path $clipRegistryPath -Force
    Set-Item -LiteralPath $clipRegistryPath -Value $clipManifest
} catch [System.UnauthorizedAccessException] {
    throw 'Windows denied registration for this process. Run Install Chrome Helper.cmd from File Explorer under your Windows account.'
}

Write-Host 'Chrome helper registered for this Windows account.'
Write-Host "Load this folder at chrome://extensions using Load unpacked:"
Write-Host (Join-Path $PSScriptRoot 'chrome-extension')
