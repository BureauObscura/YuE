@echo off
setlocal
set "STUDIO_ROOT=%~dp0.."
set "PYTHONUTF8=1"
cd /d "%STUDIO_ROOT%"
set "STUDIO_PYTHON=%STUDIO_ROOT%\.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" (
  echo YuE Studio cannot find %STUDIO_PYTHON%
  echo Run the Windows installation steps in studio\README.md first.
  pause
  exit /b 1
)
"%STUDIO_PYTHON%" studio\windows\browser_launcher.py
if errorlevel 1 (
  echo.
  echo YuE Studio stopped with an error. Review the message above.
  pause
)
