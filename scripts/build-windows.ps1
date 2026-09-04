#Requires -Version 5.1
# 构建语幕 SubFlow Windows 客户端（onedir）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install -e ".[gui,packaging]"
python -m PyInstaller --noconfirm --clean "$Root\packaging\subflow.spec"

$dist = Join-Path $Root "dist\SubFlow"

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

Write-Host "Windows client: $dist\SubFlow.exe"
