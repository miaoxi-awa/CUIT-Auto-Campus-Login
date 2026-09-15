@echo off
setlocal
pushd "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Users\LENOVO\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" ( echo [X] run install_all.bat first & pause & exit /b 1 )
"%PY%" "%~dp0main.py" --logout-only --visible %*
pause
