@echo off
echo ==========================================
echo   Email Templates - Launch
echo ==========================================
echo.
set "PROJECT_DIR=%~dp0"

REM Load SMTP config if exists
if exist "%PROJECT_DIR%smtp-config.bat" (
    echo [0/2] Loading SMTP configuration...
    call "%PROJECT_DIR%smtp-config.bat"
)

echo [1/2] Starting backend server...
start "Backend" powershell -NoExit -Command "cd '%PROJECT_DIR%backend'; py -3.12 -m uvicorn main:root_app"
timeout /t 4 >nul
echo [2/2] Starting frontend server...
start "Frontend" powershell -NoExit -Command "cd '%PROJECT_DIR%frontend'; npm run dev"
timeout /t 3 >nul
echo.
echo ==========================================
echo   Both servers are running!
echo.
echo   Open in browser:
echo   http://localhost:3000
echo.
echo   API docs:
echo   http://127.0.0.1:8000/docs
echo ==========================================
echo.
echo To stop - close Backend and Frontend windows.
pause
