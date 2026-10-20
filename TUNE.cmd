@echo off
setlocal DisableDelayedExpansion
set "GYRO_RECIPE_ROOT=%~dp0"
set "GYRO_VENV_PY=%GYRO_RECIPE_ROOT%.venv\Scripts\python.exe"
if not exist "%GYRO_VENV_PY%" (
  echo Run INSTALL.cmd first: TUNE.cmd measures an installed profile.
  set "GYRO_EXIT=1"
  goto done
)
"%GYRO_VENV_PY%" "%GYRO_RECIPE_ROOT%tune.py" %*
set "GYRO_EXIT=%errorlevel%"
:done
if not "%GYRO_EXIT%"=="0" if not defined GYRO_NO_PAUSE pause
exit /b %GYRO_EXIT%
