#Requires -Version 5.1
param(
    [Parameter(Mandatory=$true)][ValidateSet("asr", "gptsovits", "whisperx")][string]$Kind,
    [string]$Python = "python",
    [ValidateSet("auto", "cpu", "cuda", "mps")][string]$Device = "auto",
    [switch]$SkipModels
)
$ErrorActionPreference = "Stop"
$prepareArgs = @((Join-Path $PSScriptRoot "prepare-runtime.py"), $Kind)
if ($Device -ne "auto") { $prepareArgs += @("--backend", $Device) }
if ($SkipModels) { $prepareArgs += "--skip-models" }
& $Python @prepareArgs
if ($LASTEXITCODE -ne 0) { throw "SubFlow runtime preparation failed (exit $LASTEXITCODE)." }
