@echo off
setlocal
title LLMap Launcher

cd /d "%~dp0"

echo ================================
echo  LLMap launcher
echo ================================
echo Folder: %CD%
echo.

set "PYTHON="

where python >nul 2>nul
if not errorlevel 1 set "PYTHON=python"

if not defined PYTHON if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python3.11.exe" (
    set "PYTHON=%LOCALAPPDATA%\Microsoft\WindowsApps\python3.11.exe"
)

if not defined PYTHON if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
)

if not defined PYTHON if exist "C:\Python311\python.exe" (
    set "PYTHON=C:\Python311\python.exe"
)

if not defined PYTHON if exist "C:\Python310\python.exe" (
    set "PYTHON=C:\Python310\python.exe"
)

if not defined PYTHON if exist "C:\Python39\python.exe" (
    set "PYTHON=C:\Python39\python.exe"
)

if not defined PYTHON (
    echo [ERROR] Python was not found.
    echo Install Python or add it to PATH, then run this file again.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python: %PYTHON%
echo.

if exist "%~dp0launcher.py" (
    "%PYTHON%" "%~dp0launcher.py"
    if errorlevel 1 (
        echo.
        echo [ERROR] launcher.py failed.
        pause
        exit /b 1
    )
    exit /b 0
)

echo [WARN] launcher.py was not found. Starting web server only.

netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    start "" "http://localhost:8080/index.html"
    exit /b 0
)

start /b "" "%PYTHON%" -m http.server 8080
timeout /t 2 >nul
start "" "http://localhost:8080/index.html"

echo.
echo Server is running at http://localhost:8080
pause
