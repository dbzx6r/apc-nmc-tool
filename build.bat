@echo off
REM build.bat — Build APC NMC Field Tool into a single Windows .exe
REM Run this on the Windows developer machine (not the target deploy machine).
REM Requirements:  pip install -r requirements.txt -r requirements-build.txt

echo.
echo ========================================
echo   APC NMC Field Tool  —  Build Script
echo ========================================
echo.

REM Verify PyInstaller is available
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller not found. Run: pip install pyinstaller
    exit /b 1
)

REM Clean previous build artifacts
if exist "dist\APC_NMC_Tool.exe" del /f /q "dist\APC_NMC_Tool.exe"
if exist "build" rmdir /s /q "build"

echo [*] Running PyInstaller...
pyinstaller apc_tool.spec --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed. Check output above.
    exit /b 1
)

echo.
echo [OK] Build complete.
echo      Output: dist\APC_NMC_Tool.exe
echo.
echo      Copy APC_NMC_Tool.exe to the target machine.
echo      The database (apc_devices.db) will be created in the same folder
echo      as the .exe on first run.
echo.
pause
