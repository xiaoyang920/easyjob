@echo off
chcp 65001 >nul
title EasyJob - Local Launcher
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1" -OpenBrowser %*
set "launch_result=%errorlevel%"
if not "%launch_result%"=="0" (
  echo.
  echo Startup failed. Check the error above and the logs folder.
)
echo.
pause
exit /b %launch_result%
