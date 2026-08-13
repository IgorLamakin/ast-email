@echo off
chcp 65001 >nul
echo ==========================================
echo   Сборка АСТ Email Templates (Desktop)
echo ==========================================
echo.

set "PROJECT_DIR=%~dp0"

REM Читаем номер версии из electron/package.json - единый источник правды,
REM чтобы номер версии, который видно в самом приложении (нижняя часть
REM бокового меню), всегда совпадал с версией установщика.
for /f "delims=" %%v in ('node -p "require('%PROJECT_DIR:\=/%electron/package.json').version"') do set APP_VERSION=%%v
echo Версия сборки: %APP_VERSION%
echo.

REM Step 0: Install frontend dependencies if needed
echo [0/4] Проверка зависимостей фронтенда...
cd "%PROJECT_DIR%frontend"
if not exist "node_modules" (
    echo Установка зависимостей frontend...
    call npm install
    if errorlevel 1 (
        echo ОШИБКА: Не удалось установить зависимости frontend
        pause
        exit /b 1
    )
)

REM Step 1: Build frontend
echo [1/4] Сборка фронтенда...
cd "%PROJECT_DIR%frontend"
set VITE_APP_VERSION=%APP_VERSION%
call npm run build
if errorlevel 1 (
    echo ОШИБКА: Не удалось собрать фронтенд
    pause
    exit /b 1
)

REM Step 2: Install Electron dependencies
echo [2/4] Установка зависимостей Electron...
cd "%PROJECT_DIR%electron"
if not exist "node_modules" (
    call npm install
)
if errorlevel 1 (
    echo ОШИБКА: Не удалось установить зависимости Electron
    pause
    exit /b 1
)

REM Step 3: Build Electron app
echo [3/4] Сборка Electron приложения...
call npm run build:win
if errorlevel 1 (
    echo ОШИБКА: Не удалось собрать Electron приложение
    pause
    exit /b 1
)

REM Step 4: Copy installer into a versioned releases folder, so every build
REM ever produced stays available for rollback (see VERSIONING.md).
echo [4/4] Готово!
if not exist "%PROJECT_DIR%releases" mkdir "%PROJECT_DIR%releases"
copy /Y "%PROJECT_DIR%dist-electron\AST Email Templates Setup %APP_VERSION%.exe" "%PROJECT_DIR%releases\AST-Email-Templates-Setup-%APP_VERSION%.exe" >nul
echo.
echo Установщик находится в папке:
echo   %PROJECT_DIR%dist-electron
echo.
echo Копия версии %APP_VERSION% сохранена в архиве всех версий:
echo   %PROJECT_DIR%releases
echo.
if not defined CALLED_FROM_RELEASE pause
