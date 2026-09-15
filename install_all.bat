@echo off
setlocal
pushd "%~dp0"
rem Portable edition: Python + selenium are bundled in .\runtime, nothing to install.
if exist "%~dp0runtime\python.exe" (
    echo [OK] Portable Python found in runtime\. No installation needed.
    echo      Just edit config.ini, then double-click other .bat files.
) else (
    echo [X] runtime\python.exe missing. The package is incomplete, re-copy the whole folder.
)
pause
