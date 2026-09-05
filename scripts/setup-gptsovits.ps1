#Requires -Version 5.1
param(
    [string]$Python = "python",
    [ValidateSet("auto", "cpu", "cuda", "mps")][string]$Device = "auto"
)
# Prepare this project's patched source and dependencies; weights can follow later.
$ErrorActionPreference = "Stop"
& "$PSScriptRoot\invoke-runtime-preparation.ps1" -Kind gptsovits -Python $Python -Device $Device -SkipModels
