@echo off
REM Swim Sync Launcher
REM ------------------

echo Starting Swim Sync...

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found!
    echo Please install Python 3.11+ from python.org
    pause
    exit /b 1
)

REM Check spotDL
spotdl --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: spotDL not found!
    echo Installing spotDL...
    pip install spotdl
)

REM Check FFmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: FFmpeg not found!
    echo Please install FFmpeg and add it to PATH
    echo Downloads: https://ffmpeg.org/download.html
    echo.
    echo Press any key to continue anyway...
    pause >nul
)

REM Run the app from project root
cd /d "%~dp0.."
python run.py
