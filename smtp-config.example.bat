@echo off
chcp 65001 >nul
REM ==========================================
REM  НАСТРОЙКА SMTP ДЛЯ ОТПРАВКИ ПИСЕМ
REM ==========================================
REM
REM ВАЖНО! Для Яндекс, Mail.ru и Gmail нужен
REM ПАРОЛЬ ПРИЛОЖЕНИЯ, а не обычный пароль!
REM
REM ==========================================
REM  КАК ПОЛЬЗОВАТЬСЯ ЭТИМ ФАЙЛОМ
REM ==========================================
REM 1. Скопируй этот файл в "smtp-config.bat" в той же папке
REM    (smtp-config.bat в Git не попадает - см. .gitignore -
REM    именно туда нужно вписывать реальный пароль).
REM 2. Заполни 3 значения ниже в "smtp-config.bat" реальными
REM    данными - этот example-файл со значениями не трогай.
REM
REM ==========================================
REM  КАК ПОЛУЧИТЬ ПАРОЛЬ ПРИЛОЖЕНИЯ (Яндекс)
REM ==========================================
REM 1. Открой браузер и зайди на:
REM    https://id.yandex.ru/security
REM 2. Включи "Двухфакторная аутентификация"
REM    (если еще не включена)
REM 3. Найди раздел "Пароли приложений"
REM 4. Нажми "Создать пароль приложения"
REM 5. Выбери тип "Почта"
REM 6. Скопируй 16 символов (например: abcd efgh ijkl mnop)
REM 7. Вставь этот пароль ниже в SMTP_PASSWORD
REM
REM ==========================================
REM  ЗАПОЛНИ ТОЛЬКО ЭТИ 3 ЗНАЧЕНИЯ:
REM ==========================================

set SMTP_HOST=smtp.yandex.ru
set SMTP_PORT=587
set SMTP_USER=ВАШ_ЛОГИН@yandex.ru
set SMTP_PASSWORD=ВАШ_ПАРОЛЬ_ПРИЛОЖЕНИЯ
set SMTP_FROM=ВАШ_ЛОГИН@yandex.ru

REM ==========================================
REM  ПРИМЕР ЗАПОЛНЕННОГО ФАЙЛА:
REM ==========================================
REM set SMTP_HOST=smtp.yandex.ru
REM set SMTP_PORT=587
REM set SMTP_USER=ivan@yandex.ru
REM set SMTP_PASSWORD=abcd efgh ijkl mnop
REM set SMTP_FROM=ivan@yandex.ru
REM ==========================================

REM --- Mail.ru (альтернатива) ---
REM set SMTP_HOST=smtp.mail.ru
REM set SMTP_PORT=587
REM set SMTP_USER=ВАШ_ЛОГИН@mail.ru
REM set SMTP_PASSWORD=ВАШ_ПАРОЛЬ_ПРИЛОЖЕНИЯ
REM set SMTP_FROM=ВАШ_ЛОГИН@mail.ru

REM --- Gmail (альтернатива) ---
REM set SMTP_HOST=smtp.gmail.com
REM set SMTP_PORT=587
REM set SMTP_USER=ВАШ_ЛОГИН@gmail.com
REM set SMTP_PASSWORD=ВАШ_ПАРОЛЬ_ПРИЛОЖЕНИЯ
REM set SMTP_FROM=ВАШ_ЛОГИН@gmail.com

REM ==========================================
REM  ПОСЛЕ ЗАПОЛНЕНИЯ (в smtp-config.bat):
REM  1. Сохрани файл (Ctrl+S)
REM  2. Закрой терминал с бэкендом
REM  3. Запусти start.bat заново
REM ==========================================
