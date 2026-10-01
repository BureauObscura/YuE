[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot 'Bureau Obscura Audio Fabricator'),
    [switch]$SkipHashCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$archiveName = 'Bureau-Obscura-Audio-Fabricator-1.0.0-Windows-x64.7z'
$firstPart = Join-Path $PSScriptRoot ($archiveName + '.001')
$sevenZip = Join-Path $PSScriptRoot 'tools\7zip\7z.exe'
$hashList = Join-Path $PSScriptRoot 'SHA256SUMS.txt'

if (-not (Test-Path -LiteralPath $firstPart -PathType Leaf)) {
    throw "Place this bootstrap beside every $archiveName.NNN release part before extracting."
}
if (-not (Test-Path -LiteralPath $sevenZip -PathType Leaf)) {
    throw 'The bundled 7-Zip extractor is missing from the bootstrap folder.'
}

if (-not $SkipHashCheck) {
    if (-not (Test-Path -LiteralPath $hashList -PathType Leaf)) {
        throw 'SHA256SUMS.txt is required unless -SkipHashCheck is explicitly supplied.'
    }
    $expected = @{}
    foreach ($line in Get-Content -LiteralPath $hashList) {
        if ($line -match '^([a-fA-F0-9]{64})\s+\*(.+)$') {
            $expected[$Matches[2]] = $Matches[1].ToLowerInvariant()
        }
    }
    $parts = Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object { $_.Name -like ($archiveName + '.*') } | Sort-Object Name
    if (-not $parts.Count) {
        throw 'No split archive parts were found.'
    }
    foreach ($part in $parts) {
        if (-not $expected.ContainsKey($part.Name)) {
            throw "No published checksum exists for $($part.Name)."
        }
        Write-Host "Verifying $($part.Name)..."
        $actual = (Get-FileHash -LiteralPath $part.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected[$part.Name]) {
            throw "Checksum mismatch for $($part.Name). Download that part again."
        }
    }
}

$destinationFull = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destinationFull) {
    if (Get-ChildItem -LiteralPath $destinationFull -Force -ErrorAction SilentlyContinue) {
        throw "Destination must be empty: $destinationFull"
    }
} else {
    New-Item -ItemType Directory -Path $destinationFull -Force | Out-Null
}

Write-Host "Extracting to $destinationFull..."
& $sevenZip x $firstPart "-o$destinationFull" -y
if ($LASTEXITCODE -ne 0) {
    throw "7-Zip extraction failed with exit code $LASTEXITCODE."
}

$launcher = Join-Path $destinationFull 'Bureau Obscura Audio Fabricator.exe'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw 'Extraction completed without the application launcher.'
}
Unblock-File -LiteralPath $launcher -ErrorAction SilentlyContinue
Write-Host ''
Write-Host 'Extraction complete.' -ForegroundColor Green
Write-Host "Open: $launcher"
