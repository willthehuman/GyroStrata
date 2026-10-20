@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Start-Here.ps1" %*
set "GYRO_EXIT=%errorlevel%"
if not defined GYRO_NO_PAUSE pause
exit /b %GYRO_EXIT%
