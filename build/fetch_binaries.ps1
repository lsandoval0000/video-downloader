<#
.SYNOPSIS
    Acquire and verify the sidecar binaries the VideoDownloader app bundles.

.DESCRIPTION
    Downloads and extracts, into the repository's ``vendor/`` folder:

      vendor/bin/ffmpeg.exe        (yt-dlp/FFmpeg-Builds static GPL build)
      vendor/bin/ffprobe.exe       (same archive)
      vendor/bin/deno.exe          (denoland/deno release, >= 2.3.0)
      vendor/libmpv/libmpv-2.dll   (shinchiro/mpv-winbuild-cmake, NON-v3 x86_64)

    The script is idempotent: a binary that is already present (and passes a
    lightweight validity check) is skipped unless ``-Force`` is given. Where the
    upstream project publishes a ``checksums.sha256`` file the download is
    checksum-verified; where it does not (libmpv) the SHA-256 is recorded and a
    PE-header sanity check is applied instead. Finally the resolved versions are
    printed.

    Layout MUST stay consistent with ``src/vdl/paths.py`` (leaf 1.2):
    ``vendor/bin/*`` and ``vendor/libmpv/libmpv-2.dll`` in dev, which the
    PyInstaller spec (leaf 7.2) mirrors into ``_internal/bin/*`` and
    ``_internal/libmpv/libmpv-2.dll``.

.NOTES
    Windows PowerShell 5.1+ / PowerShell 7+. Requires network access at build
    time. ``.7z`` extraction needs ``7z``; if it is absent the script falls back
    to ``tar`` (libarchive reads 7-Zip), then ``winget install 7zip.7zip``, then
    the Python ``py7zr`` package.
#>

[CmdletBinding()]
param(
    # Re-download and re-extract even if the binaries already exist.
    [switch]$Force,

    # Override the output directory (defaults to <repo>/vendor).
    [string]$VendorDir
)

$ErrorActionPreference = 'Stop'
# The PowerShell progress bar makes Invoke-WebRequest dramatically slower.
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $VendorDir) { $VendorDir = Join-Path $RepoRoot 'vendor' }

$BinDir = Join-Path $VendorDir 'bin'
$LibmpvDir = Join-Path $VendorDir 'libmpv'
$CacheDir = Join-Path $VendorDir '.cache'
New-Item -ItemType Directory -Force -Path $BinDir, $LibmpvDir, $CacheDir | Out-Null

$UserAgent = 'vdl-fetch-binaries'

# Minimum acceptable deno version (yt-dlp JS-challenge runtime requirement).
$MinDeno = [version]'2.3.0'

# ─────────────────────────────── helpers ────────────────────────────────

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "    $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "    $Message" -ForegroundColor Yellow }

function Get-VenvPython {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    return 'python'
}

# Fetch a URL and return its body as text (works on PS 5.1 and PS 7 where the
# content may come back as bytes for binary-ish content types).
function Get-RemoteText {
    param([string]$Url)
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -Headers @{ 'User-Agent' = $UserAgent } -TimeoutSec 60
    if ($resp.Content -is [byte[]]) { return [System.Text.Encoding]::UTF8.GetString($resp.Content) }
    return [string]$resp.Content
}

function Get-RemoteJson {
    param([string]$Url)
    return Invoke-RestMethod -Uri $Url -Headers @{ 'User-Agent' = $UserAgent } -TimeoutSec 60
}

function Save-Download {
    param([string]$Url, [string]$Destination)
    Write-Host "    downloading $(Split-Path -Leaf $Destination)"
    Invoke-WebRequest -Uri $Url -UseBasicParsing -Headers @{ 'User-Agent' = $UserAgent } -OutFile $Destination -TimeoutSec 0
}

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

# Parse an expected hash for a file name out of a checksums file. Handles both
# the GNU ``<hash>  <file>`` format and PowerShell's ``Get-FileHash`` listing
# (``Hash : <hash>``), which deno publishes.
function Get-ExpectedHash {
    param([string]$ChecksumFile, [string]$FileName)
    if (-not (Test-Path $ChecksumFile)) { return $null }
    $text = Get-Content -Raw -Path $ChecksumFile
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match '^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
            if ((Split-Path -Leaf $Matches[2]) -eq $FileName) { return $Matches[1] }
        }
    }
    if ($text -match '(?im)^\s*Hash\s*:\s*([0-9a-fA-F]{64})') { return $Matches[1] }
    return $null
}

function Assert-Checksum {
    param([string]$Path, [string]$Expected)
    if (-not $Expected) {
        Write-Warn "no published checksum for $(Split-Path -Leaf $Path); recording local hash"
        return
    }
    $actual = Get-Sha256 $Path
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "checksum mismatch for $Path`n  expected: $Expected`n  actual:   $actual"
    }
    Write-Ok "checksum OK ($(Split-Path -Leaf $Path))"
}

# A PE binary on Windows starts with the "MZ" DOS magic.
function Test-PeBinary {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    if ((Get-Item $Path).Length -lt 64KB) { return $false }
    $bytes = [System.IO.File]::ReadAllBytes($Path)[0..1]
    return ($bytes[0] -eq 0x4D -and $bytes[1] -eq 0x5A)  # 'MZ'
}

function Expand-ZipArchive {
    param([string]$Zip, [string]$Destination)
    if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
    Expand-Archive -Path $Zip -DestinationPath $Destination -Force
}

function Find-7z {
    foreach ($name in @('7z', '7za', '7zr')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    foreach ($p in @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe")) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}

function Expand-7zArchive {
    param([string]$Archive, [string]$Destination)
    if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $sevenZip = Find-7z
    if ($sevenZip) {
        Write-Ok "extracting with $sevenZip"
        & $sevenZip x $Archive "-o$Destination" -y | Out-Null
        return
    }

    # Windows' bundled tar is bsdtar (libarchive) and reads 7-Zip archives.
    $tar = Get-Command tar -ErrorAction SilentlyContinue
    if ($tar) {
        try {
            Write-Ok "extracting with tar (libarchive)"
            & $tar.Source -xf $Archive -C $Destination 2>$null
            if ($LASTEXITCODE -eq 0) { return }
            Write-Warn "tar could not read the 7-Zip archive"
        } catch {
            Write-Warn "tar extraction failed: $_"
        }
    }

    # Last resort: install 7-Zip, else use the Python py7zr package.
    Write-Warn "7z not found; trying 'winget install 7zip.7zip'"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & $winget.Source install --id 7zip.7zip -e --silent `
                --accept-source-agreements --accept-package-agreements | Out-Null
        } catch { Write-Warn "winget install failed: $_" }
        $sevenZip = Find-7z
        if ($sevenZip) {
            & $sevenZip x $Archive "-o$Destination" -y | Out-Null
            return
        }
    }

    $python = Get-VenvPython
    Write-Warn "falling back to py7zr via $python"
    & $python -m pip install --quiet py7zr
    & $python -c "import sys, py7zr; py7zr.SevenZipFile(sys.argv[1]).extractall(sys.argv[2])" $Archive $Destination
    if ($LASTEXITCODE -ne 0) { throw "py7zr extraction failed for $Archive" }
}

function Copy-FirstMatch {
    param([string]$Root, [string]$Filter, [string]$Destination)
    $found = Get-ChildItem -Path $Root -Recurse -File -Filter $Filter | Select-Object -First 1
    if (-not $found) { throw "could not find '$Filter' inside extracted archive under $Root" }
    Copy-Item -Path $found.FullName -Destination $Destination -Force
    return $found.FullName
}

# ───────────────────────────── ffmpeg/ffprobe ───────────────────────────

function Fetch-Ffmpeg {
    param([switch]$Force)
    $ffmpeg = Join-Path $BinDir 'ffmpeg.exe'
    $ffprobe = Join-Path $BinDir 'ffprobe.exe'
    if (-not $Force -and (Test-PeBinary $ffmpeg) -and (Test-PeBinary $ffprobe)) {
        Write-Ok 'ffmpeg/ffprobe already present; skipping (use -Force to refetch)'
        return
    }

    $zipName = 'ffmpeg-master-latest-win64-gpl.zip'
    $zip = Join-Path $CacheDir $zipName
    $base = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest'
    if ($Force -or -not (Test-Path $zip)) { Save-Download "$base/$zipName" $zip }

    $sums = Join-Path $CacheDir 'ffmpeg-checksums.sha256'
    try {
        $text = Get-RemoteText "$base/checksums.sha256"
        Set-Content -Path $sums -Value $text -Encoding ASCII
    } catch { Write-Warn "could not fetch ffmpeg checksums.sha256: $_" }
    Assert-Checksum $zip (Get-ExpectedHash $sums $zipName)

    $tmp = Join-Path $CacheDir 'ffmpeg-extract'
    Expand-ZipArchive $zip $tmp
    Copy-FirstMatch $tmp 'ffmpeg.exe'  $ffmpeg  | Out-Null
    Copy-FirstMatch $tmp 'ffprobe.exe' $ffprobe | Out-Null
    Remove-Item -Recurse -Force $tmp
    if (-not (Test-PeBinary $ffmpeg)) { throw "ffmpeg.exe is not a valid PE binary" }
    if (-not (Test-PeBinary $ffprobe)) { throw "ffprobe.exe is not a valid PE binary" }
}

# ──────────────────────────────── libmpv ────────────────────────────────

function Fetch-Libmpv {
    param([switch]$Force)
    $dll = Join-Path $LibmpvDir 'libmpv-2.dll'
    if (-not $Force -and (Test-PeBinary $dll)) {
        Write-Ok 'libmpv-2.dll already present; skipping (use -Force to refetch)'
        return
    }

    Write-Step 'Resolving latest shinchiro mpv-dev (non-v3, x86_64)'
    $release = Get-RemoteJson 'https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest'
    # NON-v3 build for broadest CPU compatibility (the v3 build needs AVX2).
    $asset = $release.assets |
        Where-Object { $_.name -match '^mpv-dev-x86_64-\d' -and $_.name -notmatch 'v3' -and $_.name -like '*.7z' } |
        Select-Object -First 1
    if (-not $asset) { throw 'no non-v3 mpv-dev x86_64 .7z asset found in the latest release' }

    $archive = Join-Path $CacheDir $asset.name
    if ($Force -or -not (Test-Path $archive)) { Save-Download $asset.browser_download_url $archive }

    # shinchiro does not publish a checksums file; record the local hash instead.
    $sumAsset = $release.assets | Where-Object { $_.name -match '(?i)checksum|sha256' } | Select-Object -First 1
    if ($sumAsset) {
        $sums = Join-Path $CacheDir 'mpv-checksums.sha256'
        try {
            $text = Get-RemoteText $sumAsset.browser_download_url
            Set-Content -Path $sums -Value $text -Encoding ASCII
        } catch { Write-Warn "could not fetch mpv checksums: $_" }
        Assert-Checksum $archive (Get-ExpectedHash $sums $asset.name)
    } else {
        Write-Warn "upstream publishes no checksum for libmpv; recording local SHA-256"
        Write-Ok ("sha256 " + (Get-Sha256 $archive) + "  " + $asset.name)
    }

    $tmp = Join-Path $CacheDir 'mpv-extract'
    Expand-7zArchive $archive $tmp
    Copy-FirstMatch $tmp 'libmpv-2.dll' $dll | Out-Null
    Remove-Item -Recurse -Force $tmp
    if (-not (Test-PeBinary $dll)) { throw "libmpv-2.dll is not a valid PE binary" }
}

# ───────────────────────────────── deno ─────────────────────────────────

function Fetch-Deno {
    param([switch]$Force)
    $exe = Join-Path $BinDir 'deno.exe'
    if (-not $Force -and (Test-PeBinary $exe)) {
        Write-Ok 'deno.exe already present; skipping (use -Force to refetch)'
        return
    }

    Write-Step 'Resolving latest deno release'
    $release = Get-RemoteJson 'https://api.github.com/repos/denoland/deno/releases/latest'
    $assetName = 'deno-x86_64-pc-windows-msvc.zip'   # the `deno` binary, NOT denort
    $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
    if (-not $asset) { throw "deno asset '$assetName' not found in release $($release.tag_name)" }

    $zip = Join-Path $CacheDir $assetName
    if ($Force -or -not (Test-Path $zip)) { Save-Download $asset.browser_download_url $zip }

    $sumAsset = $release.assets | Where-Object { $_.name -eq "$assetName.sha256sum" } | Select-Object -First 1
    if ($sumAsset) {
        $sums = Join-Path $CacheDir 'deno-checksums.sha256'
        try {
            $text = Get-RemoteText $sumAsset.browser_download_url
            Set-Content -Path $sums -Value $text -Encoding ASCII
        } catch { Write-Warn "could not fetch deno checksum: $_" }
        Assert-Checksum $zip (Get-ExpectedHash $sums $assetName)
    }

    $tmp = Join-Path $CacheDir 'deno-extract'
    Expand-ZipArchive $zip $tmp
    Copy-FirstMatch $tmp 'deno.exe' $exe | Out-Null
    Remove-Item -Recurse -Force $tmp
    if (-not (Test-PeBinary $exe)) { throw "deno.exe is not a valid PE binary" }
}

# ─────────────────────────── resolved versions ──────────────────────────

function Get-ExeVersionLine {
    param([string]$Exe, [string[]]$Arguments)
    try {
        $line = & $Exe @Arguments 2>&1 | Select-Object -First 1
        return ($line -as [string]).Trim()
    } catch { return "(failed: $_)" }
}

function Show-ResolvedVersions {
    Write-Step 'Resolved versions'
    $ffmpeg = Join-Path $BinDir 'ffmpeg.exe'
    $ffprobe = Join-Path $BinDir 'ffprobe.exe'
    $deno = Join-Path $BinDir 'deno.exe'
    $dll = Join-Path $LibmpvDir 'libmpv-2.dll'

    if (Test-Path $ffmpeg) { Write-Ok ("ffmpeg : " + (Get-ExeVersionLine $ffmpeg @('-version'))) }
    if (Test-Path $ffprobe) { Write-Ok ("ffprobe: " + (Get-ExeVersionLine $ffprobe @('-version'))) }
    if (Test-Path $deno) { Write-Ok ("deno   : " + (Get-ExeVersionLine $deno @('--version'))) }
    if (Test-Path $dll) {
        $ver = (Get-Item $dll).VersionInfo.FileVersion
        if (-not $ver) { $ver = '(no version resource)' }
        Write-Ok ("libmpv : $ver  [$dll]")
    }

    # deno minimum-version gate.
    if (Test-Path $deno) {
        $line = Get-ExeVersionLine $deno @('--version')
        if ($line -match '(\d+\.\d+\.\d+)') {
            $found = [version]$Matches[1]
            if ($found -lt $MinDeno) { throw "deno $found is below the required minimum $MinDeno" }
            Write-Ok "deno version $found >= required $MinDeno"
        }
    }
}

# ───────────────────────────────── main ─────────────────────────────────

Write-Step "Fetching sidecar binaries into $VendorDir"
Fetch-Ffmpeg -Force:$Force
Fetch-Libmpv -Force:$Force
Fetch-Deno   -Force:$Force
Show-ResolvedVersions
Write-Step 'Done'
