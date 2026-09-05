# Download official GPT-SoVITS pretrained weights into the vendored tree.
# https://github.com/RVC-Boss/GPT-SoVITS
# Portable builds include these files beside SubFlow.exe.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$dest = if ($env:SUBFLOW_GPTSOVITS_HOME) { $env:SUBFLOW_GPTSOVITS_HOME } else { Join-Path $Root "third_party\GPT-SoVITS" }
if (-not (Test-Path (Join-Path $dest "api_v2.py"))) {
    throw "api_v2.py not found in $dest. Run .\scripts\setup-gptsovits.ps1 first."
}
$weightsDir = Join-Path $dest "GPT_SoVITS\pretrained_models"
function Test-NonemptyDir([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    return $null -ne (Get-ChildItem $Path -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -notin @(".gitignore", ".gitattributes") } | Select-Object -First 1)
}
$hasBert = Test-NonemptyDir (Join-Path $weightsDir "chinese-roberta-wwm-ext-large")
$hasHubert = Test-NonemptyDir (Join-Path $weightsDir "chinese-hubert-base")
$hasWeights = $null -ne (Get-ChildItem $weightsDir -Recurse -Include *.ckpt,*.pth -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 1KB } | Select-Object -First 1)
$urls = @(
    "https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master/pretrained_models.zip",
    "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip",
    "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip"
)
$g2pw = @(
    "https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master/G2PWModel.zip",
    "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip",
    "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip"
)

function Get-Zip($List, $OutFile) {
    foreach ($uri in $List) {
        Write-Host "GET $uri"
        try {
            Invoke-WebRequest -Uri $uri -OutFile $OutFile -UseBasicParsing
            if ((Get-Item $OutFile).Length -gt 1MB) { return }
        } catch {
            Write-Host "  failed: $($_.Exception.Message)"
        }
    }
    throw "download failed: $OutFile"
}

if ($hasBert -and $hasHubert -and $hasWeights) {
    Write-Host "Pretrained models already present: $weightsDir"
} else {
    $tmp = Join-Path $dest "pretrained_models.zip"
    Get-Zip $urls $tmp
    Expand-Archive -Path $tmp -DestinationPath (Join-Path $dest "GPT_SoVITS") -Force
    Remove-Item $tmp -Force
}

$g2pwDir = Join-Path $dest "GPT_SoVITS\text\G2PWModel"
$g2pwReady = $null -ne (Get-ChildItem $g2pwDir -Recurse -Filter *.onnx -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $g2pwReady) {
    $g2pwZip = Join-Path $dest "G2PWModel.zip"
    Get-Zip $g2pw $g2pwZip
    Expand-Archive -Path $g2pwZip -DestinationPath (Join-Path $dest "GPT_SoVITS\text") -Force
    Remove-Item $g2pwZip -Force
}

Write-Host "Weights ready in $weightsDir"
Write-Host "Start SubFlow — the client will boot api_v2.py on 127.0.0.1:9880."
