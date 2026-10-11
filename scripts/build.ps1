<#
.SYNOPSIS
    One-shot, idempotent build of the portable Windows VideoDownloader folder.

.DESCRIPTION
    Runs the full packaging pipeline end to end:

      1. fetches/verifies the sidecar binaries into vendor/ (fetch_binaries.ps1);
      2. removes any previous output for a reproducible build;
      3. runs PyInstaller against build/vdl.spec (onedir + windowed);
      4. asserts every required artifact exists and that no onefile blob was made;
      5. launches the frozen VideoDownloader.exe --selftest, requires exit 0,
         and validates the emitted selftest.json;
      6. reports the unpacked size of dist/VideoDownloader.

    Idempotent: re-running produces the same artifact; it is safe to run from any
    working directory (all paths are derived from this script's location).

.PARAMETER SkipFetch
    Skip step 1 (use when vendor/ is already populated and you want a faster run).

.PARAMETER SkipSelftest
    Skip steps 5-6 (build + artifact assertions only).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipFetch,
    [switch]$SkipSelftest
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "    $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "    $Message" -ForegroundColor Yellow }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SpecFile = Join-Path $RepoRoot 'build\vdl.spec'
$DistDir = Join-Path $RepoRoot 'dist\VideoDownloader'
$ExePath = Join-Path $DistDir 'VideoDownloader.exe'
$SelftestJson = Join-Path $RepoRoot 'selftest.json'

Push-Location $RepoRoot
try {
    # -- 0. environment ----------------------------------------------------
    $python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw "virtualenv python not found at $python - create .venv and install requirements first"
    }
    Write-Step "Using interpreter: $python"

    # -- 1. sidecar binaries (idempotent) ---------------------------------
    if ($SkipFetch) {
        Write-Warn 'Skipping binary fetch (-SkipFetch)'
    } else {
        Write-Step 'Fetching sidecar binaries'
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $RepoRoot 'build\fetch_binaries.ps1')
        if ($LASTEXITCODE -ne 0) { throw "fetch_binaries.ps1 failed (exit $LASTEXITCODE)" }
    }

    # -- 2. clean previous output (reproducible + idempotent) -------------
    foreach ($dir in @((Join-Path $RepoRoot 'build\VideoDownloader'), $DistDir)) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    }

    # -- 3. PyInstaller (onedir + windowed, via spec) ---------------------
    Write-Step 'Running PyInstaller against build\vdl.spec'
    & $python -m PyInstaller --clean --noconfirm $SpecFile
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

    # -- 4. assert artifacts ----------------------------------------------
    Write-Step 'Verifying build artifacts'
    if (-not (Test-Path $ExePath)) { throw "build finished but $ExePath is missing" }

    $required = @(
        'dist\VideoDownloader\_internal\bin\ffmpeg.exe',
        'dist\VideoDownloader\_internal\bin\ffprobe.exe',
        'dist\VideoDownloader\_internal\bin\deno.exe',
        'dist\VideoDownloader\_internal\libmpv\libmpv-2.dll',
        'dist\VideoDownloader\_internal\yt_dlp_ejs'
    )
    foreach ($rel in $required) {
        $abs = Join-Path $RepoRoot $rel
        if (-not (Test-Path $abs)) { throw "missing required artifact: $rel" }
        Write-Ok $rel
    }

    # Anti-pattern guard: the app EXE must not be a onefile blob. The bundled
    # sidecars (ffmpeg/ffprobe/deno) legitimately exceed 50 MB, so scope the
    # check to the app directory's own top-level exe.
    $appExeSize = (Get-Item $ExePath).Length
    if ($appExeSize -gt 50MB) {
        throw "VideoDownloader.exe is $([Math]::Round($appExeSize/1MB,1)) MB - onefile artifact?"
    }
    # Also assert there is no aggregate EXE sitting at the dist/ root (onefile).
    $distRootExes = Get-ChildItem (Join-Path $RepoRoot 'dist') -Filter *.exe -File -ErrorAction SilentlyContinue
    if ($distRootExes) {
        throw "unexpected EXE at dist/ root (onefile?): $($distRootExes.FullName -join ', ')"
    }

    # -- 5/6. frozen selftest + size report -------------------------------
    if ($SkipSelftest) {
        Write-Warn 'Skipping frozen --selftest (-SkipSelftest)'
    } else {
        Write-Step 'Running frozen VideoDownloader.exe --selftest'
        if (Test-Path $SelftestJson) { Remove-Item -Force $SelftestJson }

        # A GUI-subsystem exe must be waited on explicitly; `&` would not block.
        $proc = Start-Process -FilePath $ExePath -ArgumentList '--selftest' -Wait -PassThru -NoNewWindow
        if (-not (Test-Path $SelftestJson)) {
            throw "selftest did not write $SelftestJson (exit=$($proc.ExitCode))"
        }
        $result = Get-Content -Raw $SelftestJson | ConvertFrom-Json
        if ($proc.ExitCode -ne 0 -or -not $result.ok) {
            throw "selftest failed (exit=$($proc.ExitCode), ok=$($result.ok)):`n$(Get-Content -Raw $SelftestJson)"
        }
        Write-Ok "ffmpeg : $($result.ffmpeg_version)"
        Write-Ok "ffprobe: $($result.ffprobe_version)"
        Write-Ok "deno   : $($result.deno_version)"
        Write-Ok "libmpv : $($result.libmpv_version) (client API $($result.libmpv.client_api_version))"
        Write-Ok "qt     : $($result.qt.qt_version)"

        $size = (Get-ChildItem $DistDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
        Write-Step ("Done - dist\VideoDownloader unpacked size: {0:N1} MB" -f ($size / 1MB))
    }
}
finally {
    Pop-Location
}
