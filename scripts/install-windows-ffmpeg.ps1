#Requires -Version 5.1
param(
    [ValidateRange(1, 5)][int]$Attempts = 3,
    [ValidateRange(0, 60)][int]$RetryDelaySeconds = 10
)
$ErrorActionPreference = "Stop"
# Inspect native exit codes ourselves so a failed install can be retried.
$PSNativeCommandUseErrorActionPreference = $false

function Test-MediaTools {
    foreach ($name in @("ffmpeg", "ffprobe")) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if (-not $command) { return $false }
        try {
            & $command.Source -version *> $null
            if ($LASTEXITCODE -ne 0) { return $false }
        } catch { return $false }
    }
    return $true
}

if (Test-MediaTools) { return }
for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    Write-Host "Installing FFmpeg ($attempt/$Attempts)"
    & choco install ffmpeg -y --no-progress --execution-timeout=180
    $installExit = $LASTEXITCODE
    # Chocolatey can exit zero after a feed failure and install no packages.
    if (Test-MediaTools) {
        Write-Host "FFmpeg and FFprobe are executable."
        return
    }
    Write-Warning "FFmpeg verification failed after Chocolatey exit $installExit."
    if ($attempt -lt $Attempts) { Start-Sleep -Seconds $RetryDelaySeconds }
}
throw "FFmpeg/FFprobe are unavailable after $Attempts installation attempts."
