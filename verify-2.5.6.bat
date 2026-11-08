@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==========================================
echo   AST Email Templates - verify 2.5.6
echo ==========================================
echo.

set FAIL=0

echo [1/5] Python syntax check...
py -3.12 -m py_compile backend\main.py backend\models.py backend\schemas.py backend\database.py >nul 2>&1
if errorlevel 1 py -m py_compile backend\main.py backend\models.py backend\schemas.py backend\database.py >nul 2>&1
if errorlevel 1 (
  echo   ERROR: Python syntax check failed.
  set FAIL=1
) else (
  echo   OK
)

echo [2/5] Node syntax check (electron)...
node --check electron\main.js >nul 2>&1
if errorlevel 1 (
  echo   ERROR: main.js syntax check failed.
  set FAIL=1
) else (
  echo   main.js OK
)
node --check electron\preload.js >nul 2>&1
if errorlevel 1 (
  echo   ERROR: preload.js syntax check failed.
  set FAIL=1
) else (
  echo   preload.js OK
)

echo [3/5] Version consistency...
for /f "delims=" %%v in ('node -p "require('./electron/package.json').version"') do set VER=%%v
echo   electron/package.json: %VER%
if not "%VER%"=="2.5.6" (
  echo   WARN: electron version is %VER%, expected 2.5.6
)

echo [4/5] Check leftover vulnerable patterns in source...
>nul 2>&1 findstr /S /C:"JinjaTemplate(" backend\main.py && (
  echo   WARN: backend/main.py still references JinjaTemplate
) || echo   no JinjaTemplate in backend\main.py
>nul 2>&1 findstr /S /M /C:"nodeIntegration: true" electron\*.js electron\*.html
if errorlevel 1 (
  echo   no nodeIntegration:true in electron source - OK
) else (
  echo "WARN: nodeIntegration:true found in electron source"
)

echo [5/5] Итог проверок...
if "%FAIL%"=="1" (
  echo.
  echo ==========================================
  echo   Syntax checks FAILED. Fix them, then re-run.
  echo ==========================================
  pause
  exit /b 1
)

echo.
echo   Все проверки пройдены.
echo   Для сборки установщика запустите release.bat вручную.
echo   (Раньше этот скрипт сам вызывал release.bat - убрано, чтобы
echo    проверка не запускала сборку/коммит неожиданно.)
pause