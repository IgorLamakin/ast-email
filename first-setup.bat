@echo off
chcp 65001 >nul
echo ==========================================
echo   First Setup - AST Email Templates
echo ==========================================
echo.

set "PROJECT_DIR=%~dp0"

REM Step 1: Install backend dependencies
echo [1/3] Installing backend dependencies...
cd "%PROJECT_DIR%backend"
py -3.12 -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install backend dependencies
    pause
    exit /b 1
)

REM Step 2: Install frontend dependencies
echo [2/3] Installing frontend dependencies...
cd "%PROJECT_DIR%frontend"
call npm install
if errorlevel 1 (
    echo ERROR: Failed to install frontend dependencies
    pause
    exit /b 1
)

REM Step 3: Install Electron dependencies
echo [3/3] Installing Electron dependencies...
cd "%PROJECT_DIR%electron"
call npm install
if errorlevel 1 (
    echo ERROR: Failed to install Electron dependencies
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   Setup complete!
echo ==========================================
echo.
echo Now run build-electron.bat to build the installer.
echo.
pause
