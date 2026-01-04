@echo off
title Swim Sync Web UI
echo ================================================
echo   Swim Sync Web UI
echo ================================================
echo.
echo Starting local web server...
echo Your browser will open automatically.
echo.
echo Press Ctrl+C to stop the server when done.
echo.

cd /d "%~dp0.."
python run_web.py

pause
