#Requires -Version 5.1
param([switch]$SourceOnly, [switch]$SkipInstall, [string]$DistPath = "dist")
# 构建语幕 SubFlow Windows 客户端（onedir）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SkipInstall) {
    python -m pip install -e ".[gui,packaging]"
    if ($LASTEXITCODE -ne 0) { throw "Package installation failed" }
}
python -m PyInstaller --noconfirm --clean --distpath $DistPath "$Root\packaging\subflow.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$dist = Join-Path $DistPath "SubFlow"

function Resolve-RealExe([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    $path = $cmd.Source
    $desc = (Get-Item $path).VersionInfo.FileDescription
    if ($desc -like "*Chocolatey Shim*") {
        $choco = Join-Path $env:ChocolateyInstall "lib\$Name\tools\$Name\bin\$Name.exe"
        if (-not (Test-Path $choco)) {
            $choco = Join-Path $env:ChocolateyInstall "lib\ffmpeg\tools\ffmpeg\bin\$Name.exe"
        }
        if (Test-Path $choco) { return (Get-Item $choco).FullName }
    }
    return $path
}

$ffmpeg = Resolve-RealExe "ffmpeg"
$probe = Resolve-RealExe "ffprobe"
if ($ffmpeg) {
    Copy-Item $ffmpeg (Join-Path $dist "ffmpeg.exe") -Force
    if ($probe) { Copy-Item $probe (Join-Path $dist "ffprobe.exe") -Force }
    Write-Host "Copied ffmpeg from $ffmpeg"
}

# PyInstaller may hoist a foreign ICU next to python313.dll; Qt6Core then dies with WinError 127.
$internal = Join-Path $dist "_internal"
if (Test-Path $internal) {
    Get-ChildItem $internal -File -Filter "icu*.dll" | Remove-Item -Force
}

$readme = Join-Path $dist "请先读我.txt"
[System.IO.File]::WriteAllText(
    $readme,
    "请从本文件夹启动 SubFlow.exe，不要只复制 exe 到别处。`r`n若仍报 Qt DLL 错误，请安装 Microsoft Visual C++ 2015-2022 Redistributable (x64)。`r`n"
)

$sovits = Join-Path $Root "third_party\GPT-SoVITS"
$sovitsOut = Join-Path $dist "GPT-SoVITS"
if (Test-Path (Join-Path $sovits "api_v2.py")) {
    $bundleArgs = @("$Root\scripts\bundle-gptsovits.py", $sovits, $sovitsOut)
    if ($SourceOnly) { $bundleArgs += "--source-only" }
    python @bundleArgs
    if ($LASTEXITCODE -ne 0) { throw "GPT-SoVITS bundling failed" }
} else {
    throw "Missing GPT-SoVITS source: $sovits"
}

Write-Host "Windows client: $dist\SubFlow.exe"
