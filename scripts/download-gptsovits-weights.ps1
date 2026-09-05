#Requires -Version 5.1
param(
    [string]$Python = "python",
    [ValidateSet("auto", "cpu", "cuda", "mps")][string]$Device = "auto"
)
# Prepare the managed runtime, then download and validate models and language data.
$ErrorActionPreference = "Stop"
& "$PSScriptRoot\invoke-runtime-preparation.ps1" -Kind gptsovits -Python $Python -Device $Device
