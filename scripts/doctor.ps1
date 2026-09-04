#Requires -Version 5.1
# bilingual-sub environment check (Windows helper)
$ErrorActionPreference = "Stop"
Write-Host "=== bilingual-sub doctor (PowerShell) ===" -ForegroundColor Cyan
try {
    $ff = ffmpeg -version 2>&1 | Select-Object -First 1
    Write-Host "[OK] ffmpeg: $ff" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] ffmpeg not found. winget install Gyan.FFmpeg" -ForegroundColor Red
    exit 2
}
python -m bilingual_sub.cli.main doctor
exit $LASTEXITCODE
