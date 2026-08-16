# Контекст задачи: Автообновление приложения «АСТ Email Templates»

Файл-контекст: что требовалось, кто как решал подобное, как устроена наша
реализация, как выпустить обновление и как проверить.

---

## 1. Требования (что просил пользователь)

1. При запуске приложения с рабочего стола, если вышло обновление — показывать
   сообщение с **кратким описанием изменений** и двумя кнопками:
   **«Установить»** и **«Пропустить»**.
2. По «Установить» — всё происходит автоматически, и запускается уже
   обновлённое приложение.
3. По «Пропустить» — можно продолжать работу; в **личном кабинете** (раздел
   «Мой профиль») появляется кнопка «Установить обновление» — по ней тоже всё
   устанавливается автоматически с перезапуском.
4. В обоих случаях **история, шаблоны, контакты, настройки — сохраняются**.

## 2. Анализ того, как такую задачу решают обычно

### 2.1. Основные инструменты экосистемы Electron

| Инструмент | Суть | Плюсы для нашего случая | Минусы |
|---|---|---|---|
| **electron-updater** (модуль electron-builder) | Встраивается в main-процесс; сам скачивает через `latest.yml` из GitHub Releases и переустанавливает | Работает именно с нашим сборщиком (electron-builder + NSIS); из коробки прогресс, releaseNotes, diff-обновления | Для приватного репо клиенту нужен токен (см. §6) |
| electron-builder `--publish always` | Сборка + загрузка установщика и метаданных в GitHub Releases | Один шаг, генерирует `latest.yml` | — |
| Electron Forge `autoUpdater` (Squirrel.Windows) | Альтернативный подход | — | Требует смены сборщика; у нас закреплён electron-builder |
| Свой HTTP-сервер / проверка версии | Приложение само сравнивает версии | Гибко | Не обновляет файлы, пришлось бы писать установщик самим |

### 2.2. Ключевые практики, применённые здесь

1. **`autoUpdater.autoDownload = false`** — иначе electron-updater качает
   обновление сразу на старте и «Пропустить» теряет смысл. Скачивание
   начинается только после явного «Установить».
2. **Описание изменений** — `update-available` отдаёт `info.releaseNotes`
   (из GitHub Release / встраивается сборщиком через
   `releaseInfo.releaseNotesFile`). Окно диалога показывает версии и список
   изменений.
3. **Кнопки «Установить / Пропустить»** — кастомное окно по образцу уже
   существующих `splash.html`/`wizard.html` (`dialog.showMessageBox` не даёт
   двух нужных кастомных действий в стиле приложения).
4. **Отложенная установка из личного кабинета** — IPC-мост к фронтенду:
   `ipcRenderer.invoke('update:get-status' | 'update:install' | 'update:check')`.
   Рендерер может это делать, т.к. окна собраны с
   `nodeIntegration: true, contextIsolation: false` (так уже используется
   мастер настройки).
5. **Пропуск версии** — пропущенная версия сохраняется в `settings.json`
   (`skipUpdateVersion`). Диалог при старте для неё не показывается, но кнопка
   в личном кабинете остаётся; если вышла более новая — диалог появится снова.
6. **Сохранность данных** — стандартный приём: личные данные лежат в каталоге
   `userData` (Electron), а не в папке программы. NSIS при обновлении
   перезаписывает только файлы программы. В проекте уже так:
   - `userData/settings.json` (SMTP, `skipUpdateVersion`);
   - `userData/app.db` (шаблоны, контакты, аналитика — `APP_DB_PATH`);
   - `userData/uploads/` (файлы — `APP_UPLOAD_DIR`);
   плюс `deleteAppDataOnUninstall: false`.
   Поэтому данные сохраняются в обоих сценариях.
7. **Публикация** — GitHub Releases: `npm run publish` (= `electron-builder
   --win --publish always`), загружает установщик + `latest.yml`.

## 3. Архитектура решения

