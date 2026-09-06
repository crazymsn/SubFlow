#Requires -Version 5.1
<#
Preview known generated files; pass -Apply to remove the reviewed items.
Preserves dist/SubFlow, model environments, source, tests, and user configuration.
#>
[CmdletBinding()]
param([switch]$Apply, [switch]$RetiredModels)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'pyproject.toml')) -or
    -not (Test-Path -LiteralPath (Join-Path $projectRoot 'src/bilingual_sub'))) {
    throw 'Run the copy of this script stored in the SubFlow repository.'
}

function Assert-ProjectPath([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside this repository: $absolute"
    }
    return $absolute
}

$names = @('build', 'dist/gpu-update', 'dist/greeting-update', 'dist/multilingual-update',
    'dist/preview-fix', '.mypy_cache', '.pytest_cache', '.ruff_cache', '.coverage',
    'htmlcov', 'client-smoke.json', 'dist/full-1.3.52', 'dist/offline-1.3.52',
    'dist/quality-update', 'dist/voice-restored', 'dist/ui-1.3.53',
    'dist/ui-1.3.54', 'dist/recognition-1.3.54', 'dist/ui-1.3.55', 'dist/ui-1.3.56', 'dist/ui-1.3.57', 'dist/ui-1.3.58', 'dist/ui-1.3.59', 'dist/ui-1.3.60',
    'dist/SubFlow/_internal/bilingual_sub/_data/bootstrap/__pycache__')
if ($RetiredModels) {
    # Only retired stock weights. Custom checkpoints and active v2 assets stay.
    $modelBase = 'third_party/GPT-SoVITS/GPT_SoVITS/pretrained_models/'
    $retired = @('gsv-v4-pretrained', 'models--nvidia--bigvgan_v2_24khz_100band_256x',
        's1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt', 's1v3.ckpt',
        's2D488k.pth', 's2G488k.pth', 's2Gv3.pth', 'sv', 'v2Pro')
    foreach ($name in $retired) { $names += $modelBase + $name }
    $offline = Join-Path $projectRoot 'dist/SubFlow/offline'
    $manifestPath = Join-Path $offline 'bundle.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Complete offline bundle required before retiring models.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($kind in @('qwen-native', 'qwen-clone', 'gptsovits')) {
        $model = $manifest.models.$kind
        if (-not $model -or -not (Test-Path -LiteralPath (Join-Path $offline $model.path))) {
            throw "Active offline model missing: $kind"
        }
    }
    foreach ($name in @('s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt', 's2G2333k.pth')) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ($modelBase + 'gsv-v2final-pretrained/' + $name)))) {
            throw "Active source v2 weight missing: $name"
        }
    }
    if ($env:SUBFLOW_GPTSOVITS_CONFIG -or $env:SUBFLOW_GPTSOVITS_HOME -or $env:SUBFLOW_GPTSOVITS_PYTHON) {
        throw 'Custom GPT-SoVITS overrides are active; inspect them before retiring models.'
    }
    $names += 'dist/SubFlow/GPT-SoVITS'
}
$targets = @($names | ForEach-Object {
    $candidate = Assert-ProjectPath (Join-Path $projectRoot $_)
    if (Test-Path -LiteralPath $candidate) { $candidate }
})
# These are source trees, not Python environments containing installed packages.
foreach ($sourceTree in @('src', 'tests', 'scripts', 'packaging')) {
    $base = Join-Path $projectRoot $sourceTree
    foreach ($cache in @(Get-ChildItem -LiteralPath $base -Directory -Recurse -Force -Filter '__pycache__')) {
        if ($cache.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        $targets += Assert-ProjectPath $cache.FullName
    }
}
$targets = @($targets | Sort-Object -Unique)
$client = Join-Path $projectRoot 'dist/SubFlow'
$vendor = Join-Path $projectRoot 'third_party'
$protected = @($client, $vendor)
if ($env:SUBFLOW_RUNTIME_DIR) { $protected += [IO.Path]::GetFullPath($env:SUBFLOW_RUNTIME_DIR) }
foreach ($target in $targets) {
    foreach ($keep in $protected) {
        if ($target.Equals($keep, [StringComparison]::OrdinalIgnoreCase) -or
            $keep.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "A cleanup target contains a protected runtime: $target"
        }
    }
}

# Inspect without traversing junctions or symlinks. Detach links only, never targets.
function Read-Tree([string]$Path) {
    $pending = New-Object 'System.Collections.Generic.Stack[object]'
    $pending.Push((Get-Item -LiteralPath $Path -Force))
    while ($pending.Count) {
        $item = $pending.Pop()
        $item
        if ($item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) {
                $pending.Push($child)
            }
        }
    }
}

