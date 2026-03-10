@echo off
setlocal

REM ── Resolve tool directory (works even if shortcut changes cwd) ── #
set "TOOL_DIR=%~dp0"
if "%TOOL_DIR:~-1%"=="\" set "TOOL_DIR=%TOOL_DIR:~0,-1%"

REM ── Verify setup has been run ────────────────────────────────────── #
if not exist "%TOOL_DIR%\.venv\Scripts\pythonw.exe" (
    echo.
    echo  [ERROR] Setup has not been run yet.
    echo.
    echo          Please run setup.bat first, then try again.
    echo.
    pause
    exit /b 1
)

REM ── Launch (pythonw = no console window for GUI app) ─────────────── #
start "" "%TOOL_DIR%\.venv\Scripts\pythonw.exe" "%TOOL_DIR%\main.py"
