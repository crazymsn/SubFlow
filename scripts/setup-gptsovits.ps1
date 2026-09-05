# Vendor / refresh official GPT-SoVITS into this repo.
# https://github.com/RVC-Boss/GPT-SoVITS
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$dest = if ($env:SUBFLOW_GPTSOVITS_HOME) { $env:SUBFLOW_GPTSOVITS_HOME } else { Join-Path $Root "third_party\GPT-SoVITS" }
$repo = "https://github.com/RVC-Boss/GPT-SoVITS.git"
$mirror = "https://ghproxy.net/https://github.com/RVC-Boss/GPT-SoVITS.git"
Write-Host "GPT-SoVITS -> $dest"
if (-not (Test-Path (Join-Path $dest "api_v2.py"))) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) { throw "git not found" }
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    $tmp = Join-Path (Split-Path $dest) "GPT-SoVITS-src"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    git clone --depth 1 $repo $tmp
    if ($LASTEXITCODE -ne 0) {
        git clone --depth 1 $mirror $tmp
    }
    if (-not (Test-Path (Join-Path $tmp "api_v2.py"))) {
        throw "clone failed: api_v2.py missing"
    }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Get-ChildItem $tmp | ForEach-Object {
        if ($_.Name -eq "README.md") {
            Copy-Item $_.FullName (Join-Path $dest "README.upstream.md") -Force
        } else {
            Move-Item $_.FullName (Join-Path $dest $_.Name) -Force
        }
    }
    Remove-Item -Recurse -Force $tmp
}
Write-Host "Source ready. Next:"
Write-Host "  1) .\scripts\download-gptsovits-weights.ps1"
Write-Host "  2) or in this folder run official install.ps1 (e.g. .\install.ps1 -Device CPU -Source HF-Mirror)"
Write-Host "  3) .\scripts\install-gptsovits-runtime.ps1 -Python <Python-3.11-path> -Device cuda"
Write-Host "Then start SubFlow. scripts/build-windows.ps1 bundles this runtime and its models beside SubFlow.exe."
