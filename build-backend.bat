@echo off
chcp 65001 >nul
echo ==========================================
echo   Сборка автономного backend (PyInstaller)
echo ==========================================
echo.

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%backend"

py -3.12 -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: PyInstaller не установлен.
    echo Выполните: py -3.12 -m pip install --user pyinstaller
    exit /b 1
)

if not exist "%PROJECT_DIR%build-backend" mkdir "%PROJECT_DIR%build-backend"

py -3.12 -m PyInstaller --noconfirm --clean --onedir --name ast-backend ^
  --distpath "%PROJECT_DIR%backend-dist" ^
  --workpath "%PROJECT_DIR%build-backend" ^
  --specpath "%PROJECT_DIR%build-backend" ^
  --add-data "%PROJECT_DIR%backend\email_templates;email_templates" ^
  --collect-all uvicorn ^
  --collect-all fastapi ^
  --collect-all sqlalchemy ^
  --collect-all passlib ^
  --collect-all jose ^
  --collect-all email_validator ^
  --collect-all xhtml2pdf ^
  --collect-all reportlab ^
  --collect-all jinja2 ^
  --collect-all bcrypt ^
  --collect-all multipart ^
  --collect-all openpyxl ^
  --collect-all xlrd ^
  --collect-all dns ^
  run_server.py

if errorlevel 1 (
    echo ОШИБКА: не удалось собрать backend.
    exit /b 1
)

if not exist "%PROJECT_DIR%backend-dist\ast-backend\ast-backend.exe" (
    echo ОШИБКА: ast-backend.exe не найден после сборки.
    exit /b 1
)

echo.
echo Готово: backend-dist\ast-backend\ast-backend.exe
