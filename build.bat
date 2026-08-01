@echo off
setlocal
cd /d "%~dp0"

python package.py --installer
if errorlevel 1 (
  echo.
  echo Build failed.
  exit /b 1
)

echo.
echo Build OK.
exit /b 0
