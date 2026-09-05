# Launch the vendored official api_v2.py on 127.0.0.1:9880
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$sovitsHome = if ($env:SUBFLOW_GPTSOVITS_HOME) { $env:SUBFLOW_GPTSOVITS_HOME } else { Join-Path $Root "third_party\GPT-SoVITS" }
if (-not (Test-Path (Join-Path $sovitsHome "api_v2.py"))) {
    $sovitsHome = Join-Path $env:LOCALAPPDATA "SubFlow\GPT-SoVITS"
}
$api = Join-Path $sovitsHome "api_v2.py"
if (-not (Test-Path $api)) {
    throw "api_v2.py not found. Run .\scripts\setup-gptsovits.ps1"
}
$py = $env:SUBFLOW_GPTSOVITS_PYTHON
if (-not $py) {
    foreach ($rel in @("venv\Scripts\python.exe", "runtime\python.exe")) {
        $cand = Join-Path $sovitsHome $rel
        if (Test-Path $cand) { $py = $cand; break }
    }
}
if (-not $py) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $py = "py"; $prefix = @("-3") } else { $py = "python"; $prefix = @() }
} else {
    $prefix = @()
}
$config = Join-Path $sovitsHome "GPT_SoVITS\configs\tts_infer.yaml"
$launch = @($prefix + @("api_v2.py", "-a", "127.0.0.1", "-p", "9880"))
if (Test-Path $config) { $launch += @("-c", $config) }
Write-Host "Starting GPT-SoVITS API at http://127.0.0.1:9880"
Set-Location $sovitsHome
& $py @launch
