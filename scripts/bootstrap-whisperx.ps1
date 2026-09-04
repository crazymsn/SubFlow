# Prepare the SubFlow WhisperX runtime used by the packaged client.
# Default location: %APPDATA%\SubFlow\runtime
$ErrorActionPreference = "Stop"
$dest = Join-Path $env:APPDATA "SubFlow\runtime"
$py = Join-Path $dest "Scripts\python.exe"
Write-Host "WhisperX runtime -> $dest"
if (-not (Test-Path $py)) {
    $hostPy = Get-Command py -ErrorAction SilentlyContinue
    if ($hostPy) {
        & py -3 -m venv $dest
    } else {
        & python -m venv $dest
    }
}
& $py -m pip install -U pip
& $py -m pip install torch openai-whisper whisperx
& $py -c "import whisperx; print('whisperx ok', whisperx.__file__)"