$links = @()
$plan = @()
foreach ($target in $targets) {
    $tree = @(Read-Tree $target)
    $treeLinks = @($tree | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    foreach ($link in $treeLinks) {
        if ($link.LinkType -notin @('Junction', 'SymbolicLink')) {
            throw "Unrecognized reparse point; inspect it manually: $($link.FullName)"
        }
    }
    $files = @($tree | Where-Object { -not $_.PSIsContainer -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) })
    $links += $treeLinks
    $plan += [pscustomobject]@{ Path = $target; Files = $files.Count; Bytes = [long](($files | Measure-Object Length -Sum).Sum) }
}
$plan | Format-Table Path, Files, Bytes -AutoSize
$bytes = [long](($plan | Measure-Object Bytes -Sum).Sum)
Write-Host ('Total: {0:N2} GiB; {1} links will be detached without deleting their targets.' -f ($bytes / 1GB), $links.Count)
if (-not $Apply) {
    Write-Host 'Preview only. To apply this plan, run: .\scripts\clean-workspace.ps1 -Apply'
    return
}

# Refuse if a running process or saved reference points at a removal target.
$processes = @(Get-CimInstance Win32_Process)
$config = if ($env:APPDATA) { Join-Path $env:APPDATA 'SubFlow/config.yaml' } else { '' }
$settings = if ($config -and (Test-Path -LiteralPath $config)) { Get-Content -LiteralPath $config -Raw } else { '' }
$settings = $settings.Replace('\\', '\').Replace('/', '\')
foreach ($target in $targets) {
    if ($settings.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Saved settings reference a cleanup target; change the setting first: $target"
    }
    foreach ($process in $processes) {
        if (($process.ExecutablePath -and $process.ExecutablePath.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) -or
            ($process.CommandLine -and $process.CommandLine.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0)) {
            throw "Process $($process.ProcessId) is using a cleanup target: $target"
        }
    }
}
$protectedFiles = @((Join-Path $client 'SubFlow.exe'), (Join-Path $client 'ffmpeg.exe'), (Join-Path $client 'ffprobe.exe'))
if ($config) { $protectedFiles += $config }
$checks = @($protectedFiles | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object {
    [pscustomobject]@{ Path = $_; Hash = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash }
})
$linkedResources = @($links | ForEach-Object {
    [pscustomobject]@{ Path = [string]$_.Target; Exists = (Test-Path -LiteralPath ([string]$_.Target)) }
})
foreach ($link in $links) {
    $path = Assert-ProjectPath $link.FullName
    $current = Get-Item -LiteralPath $path -Force
    if (-not ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $current.Target -ne $link.Target) {
        throw "Link changed during cleanup preparation: $path"
    }
    Remove-Item -LiteralPath $path -Force
}
foreach ($target in $targets) {
    $path = Assert-ProjectPath $target
    if (-not (Test-Path -LiteralPath $path)) { continue }
    Write-Host "Removing reviewed generated path: $path"
    if (@(Read-Tree $path | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "A link appeared after preparation; stopping: $path"
    }
    Remove-Item -LiteralPath $path -Recurse -Force
}
foreach ($check in $checks) {
    if ((Get-FileHash -LiteralPath $check.Path -Algorithm SHA256).Hash -ne $check.Hash) {
        throw "Protected file changed: $($check.Path)"
    }
}
foreach ($resource in $linkedResources) {
    if ((Test-Path -LiteralPath $resource.Path) -ne $resource.Exists) {
        throw "Linked resource changed: $($resource.Path)"
    }
}
Write-Host 'Cleanup complete. Current client, configuration, and linked runtimes preserved.'
