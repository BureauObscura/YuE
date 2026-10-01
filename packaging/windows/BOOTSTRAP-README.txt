BUREAU OBSCURA AUDIO FABRICATOR — OFFLINE WINDOWS BUNDLE

This is a non-commercial art-project distribution. YuE2 model weights remain
licensed under CC BY-NC 4.0 with the additional individual-creator permission
provided by their authors. Do not use or redistribute the YuE2 weights for a
company's commercial purposes without a separate license from the authors.

DOWNLOAD
Download this bootstrap ZIP, SHA256SUMS.txt, and every numbered .7z part from
the same GitHub release into one folder. Extract this bootstrap ZIP there.

INSTALL
Right-click Extract-Bundle.ps1 and choose "Run with PowerShell", or run:

  powershell -ExecutionPolicy Bypass -File .\Extract-Bundle.ps1

The script verifies every release part before extracting. The included 7-Zip
binary is used only for unpacking this release and retains its own license.

RUN
Open "Bureau Obscura Audio Fabricator.exe" inside the extracted folder.
Keep the engines and runtimes beside it. Closing the app window stops both
local model services.

Models and runtimes are included. Generated takes and personal library data
are not; they remain under %LOCALAPPDATA%\YuE Studio.
