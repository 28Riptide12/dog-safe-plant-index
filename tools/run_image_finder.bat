@echo off
REM Automatic Plant Image Finder - Scheduled Task Script
REM This script can be run by Windows Task Scheduler to automatically find and update plant images

setlocal enabledelayedexpansion

REM Change to Web app directory
cd /d "C:\Web app" || exit /b 1

REM Run the image finder
REM Settings:
REM   --max-plants 10: Find up to 10 images per run
REM   --delay 5.0: Wait 5 seconds between Commons API requests
REM   (no --dry-run: Actually save updates, not just preview)

echo.
echo ====================================
echo Plant Image Finder - Scheduled Run
echo ====================================
echo Started at: %date% %time%
echo.

.venv\Scripts\python.exe tools\find_missing_images.py --max-plants 10 --delay 5.0

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUCCESS] Plant image finder completed successfully
    echo Finished at: %date% %time%
) else (
    echo.
    echo [ERROR] Plant image finder failed with exit code %ERRORLEVEL%
    echo Finished at: %date% %time%
)

echo.
endlocal
