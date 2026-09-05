#Requires -Version 5.1
param(
    [string]$Python = "python",
    [ValidateSet("cpu", "cuda")][string]$Device = "cuda",
    [switch]$SkipWeights
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$sovitsHome = if ($env:SUBFLOW_GPTSOVITS_HOME) { $env:SUBFLOW_GPTSOVITS_HOME } else { Join-Path $Root "third_party\GPT-SoVITS" }
if (-not (Test-Path -LiteralPath (Join-Path $sovitsHome "api_v2.py"))) {
    throw "Run scripts/setup-gptsovits.ps1 to prepare the official source first."
}
# The pinned inference stack supports Python 3.11/3.12, not the GUI's 3.13.
& $Python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,12), 'GPT-SoVITS needs Python 3.11 or 3.12'"
if ($LASTEXITCODE -ne 0) { throw "Pass -Python with a Python 3.11/3.12 executable" }
$venv = Join-Path $sovitsHome "venv"
& $Python -m venv $venv
if ($LASTEXITCODE -ne 0) { throw "Cannot create GPT-SoVITS venv" }
$runtimePython = Join-Path $venv "Scripts\python.exe"
$torchIndex = if ($Device -eq "cpu") { "https://download.pytorch.org/whl/cpu" } else { "https://download.pytorch.org/whl/cu124" }
& $runtimePython -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { throw "Torch installation failed" }
& $runtimePython -m pip install -c "$PSScriptRoot\gptsovits-constraints.txt" -r "$PSScriptRoot\gptsovits-inference.txt"
if ($LASTEXITCODE -ne 0) { throw "GPT-SoVITS dependency installation failed" }
& $runtimePython "$PSScriptRoot\prepare-sovits-data.py" (Join-Path $sovitsHome "nltk_data")
if ($LASTEXITCODE -ne 0) { throw "GPT-SoVITS language data installation failed" }
if (-not $SkipWeights) { & "$PSScriptRoot\download-gptsovits-weights.ps1" }
& $Python "$PSScriptRoot\sovits-runtime.py" check
if ($LASTEXITCODE -ne 0) { throw "GPT-SoVITS runtime validation failed" }
Write-Host "GPT-SoVITS runtime ready: $runtimePython"
