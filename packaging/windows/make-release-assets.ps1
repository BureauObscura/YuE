[CmdletBinding()]
param(
    [string]$ReleaseRoot = 'C:\Bureau\AudioFabricatorRelease\v1.0.0',
    [string]$SevenZip = '',
    [string]$Version = '1.0.0'
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

$ReleaseRoot = Get-FullPath $ReleaseRoot
$packageRoot = Join-Path $ReleaseRoot 'stage\Bureau Obscura Audio Fabricator'
$assets = Join-Path $ReleaseRoot 'assets'
if (-not (Test-Path -LiteralPath (Join-Path $packageRoot 'BUILD-MANIFEST.json'))) {
    throw "Run build-offline-bundle.ps1 first. Missing package: $packageRoot"
}
Assert-ChildPath $ReleaseRoot $assets
if (Test-Path -LiteralPath $assets) {
    Remove-Item -LiteralPath $assets -Recurse -Force
}
New-Item -ItemType Directory -Path $assets -Force | Out-Null

if (-not $SevenZip) {
    $command = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($command) {
        $SevenZip = $command.Source
    } else {
        $candidate = Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -File -Filter 7z.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($candidate) { $SevenZip = $candidate.FullName }
    }
}
if (-not $SevenZip -or -not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) {
    throw '7-Zip is required to make streaming split volumes. Install 7zip.7zip or pass -SevenZip.'
}

$archiveBase = Join-Path $assets "Bureau-Obscura-Audio-Fabricator-$Version-Windows-x64.7z"
Push-Location $packageRoot
try {
    & $SevenZip a -t7z -mx=1 -mmt=on -v1900m $archiveBase '.\*'
    if ($LASTEXITCODE -ne 0) {
        throw "7-Zip failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$bootstrap = Join-Path $ReleaseRoot 'bootstrap'
Assert-ChildPath $ReleaseRoot $bootstrap
if (Test-Path -LiteralPath $bootstrap) {
    Remove-Item -LiteralPath $bootstrap -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $bootstrap 'tools\7zip') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Extract-Bundle.ps1') -Destination $bootstrap -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'BOOTSTRAP-README.txt') -Destination (Join-Path $bootstrap 'README.txt') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'MODEL_TERMS.md') -Destination $bootstrap -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'NOTICE.txt') -Destination $bootstrap -Force

$sevenZipDirectory = Split-Path -Parent $SevenZip
foreach ($name in @('7z.exe', '7z.dll', 'License.txt')) {
    $source = Join-Path $sevenZipDirectory $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "The portable 7-Zip bootstrap component is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $bootstrap 'tools\7zip') -Force
}

$bootstrapZip = Join-Path $assets "Bureau-Obscura-Audio-Fabricator-$Version-Bootstrap.zip"
Compress-Archive -Path (Join-Path $bootstrap '*') -DestinationPath $bootstrapZip -CompressionLevel Optimal

$hashLines = foreach ($file in Get-ChildItem -LiteralPath $assets -File | Sort-Object Name) {
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash *$($file.Name)"
}
$hashPath = Join-Path $assets 'SHA256SUMS.txt'
$hashLines | Set-Content -LiteralPath $hashPath -Encoding ascii

$releaseNotes = Join-Path $assets 'RELEASE_NOTES.md'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'RELEASE_NOTES.md') -Destination $releaseNotes -Force

$largest = Get-ChildItem -LiteralPath $assets -File | Sort-Object Length -Descending | Select-Object -First 1
if ($largest.Length -ge 2GB) {
    throw "A release asset exceeds GitHub's 2 GiB limit: $($largest.FullName)"
}

Get-ChildItem -LiteralPath $assets -File | Sort-Object Name | Select-Object Name, Length, @{n='GiB';e={[math]::Round($_.Length / 1GB, 3)}}
