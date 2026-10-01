[CmdletBinding()]
param(
    [string]$YuERoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$StableRoot = 'C:\Bureau\Tools\stable-audio-3',
    [string]$OutputRoot = 'C:\Bureau\AudioFabricatorRelease',
    [string]$Version = '1.0.0',
    [string]$BuilderPython = '',
    [switch]$SkipBuild,
    [switch]$SkipValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path))
}

function Assert-ChildPath([string]$Parent, [string]$Child) {
    $parentPath = (Get-FullPath $Parent).TrimEnd('\') + '\'
    $childPath = Get-FullPath $Child
    if (-not $childPath.StartsWith($parentPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the release root: $childPath"
    }
}

function Reset-BuildDirectory([string]$Parent, [string]$Path) {
    Assert-ChildPath $Parent $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Invoke-Robocopy {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExcludeDirectories = @(),
        [string[]]$ExcludeFiles = @()
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Copy source does not exist: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $arguments = @($Source, $Destination, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:2', '/W:1', '/XJ', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($ExcludeDirectories.Count) {
        $arguments += '/XD'
        $arguments += $ExcludeDirectories
    }
    if ($ExcludeFiles.Count) {
        $arguments += '/XF'
        $arguments += $ExcludeFiles
    }
    & robocopy.exe @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Robocopy failed with exit code $LASTEXITCODE while copying $Source"
    }
}

function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$FilePath, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Copy-PortablePython {
    param(
        [Parameter(Mandatory = $true)][string]$Venv,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $venvPython = Join-Path $Venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Python environment is incomplete: $Venv"
    }
    $base = (& $venvPython -c 'import sys; print(sys.base_prefix)').Trim()
    if (-not (Test-Path -LiteralPath (Join-Path $base 'python.exe'))) {
        throw "Python base runtime is unavailable: $base"
    }
    Invoke-Robocopy -Source $base -Destination $Destination `
        -ExcludeDirectories @((Join-Path $base 'Lib\site-packages'), (Join-Path $base '__pycache__')) `
        -ExcludeFiles @('*.pyc', '*.pyo')
    $sitePackages = Join-Path $Destination 'Lib\site-packages'
    Invoke-Robocopy -Source (Join-Path $Venv 'Lib\site-packages') -Destination $sitePackages `
        -ExcludeDirectories @('__pycache__') -ExcludeFiles @('*.pyc', '*.pyo')
    if (Test-Path -LiteralPath (Join-Path $Venv 'Scripts')) {
        Invoke-Robocopy -Source (Join-Path $Venv 'Scripts') -Destination (Join-Path $Destination 'Scripts') `
            -ExcludeDirectories @('__pycache__') -ExcludeFiles @('python.exe', 'pythonw.exe', '*.pyc', '*.pyo')
    }
    Copy-Item -LiteralPath (Join-Path $base 'LICENSE.txt') -Destination (Join-Path $Destination 'PYTHON-LICENSE.txt') -Force
}

function Assert-File([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required release input is missing: $Path"
    }
}

$YuERoot = Get-FullPath $YuERoot
$StableRoot = Get-FullPath $StableRoot
$OutputRoot = Get-FullPath $OutputRoot
$releaseRoot = Join-Path $OutputRoot "v$Version"
$stageRoot = Join-Path $releaseRoot 'stage'
$packageRoot = Join-Path $stageRoot 'Bureau Obscura Audio Fabricator'
$launcherSource = Join-Path $PSScriptRoot 'audio_fabricator_launcher.py'
$launcherSpec = Join-Path $PSScriptRoot 'Bureau Obscura Audio Fabricator.spec'
$launcherDist = Join-Path $PSScriptRoot 'dist\Bureau Obscura Audio Fabricator.exe'

Assert-File (Join-Path $YuERoot 'MODEL_LICENSE')
Assert-File (Join-Path $YuERoot 'models\YuE2-3B\model.safetensors')
Assert-File (Join-Path $YuERoot 'models\YuE2-Vae\model.safetensors')
Assert-File (Join-Path $StableRoot 'optimized\tflite\models\tflite\sa3-sm-sfx\dit_fp32.tflite')
Assert-File (Join-Path $StableRoot 'optimized\tflite\models\tflite\same-s\dec_fp32.tflite')
Assert-File (Join-Path $StableRoot 'optimized\tflite\models\tflite\t5gemma\encoder_fp16.tflite')
Assert-File $launcherSource
Assert-File $launcherSpec

if (-not $SkipBuild) {
    Push-Location (Join-Path $YuERoot 'studio\web')
    try {
        Invoke-Checked 'npm.cmd' 'run' 'build'
    }
    finally {
        Pop-Location
    }

    if (-not $BuilderPython) {
        $builderVenv = Join-Path $PSScriptRoot '.build-venv'
        $BuilderPython = Join-Path $builderVenv 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $BuilderPython)) {
            $py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
            if (-not $py) {
                throw 'Python launcher py.exe is required to create the isolated PyInstaller environment.'
            }
            Invoke-Checked $py '-3.12' '-m' 'venv' $builderVenv
            Invoke-Checked $BuilderPython '-m' 'pip' 'install' '--disable-pip-version-check' 'pyinstaller==6.22.3' 'pillow==12.3.0'
        }
    }
    Assert-File $BuilderPython
    Push-Location $PSScriptRoot
    try {
        Invoke-Checked $BuilderPython '-m' 'PyInstaller' '--noconfirm' '--clean' '--distpath' (Join-Path $PSScriptRoot 'dist') '--workpath' (Join-Path $PSScriptRoot 'build') $launcherSpec
    }
    finally {
        Pop-Location
    }
}