```
[Запуск приложения]
      ▼
whenReady (setupComplete) → createMainWindow → setTimeout(3s) checkForUpdates()
      ▼
autoUpdater.checkForUpdates()   (autoDownload=false)
      ├── update-available --► не пропущена версия? --► createUpdateWindow()
      │                                              (update.html)
      │      └──► broadcast 'update:status' → личный кабинет
      ├── update-not-available --► тихо
      ├── error --► broadcast 'update:status' {state:'error'}
      └── «Установить» (диалог или кабинет) --► installUpdate()
                ▼
          downloadUpdate() → download-progress (прогресс) → update-downloaded
                ▼
          stopBackend() → quitAndInstall(isSilent=true, isForceRunAfter=true)
```

IPC-мост (main ↔ renderer):
- `update:get-status` → `{ supported, currentVersion, state, version, releaseNotes }`
- `update:check` → повторная проверка
- `update:install` → `installUpdate()`
- `update:skip version` → запомнить пропущенную версию и закрыть окно
- событие: `update:status` (в т.ч. прогресс); для окна обновления — `update:info`

---

## 4. Что сделано (файлы)

| Файл | Изменение |
|---|---|
| `electron/package.json` | `version: 2.3.0`; зависимость `electron-updater`; скрипт `publish`; `build.publish` (GitHub: `IgorLamakin/ast-email`, private); `build.releaseInfo.releaseNotesFile`; в упаковку добавлены `update.html`, `RELEASE_NOTES.md` |
| `electron/main.js` | `require('electron-updater')` в try/catch; блок «AUTO UPDATE» (окно `update.html`, `checkForUpdates()`, `installUpdate()`, события autoUpdater, IPC `update:*`); фоновая проверка через 3 c после открытия главного окна |
| `electron/update.html` | Окно «Доступна новая версия»: версии, описание изменений, кнопки «Установить обновление»/«Пропустить», прогресс-бар |
| `electron/RELEASE_NOTES.md` | Краткое описание релиза (встраивается в `latest.yml`) |
| `frontend/src/components/Profile.jsx` | Карточка «Обновления приложения» в личном кабинете |
| `updates/CONTEXT.md` | Этот документ |

## 5. Как выпустить новую версию

> Статус на 16.08.2026: репозиторий **переведён в публичный** (вариант A),
> релизы **v2.3.0** и **v2.3.1** опубликованы, `latest.yml` загружен.

1. Поднять версию в `electron/package.json` (и при необходимости
   `frontend/package.json`).
2. Обновить `CHANGELOG.md` и `electron/RELEASE_NOTES.md`.
3. Собрать фронтенд: `cd ../frontend && npm run build`.
4. Опубликовать (токен из авторизованного gh берётся автоматически):
   ```powershell
   cd electron
   $env:GH_TOKEN = & "$env:USERPROFILE\gh-cli\bin\gh.exe" auth token
   npm run publish
   ```
   В GitHub поднимется Release `vX.Y.Z` с установщиком и `latest.yml`.

## 6. Известные ограничения / что нужно для production

- Репозиторий **публичный** (выбор «А»): electron-updater скачивает обновления
  без токена — готово к раздаче. Если позже потребуется приватность исходников,
  правильный вариант — «generic» HTTP-провайдер (папка с `latest.yml` +
  установщиком на внутреннем сервере), токен тогда не нужен и исходники
  остаются приватными.
- После «Пропустить» диалог для той же версии не показывается (но кнопка в
  кабинете остаётся) до появления более новой версии.
- В dev-режиме (`isDev`) обновления не проверяются.
- Смена сборщика на Forge не требуется.

## 7. Статус выполнения

- [x] Анализ решений (этот файл)
- [x] Конфиг сборки/публикации (`package.json`)
- [x] Логика main (диалог, загрузка, установка, защита данных)
- [x] Окно «Доступна новая версия» + личный кабинет
- [ ] `npm install electron-updater` в `electron/`
- [ ] `frontend npm run build` с новым `Profile.jsx`
- [ ] `electron-builder` сборка и `--publish always`
- [ ] Живой сквозной тест (установка 2.2.1 → публикация 2.3.0 → диалог/личный
  кабинет → установка → данные целы)

Зависимость: терминал среды был заблокирован на момент реализации части файлов;
команды для сборки и проверки — в §5.