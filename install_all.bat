@echo off
setlocal
pushd "%~dp0"
rem One-time setup: create project venv and install selenium (Tsinghua mirror first)
set "PYEXE=C:\Users\LENOVO\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=D:\develop\Python\python.exe"
if not exist "%PYEXE%" (
    echo [X] Python not found, please edit PYEXE in this file
    pause & exit /b 1
)
echo [1/2] Creating venv...
"%PYEXE%" -m venv "%~dp0.venv" || (echo [X] venv failed & pause & exit /b 1)
echo [2/2] Installing selenium...
"%~dp0.venv\Scripts\python.exe" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple selenium || (
    echo Mirror failed, trying pypi.org ...
    "%~dp0.venv\Scripts\python.exe" -m pip install selenium || (echo [X] install failed & pause & exit /b 1)
)
echo.
echo [OK] Setup done. Now edit config.ini, then run other .bat files.
pause