Assert-File $launcherDist
Assert-File (Join-Path $YuERoot 'studio\web\dist\index.html')
Reset-BuildDirectory $OutputRoot $stageRoot
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

$yueDestination = Join-Path $packageRoot 'engines\yue'
Invoke-Robocopy -Source $YuERoot -Destination $yueDestination `
    -ExcludeDirectories @('.git', '.venv', 'models', 'outputs', 'node_modules', '.pytest_cache', '__pycache__', 'build') `
    -ExcludeFiles @('*.pyc', '*.pyo', '*.partial')

foreach ($model in @('YuE2-3B', 'YuE2-Vae')) {
    $sourceModel = Join-Path $YuERoot "models\$model"
    $targetModel = Join-Path $yueDestination "models\$model"
    Invoke-Robocopy -Source $sourceModel -Destination $targetModel `
        -ExcludeDirectories @('.cache', (Join-Path $sourceModel 'assets\audio'), '__pycache__') `
        -ExcludeFiles @('*.partial', '*.pyc', '*.pyo')
}

$stableDestination = Join-Path $packageRoot 'engines\stable-audio-3'
Invoke-Robocopy -Source $StableRoot -Destination $stableDestination `
    -ExcludeDirectories @('.git', '.venv', 'output', 'tests', '.pytest_cache', '__pycache__') `
    -ExcludeFiles @('*.pyc', '*.pyo', '*.partial')

$runtimes = Join-Path $packageRoot 'runtimes'
Copy-PortablePython -Venv (Join-Path $YuERoot '.venv') -Destination (Join-Path $runtimes 'yue-python')
Copy-PortablePython -Venv (Join-Path $StableRoot 'optimized\tflite\.venv') -Destination (Join-Path $runtimes 'stable-python')

Copy-Item -LiteralPath $launcherDist -Destination (Join-Path $packageRoot 'Bureau Obscura Audio Fabricator.exe') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README-FIRST.txt') -Destination (Join-Path $packageRoot 'README-FIRST.txt') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'MODEL_TERMS.md') -Destination (Join-Path $packageRoot 'MODEL_TERMS.md') -Force

