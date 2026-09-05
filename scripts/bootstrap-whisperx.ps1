#Requires -Version 5.1
param(
    [string]$Python = "python",
    [ValidateSet("auto", "cpu", "cuda", "mps")][string]$Device = "auto"
)
# Compatibility entry point: pinned dependencies in the client-managed location.
$ErrorActionPreference = "Stop"
& "$PSScriptRoot\invoke-runtime-preparation.ps1" -Kind whisperx -Python $Python -Device $Device
