"""
Простой скрипт для проверки SMTP настроек.
Запуск: py -3.12 test_smtp.py
"""
import smtplib
import os

print("=" * 50)
print("ПРОВЕРКА SMTP НАСТРОЕК")
print("=" * 50)

# Сначала пробуем переменные окружения
host = os.getenv("SMTP_HOST", "")
port_str = os.getenv("SMTP_PORT", "")
user = os.getenv("SMTP_USER", "")
password = os.getenv("SMTP_PASSWORD", "")
from_addr = os.getenv("SMTP_FROM", "")

# Если переменные не заданы — спрашиваем интерактивно
if not host:
    host = input("SMTP сервер [smtp.yandex.ru]: ").strip() or "smtp.yandex.ru"
if not port_str:
    port_input = input("Порт [587]: ").strip() or "587"
    port = int(port_input)
else:
    port = int(port_str)
if not user:
    user = input("Email (логин): ").strip()
if not password:
    password = input("Пароль приложения: ").strip()
if not from_addr:
    from_addr = input(f"Отправитель (From) [{user}]: ").strip() or user

print(f"\nSMTP_HOST: {host}")
print(f"SMTP_PORT: {port}")
print(f"SMTP_USER: {user}")
print(f"SMTP_PASS: {'*' * len(password)}")
print(f"SMTP_FROM: {from_addr}")
print("=" * 50)

if not host or not user or not password:
    print("\nОШИБКА: Не все настройки заданы!")
    exit(1)

print("\nПодключаюсь к серверу...")

if port == 465:
    # Port 465 requires SSL directly
    try:
        with smtplib.SMTP_SSL(host, 465, timeout=10) as server:
            print("SSL подключение установлено.")
            server.login(user, password)
            print("АУТЕНТИФИКАЦИЯ УСПЕШНА! (SSL)")
            print("\nВаши настройки SMTP работают корректно через SSL.")
            print("Используйте порт 465 в настройках приложения.")
    except smtplib.SMTPAuthenticationError as e:
        print(f"\nОШИБКА АУТЕНТИФИКАЦИИ (SSL): {e}")
        print("\nПричины:")
        print("1. Неправильный пароль или логин")
        print("2. Для Яндекса — возможно, нужен пароль приложения")
        print("3. Для Mail.ru — используйте обычный пароль от почты")
        print("4. Проверьте, что email указан полностью (с @)")
    except Exception as e:
        print(f"\nОШИБКА ПОДКЛЮЧЕНИЯ (SSL): {e}")
        print("Проверьте настройки хоста и порта.")
else:
    # Port 587 or other — try STARTTLS
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            print("TLS подключение установлено (STARTTLS).")
            server.login(user, password)
            print("АУТЕНТИФИКАЦИЯ УСПЕШНА! (STARTTLS)")
            print("\nВаши настройки SMTP работают корректно.")
            print("Письма должны отправляться из приложения.")
    except smtplib.SMTPAuthenticationError as e:
        print(f"\nОШИБКА АУТЕНТИФИКАЦИИ (STARTTLS): {e}")
        print("\nПробую SSL на порту 465...")
        try:
            with smtplib.SMTP_SSL(host, 465, timeout=10) as server:
                print("SSL подключение установлено.")
                server.login(user, password)
                print("АУТЕНТИФИКАЦИЯ УСПЕШНА! (SSL)")
                print("\nВаши настройки SMTP работают корректно через SSL.")
                print("Рекомендуется использовать порт 465 в настройках приложения.")
        except smtplib.SMTPAuthenticationError as e2:
            print(f"\nОШИБКА АУТЕНТИФИКАЦИИ (SSL): {e2}")
            print("\nПричины:")
            print("1. Используешь ОБЫЧНЫЙ пароль вместо ПАРОЛЯ ПРИЛОЖЕНИЯ")
            print("2. Неправильный логин (должен быть полный email)")
            print("3. Пароль приложения скопирован не полностью")
            print("4. В Яндексе не включён доступ через почтовые клиенты")
            print("   (Настройки → Почтовые программы → Разрешить)")
            print("\nКак получить пароль приложения Яндекс:")
            print("  https://id.yandex.ru/security → Пароли приложений → Создать")
        except Exception as e2:
            print(f"\nОШИБКА ПОДКЛЮЧЕНИЯ (SSL): {e2}")
            print("Проверь настройки хоста и порта.")
    except Exception as e:
        print(f"\nОШИБКА ПОДКЛЮЧЕНИЯ (STARTTLS): {e}")
        print("Пробую SSL на порту 465...")
        try:
            with smtplib.SMTP_SSL(host, 465, timeout=10) as server:
                print("SSL подключение установлено.")
                server.login(user, password)
                print("АУТЕНТИФИКАЦИЯ УСПЕШНА! (SSL)")
                print("\nВаши настройки SMTP работают корректно через SSL.")
                print("Рекомендуется использовать порт 465 в настройках приложения.")
        except smtplib.SMTPAuthenticationError as e2:
            print(f"\nОШИБКА АУТЕНТИФИКАЦИИ (SSL): {e2}")
            print("\nПричины:")
            print("1. Используешь ОБЫЧНЫЙ пароль вместо ПАРОЛЯ ПРИЛОЖЕНИЯ")
            print("2. Неправильный логин (должен быть полный email)")
            print("3. Пароль приложения скопирован не полностью")
            print("4. В Яндексе не включён доступ через почтовые клиенты")
            print("   (Настройки → Почтовые программы → Разрешить)")
            print("\nКак получить пароль приложения Яндекс:")
            print("  https://id.yandex.ru/security → Пароли приложений → Создать")
        except Exception as e2:
            print(f"\nОШИБКА ПОДКЛЮЧЕНИЯ (SSL): {e2}")
            print("Проверь настройки хоста и порта.")

print("=" * 50)
