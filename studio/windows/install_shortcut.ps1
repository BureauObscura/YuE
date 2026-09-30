param([switch]$StartMenuOnly)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$PythonW = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
$Launcher = Join-Path $PSScriptRoot 'browser_launcher.py'
$Icon = Join-Path $PSScriptRoot 'YuE Studio.ico'

foreach ($Required in @($Python, $PythonW, $Launcher)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Required YuE Studio file is missing: $Required"
    }
}

$TemporaryPng = New-TemporaryFile
try {
    Add-Type -AssemblyName System.Drawing
    $Source = [System.Drawing.Image]::FromFile((Join-Path $RepoRoot 'assets\logo.png'))
    $Canvas = New-Object System.Drawing.Bitmap 256, 256, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $Graphics = [System.Drawing.Graphics]::FromImage($Canvas)
    try {
        $Graphics.Clear([System.Drawing.Color]::Transparent)
        $Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $Graphics.DrawImage($Source, 0, 0, 256, 256)
        $Canvas.Save($TemporaryPng.FullName, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $Graphics.Dispose()
        $Canvas.Dispose()
        $Source.Dispose()
    }
    & $Python (Join-Path $PSScriptRoot 'make_icon.py') $TemporaryPng.FullName $Icon
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the YuE Studio shortcut icon.' }
} finally {
    Remove-Item -LiteralPath $TemporaryPng.FullName -Force -ErrorAction SilentlyContinue
}

$Targets = @((Join-Path ([Environment]::GetFolderPath('Programs')) 'YuE Studio.lnk'))
if (-not $StartMenuOnly) {
    $Targets += Join-Path ([Environment]::GetFolderPath('Desktop')) 'YuE Studio.lnk'
}
$Shell = New-Object -ComObject WScript.Shell
foreach ($Target in $Targets) {
    $Shortcut = $Shell.CreateShortcut($Target)
    $Shortcut.TargetPath = $PythonW
    $Shortcut.Arguments = '"' + $Launcher + '"'
    $Shortcut.WorkingDirectory = $RepoRoot
    $Shortcut.IconLocation = $Icon + ',0'
    $Shortcut.Description = 'YuE Studio music workspace'
    $Shortcut.Save()
    Write-Host "Installed: $Target"
}
