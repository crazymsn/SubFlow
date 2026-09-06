#Requires -Version 5.1
param([switch]$SourceOnly, [switch]$SkipInstall, [string]$DistPath = "dist",
      [string]$OfflinePayload = "", [switch]$HardlinkModels)
# 构建语幕 SubFlow Windows 客户端（onedir）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SkipInstall) {
    python -m pip install -e ".[gui,packaging]"
    if ($LASTEXITCODE -ne 0) { throw "Package installation failed" }
}
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
        throw "Cannot locate the real $Name executable behind the Chocolatey shim."
    }
    return $path
}

$ffmpeg = Resolve-RealExe "ffmpeg"
$probe = Resolve-RealExe "ffprobe"
foreach ($tool in @($ffmpeg, $probe)) {
    if (-not $tool) { throw "FFmpeg and FFprobe are required to build the client. Run scripts/install-windows-ffmpeg.ps1 first." }
    & $tool -version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Media executable failed verification: $tool" }
}
python -m PyInstaller --noconfirm --clean --distpath $DistPath "$Root\packaging\subflow.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Copy-Item $ffmpeg (Join-Path $dist "ffmpeg.exe") -Force
Copy-Item $probe (Join-Path $dist "ffprobe.exe") -Force
Write-Host "Copied ffmpeg from $ffmpeg"

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
if (-not $SourceOnly) {
    $bundleArgs = @("$Root\scripts\bundle-offline.py", (Join-Path $dist "offline"), "--backend", "cuda")
    if ($OfflinePayload) { $bundleArgs += @("--copy-bundle", $OfflinePayload) }
    if ($HardlinkModels) { $bundleArgs += "--hardlink" }
    python @bundleArgs
    if ($LASTEXITCODE -ne 0) { throw "Complete offline voice bundling failed" }
    [System.IO.File]::WriteAllText((Join-Path $dist "offline-required.json"), '{"schema":1}')
    [System.IO.File]::AppendAllText($readme, "`r`n已内置 Qwen 标准音色、Qwen 原声克隆、GPT-SoVITS 模型与 Python 环境。配音无需首次下载。`r`n优先使用 NVIDIA GPU；无可用 GPU 时使用 CPU。请勿删除 offline 文件夹。`r`n")
} elseif (Test-Path (Join-Path $sovits "api_v2.py")) {
    $bundleArgs = @("$Root\scripts\bundle-gptsovits.py", $sovits, $sovitsOut)
    if ($SourceOnly) { $bundleArgs += "--source-only" }
    python @bundleArgs
    if ($LASTEXITCODE -ne 0) { throw "GPT-SoVITS bundling failed" }
} else {
    throw "Missing GPT-SoVITS source: $sovits"
}

Write-Host "Windows client: $dist\SubFlow.exe"
