#Requires -Version 5.1
param(
    [string]$Python = "python",
    [ValidateSet("auto", "cpu", "cuda", "mps")][string]$Device = "auto",
    [switch]$SkipWeights
)
# Compatibility entry point: use the same managed runtime as the client.
$ErrorActionPreference = "Stop"
& "$PSScriptRoot\invoke-runtime-preparation.ps1" -Kind gptsovits -Python $Python -Device $Device -SkipModels:$SkipWeights
