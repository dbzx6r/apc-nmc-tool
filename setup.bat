@echo off
setlocal EnableDelayedExpansion

REM ── Resolve tool directory early (needed for vendor\ path) ──────── #
set "TOOL_DIR=%~dp0"
if "%TOOL_DIR:~-1%"=="\" set "TOOL_DIR=%TOOL_DIR:~0,-1%"

echo.
echo ============================================
echo   APC NMC Field Tool  —  First-Time Setup
echo ============================================
echo.

REM ── 1. Verify Python is installed ───────────────────────────────── #
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in PATH.
    echo.
    echo         Download and install Python 3.11 or newer from:
    echo         https://www.python.org/downloads/
    echo.
    echo         Make sure to check "Add Python to PATH" during install,
    echo         then re-run this setup.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Found %PYVER%
echo.

REM ── 2. Create virtual environment ───────────────────────────────── #
if exist ".venv\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists — skipping creation.
) else (
    echo [*] Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)
echo.

REM ── 3. Install / upgrade dependencies ───────────────────────────── #
echo [*] Installing dependencies from local vendor folder...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet --no-index --find-links "%TOOL_DIR%\vendor"

REM Install from vendor/ — fully offline, no internet required
.venv\Scripts\pip.exe install ^
    --no-index ^
    --find-links "%TOOL_DIR%\vendor" ^
    -r requirements.txt ^
    --quiet
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo         Make sure the vendor\ folder is present next to setup.bat
    echo         and contains all required .whl files.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

REM ── 4. Create desktop shortcut ───────────────────────────────────── #
echo [*] Creating desktop shortcut...

set "SHORTCUT=%USERPROFILE%\Desktop\APC NMC Tool.lnk"
set "LAUNCH_SCRIPT=%TOOL_DIR%\launch.bat"
set "ICON_PATH=%TOOL_DIR%\icon.ico"

REM Build the PowerShell script in a temp file to avoid CMD expansion issues
set "PS_TMP=%TEMP%\apc_shortcut.ps1"
(
    echo $s = (New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%')
    echo $s.TargetPath = '%LAUNCH_SCRIPT%'
    echo $s.WorkingDirectory = '%TOOL_DIR%'
    echo $s.Description = 'APC NMC Field Tool'
) > "%PS_TMP%"
if exist "%ICON_PATH%" (
    echo $s.IconLocation = '%ICON_PATH%' >> "%PS_TMP%"
)
echo $s.Save() >> "%PS_TMP%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_TMP%"
del "%PS_TMP%" >nul 2>&1

if %errorlevel% neq 0 (
    echo [WARN] Could not create desktop shortcut automatically.
    echo        You can manually create a shortcut to:
    echo        %LAUNCH_SCRIPT%
) else (
    echo [OK] Desktop shortcut created: "APC NMC Tool"
)
echo.

REM ── 5. Done ─────────────────────────────────────────────────────── #
echo ============================================
echo   Setup complete!
echo.
echo   Double-click "APC NMC Tool" on your
echo   desktop to launch the program.
echo ============================================
echo.
pause
