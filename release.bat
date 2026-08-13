@echo off
chcp 65001 >nul
echo ==========================================
echo   Выпуск новой версии АСТ Email Templates
echo ==========================================
echo.

set "PROJECT_DIR=%~dp0"
cd "%PROJECT_DIR%"

REM Git должен быть установлен один раз (см. VERSIONING.md, раздел
REM "Первоначальная настройка"). Если его нет - подсказываем и останавливаемся,
REM а не падаем с непонятной ошибкой чуть ниже.
where git >nul 2>nul
if errorlevel 1 (
    echo ОШИБКА: Git не найден. Установите его с https://git-scm.com/download/win
    echo и запустите этот скрипт заново. Подробнее - в файле VERSIONING.md.
    pause
    exit /b 1
)

REM Если Git ещё не инициализирован в этой папке - делаем это автоматически,
REM один раз. Дальше это безопасно вызывать повторно - ничего не сломает.
if not exist "%PROJECT_DIR%.git" (
    echo Первый запуск - инициализация Git в этой папке...
    git init
    git add -A
    git commit -m "Начальная версия (до системы версионирования)"
    echo.
)

echo [1/4] Определение номера версии и текста для CHANGELOG...
node "%PROJECT_DIR%scripts\get-release-info.js" > "%PROJECT_DIR%scripts\.version.tmp"
set /p APP_VERSION=<"%PROJECT_DIR%scripts\.version.tmp"
del "%PROJECT_DIR%scripts\.version.tmp"
echo Версия: %APP_VERSION%
echo.

echo [2/4] Сохранение снимка кода в Git (commit + tag v%APP_VERSION%)...
git add -A
git commit -F "%PROJECT_DIR%scripts\.commit-message.tmp"
if errorlevel 1 (
    echo (Изменений для коммита не найдено, либо Git ещё не настроен - см. ниже)
)
git tag "v%APP_VERSION%" 2>nul
if errorlevel 1 (
    echo ПРЕДУПРЕЖДЕНИЕ: тег v%APP_VERSION% уже существует - пропускаю.
    echo Если вы хотите выпустить эту версию заново, сначала поднимите номер версии.
)
del "%PROJECT_DIR%scripts\.commit-message.tmp" 2>nul
echo.

echo [3/4] Сборка установщика (это может занять несколько минут)...
set CALLED_FROM_RELEASE=1
call "%PROJECT_DIR%build-electron.bat"
echo.

echo [4/4] Готово! Версия %APP_VERSION% выпущена.
echo ==========================================
echo.
echo Что дальше:
echo   - Установщик этой версии:      %PROJECT_DIR%releases\AST-Email-Templates-Setup-%APP_VERSION%.exe
echo   - Чтобы ОБНОВИТЬ приложение:   просто запустите этот .exe поверх текущей установки
echo   - История всех версий кода:    git log --oneline
echo   - Откатить КОД к этой версии:  git checkout v%APP_VERSION%
echo   - Откатить САМО ПРИЛОЖЕНИЕ:    запустите установщик нужной версии из папки releases
echo.
pause