$licenses = Join-Path $packageRoot 'licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $YuERoot 'LICENSE') -Destination (Join-Path $licenses 'YUE2-CODE-APACHE-2.0.txt') -Force
Copy-Item -LiteralPath (Join-Path $YuERoot 'MODEL_LICENSE') -Destination (Join-Path $licenses 'YUE2-MODEL-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $YuERoot 'THIRD_PARTY_NOTICES.md') -Destination (Join-Path $licenses 'YUE2-THIRD-PARTY-NOTICES.md') -Force
Copy-Item -Path (Join-Path $YuERoot 'licenses\*') -Destination $licenses -Force
Copy-Item -LiteralPath (Join-Path $StableRoot 'LICENSE') -Destination (Join-Path $licenses 'STABLE-AUDIO-3-CODE-MIT.txt') -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'licenses\*') -Destination $licenses -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'NOTICE.txt') -Destination (Join-Path $packageRoot 'NOTICE.txt') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'model-revisions.json') -Destination (Join-Path $packageRoot 'model-revisions.json') -Force

$yueRuntime = Join-Path $runtimes 'yue-python\python.exe'
$stableRuntime = Join-Path $runtimes 'stable-python\python.exe'
& $yueRuntime -m pip list --format=freeze | Set-Content -LiteralPath (Join-Path $packageRoot 'yue-runtime-packages.txt') -Encoding utf8
& $stableRuntime -m pip list --format=freeze | Set-Content -LiteralPath (Join-Path $packageRoot 'stable-runtime-packages.txt') -Encoding utf8

$majorFiles = @(
    Join-Path $packageRoot 'Bureau Obscura Audio Fabricator.exe'
    Join-Path $yueDestination 'models\YuE2-3B\model.safetensors'
    Join-Path $yueDestination 'models\YuE2-Vae\model.safetensors'
    Join-Path $stableDestination 'optimized\tflite\models\tflite\sa3-sm-sfx\dit_fp32.tflite'
    Join-Path $stableDestination 'optimized\tflite\models\tflite\same-s\dec_fp32.tflite'
    Join-Path $stableDestination 'optimized\tflite\models\tflite\t5gemma\encoder_fp16.tflite'
)
$hashes = foreach ($file in $majorFiles) {
    $item = Get-Item -LiteralPath $file
    $hash = Get-FileHash -LiteralPath $file -Algorithm SHA256
    [ordered]@{
        path = $item.FullName.Substring($packageRoot.Length + 1).Replace('\', '/')
        bytes = $item.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    product = 'Bureau Obscura Audio Fabricator'
    version = $Version
    built_at_utc = [DateTime]::UtcNow.ToString('o')
    platform = 'windows-x64'
    models = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'model-revisions.json') -Raw | ConvertFrom-Json
    major_files = $hashes
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $packageRoot 'BUILD-MANIFEST.json') -Encoding utf8

if (-not $SkipValidation) {
    Invoke-Checked $yueRuntime '-c' 'import torch, transformers, soundfile, yue2; print(torch.__version__)'
    Invoke-Checked $stableRuntime '-c' 'import ai_edge_litert, gradio, numpy, soundfile; print(gradio.__version__)'
    $env:BO_AUDIO_FABRICATOR_HOME = $packageRoot
    try {
        Invoke-Checked (Join-Path $packageRoot 'Bureau Obscura Audio Fabricator.exe') '--self-test'
    }
    finally {
        Remove-Item Env:BO_AUDIO_FABRICATOR_HOME -ErrorAction SilentlyContinue
    }
}

$summary = [ordered]@{
    package_root = $packageRoot
    bytes = (Get-ChildItem -LiteralPath $packageRoot -Recurse -File | Measure-Object Length -Sum).Sum
    files = (Get-ChildItem -LiteralPath $packageRoot -Recurse -File).Count
}
$summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseRoot 'bundle-summary.json') -Encoding utf8
$summary | ConvertTo-Json
