@echo off
REM Scheduler for Plant Image Finder
REM This script runs the image finder once daily at 2 AM
REM Usage: scheduler_setup.bat

setlocal enabledelayedexpansion

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%.."

echo.
echo ==========================================
echo Plant Image Finder - Task Scheduler Setup
echo ==========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script must be run as Administrator
    echo Please right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM Get Python executable path
for /f "tokens=*" %%i in ('where python') do (
    set PYTHON_EXE=%%i
    goto :found_python
)

:not_found_python
echo ERROR: Python not found in PATH
echo Please ensure Python is installed and added to PATH
pause
exit /b 1

:found_python
echo Found Python: %PYTHON_EXE%

REM Create logs directory
if not exist "logs" mkdir logs

REM Task name
set TASK_NAME=PlantImageFinder
set TASK_DESCRIPTION=Automatically discover and cache plant images from Wikimedia Commons and iNaturalist

REM Delete existing task if it exists
tasklist /FI "TASKSCHED.EXE" 2>NUL | find /I "TASKSCHED.EXE" >NUL
if %errorLevel% equ 0 (
    echo Removing existing task...
    schtasks /delete /tn "%TASK_NAME%" /f 2>nul
)

REM Create new scheduled task
REM Run daily at 2 AM
echo Creating scheduled task: %TASK_NAME%
echo Running daily at 02:00 AM
echo.

schtasks /create /tn "%TASK_NAME%" /tr ""%PYTHON_EXE%" ""%CD%\tools\scheduler.py""" /sc daily /st 02:00 /f /ru SYSTEM

if %errorLevel% equ 0 (
    echo.
    echo SUCCESS: Scheduled task created!
    echo Task Name: %TASK_NAME%
    echo Schedule: Daily at 02:00 AM
    echo Log File: %CD%\logs\image_scheduler.log
    echo.
    echo To view the task:
    echo   - Open Task Scheduler
    echo   - Look for "%TASK_NAME%" under "Task Scheduler Library"
    echo.
    echo To view recent runs:
    echo   - Check logs\image_scheduler.log
    echo.
    echo To modify the schedule, edit the task in Task Scheduler
) else (
    echo.
    echo ERROR: Failed to create scheduled task
    echo Error Code: %errorLevel%
)

echo.
pause
