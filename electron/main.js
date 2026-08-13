const { app, BrowserWindow, ipcMain, dialog, Menu } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn, execSync } = require('child_process')
const http = require('http')

const isDev = process.env.NODE_ENV === 'development'
const userDataPath = app.getPath('userData')
const settingsPath = path.join(userDataPath, 'settings.json')
const appDataPath = app.getPath('userData')
const dbPath = path.join(appDataPath, 'app.db')
const uploadPath = path.join(appDataPath, 'uploads')
const logPath = path.join(appDataPath, 'backend.log')

function logMain(msg) {
  try {
    fs.appendFileSync(logPath, `[Main] ${msg}\n`)
  } catch (e) {
    // если даже логирование не работает - не роняем приложение из-за этого
  }
  console.log(msg)
}

let mainWindow
let wizardWindow
let splashWindow
let backendProcess
let backendReady = false

function getSettings() {
  try {
    if (fs.existsSync(settingsPath)) {
      return JSON.parse(fs.readFileSync(settingsPath, 'utf8'))
    }
  } catch (e) {
    console.error('Error reading settings:', e)
  }
  return null
}

function saveSettings(settings) {
  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2))
}

function findPython() {
  const candidates = ['py -3.12', 'py', 'python3.12', 'python3', 'python']
  for (const cmd of candidates) {
    try {
      execSync(`${cmd} --version`, { stdio: 'pipe' })
      console.log(`[Main] Found Python: ${cmd}`)
      return cmd
    } catch (e) {
      // try next
    }
  }
  console.error('[Main] No Python found!')
  return null
}

function startBackend() {
  const settings = getSettings()
  const backendPath = isDev
    ? path.join(__dirname, '..', 'backend')
    : path.join(process.resourcesPath, 'backend')

  // Ensure log directory exists
  try {
    fs.mkdirSync(appDataPath, { recursive: true })
    fs.mkdirSync(uploadPath, { recursive: true })
  } catch (e) {
    console.error('[Main] Failed to create directories:', e)
  }

  fs.writeFileSync(logPath, `[Main] === Starting backend at ${new Date().toISOString()} ===\n`)
  fs.appendFileSync(logPath, `[Main] isDev: ${isDev}\n`)
  fs.appendFileSync(logPath, `[Main] __dirname: ${__dirname}\n`)
  fs.appendFileSync(logPath, `[Main] process.resourcesPath: ${process.resourcesPath}\n`)
  fs.appendFileSync(logPath, `[Main] Backend path: ${backendPath}\n`)
  fs.appendFileSync(logPath, `[Main] Backend exists: ${fs.existsSync(backendPath)}\n`)
  fs.appendFileSync(logPath, `[Main] main.py exists: ${fs.existsSync(path.join(backendPath, 'main.py'))}\n`)
  fs.appendFileSync(logPath, `[Main] DB path: ${dbPath}\n`)
  fs.appendFileSync(logPath, `[Main] Upload path: ${uploadPath}\n`)
  fs.appendFileSync(logPath, `[Main] PATH: ${process.env.PATH}\n`)

  if (!fs.existsSync(backendPath)) {
    const msg = `Backend folder not found: ${backendPath}`
    console.error('[Main]', msg)
    fs.appendFileSync(logPath, `[Main] ERROR: ${msg}\n`)
    dialog.showErrorBox('Ошибка запуска сервера', msg + '\n\nПереустановите приложение.')
    return false
  }

  const pythonCmd = findPython()
  if (!pythonCmd) {
    const msg = 'Python не найден. Установите Python 3.12 и убедитесь, что "py" доступен в PATH.'
    console.error('[Main]', msg)
    fs.appendFileSync(logPath, `[Main] ERROR: ${msg}\n`)
    dialog.showErrorBox('Ошибка запуска сервера', msg)
    return false
  }

  // Проверяем, установлен ли uvicorn для найденного Python. Раньше, если зависимостей
  // не было, приложение просто показывало диалог с просьбой установить их вручную
  // через консоль - это неприемлемо для обычного пользователя, который просто
  // дважды кликнул на установленный .exe. Теперь при первом запуске приложение
  // пытается доустановить недостающие пакеты само (нужен интернет на компьютере
  // пользователя - как и для любого обычного приложения при первой настройке).
  try {
    execSync(`${pythonCmd} -m uvicorn --version`, { stdio: 'pipe' })
    fs.appendFileSync(logPath, `[Main] uvicorn check: OK\n`)
  } catch (e) {
    fs.appendFileSync(logPath, `[Main] uvicorn not found, attempting automatic install of backend dependencies...\n`)
    updateSplash('Устанавливаем необходимые компоненты...', 'Первый запуск может занять пару минут')
    const reqPath = path.join(backendPath, 'requirements.txt')
    try {
      const installCmd = `${pythonCmd} -m pip install -r "${reqPath}"`
      fs.appendFileSync(logPath, `[Main] Running: ${installCmd}\n`)
      const output = execSync(installCmd, { stdio: 'pipe', timeout: 5 * 60 * 1000, maxBuffer: 20 * 1024 * 1024 })
      fs.appendFileSync(logPath, `[Main] pip install output:\n${output.toString()}\n`)
    } catch (installErr) {
      const details = (installErr.stdout ? installErr.stdout.toString() : '') + (installErr.stderr ? installErr.stderr.toString() : '')
      fs.appendFileSync(logPath, `[Main] ERROR: automatic dependency install failed:\n${details}\n`)
      const msg = `Не удалось автоматически установить необходимые компоненты (нужен доступ в интернет).\n\n` +
        `Попробуйте вручную выполнить в командной строке:\n${pythonCmd} -m pip install -r "${reqPath}"\n\n` +
        `Подробности в лог-файле: ${logPath}`
      dialog.showErrorBox('Ошибка установки компонентов', msg)
      return false
    }
    // Повторная проверка после установки
    try {
      execSync(`${pythonCmd} -m uvicorn --version`, { stdio: 'pipe' })
      fs.appendFileSync(logPath, `[Main] uvicorn check after install: OK\n`)
      updateSplash('Почти готово...', 'Запускаем приложение')
    } catch (e2) {
      const msg = `Компоненты установились, но uvicorn всё равно не найден для ${pythonCmd}. ` +
        `Возможно, потребуется перезапустить приложение.\n\nЛог: ${logPath}`
      dialog.showErrorBox('Ошибка запуска сервера', msg)
      return false
    }
  }

  const pythonParts = pythonCmd.split(' ')
  const pythonExe = pythonParts[0]
  const extraArgs = pythonParts.slice(1)

  const env = {
    ...process.env,
    SMTP_HOST: settings?.smtp?.host || process.env.SMTP_HOST || '',
    SMTP_PORT: String(settings?.smtp?.port || process.env.SMTP_PORT || '587'),
    SMTP_USER: settings?.smtp?.user || process.env.SMTP_USER || '',
    SMTP_PASSWORD: settings?.smtp?.password || process.env.SMTP_PASSWORD || '',
    SMTP_FROM: settings?.smtp?.from || process.env.SMTP_FROM || '',
    APP_DB_PATH: dbPath,
    APP_UPLOAD_DIR: uploadPath,
  }

  fs.appendFileSync(logPath, `[Main] Starting backend with ${pythonCmd}\n`)
  fs.appendFileSync(logPath, `[Main] CWD: ${backendPath}\n`)

  backendProcess = spawn(pythonExe, [...extraArgs, '-m', 'uvicorn', 'main:root_app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: backendPath,
    env,
    detached: false,
    windowsHide: true,
  })

  backendProcess.stdout.on('data', (data) => {
    const line = data.toString()
    fs.appendFileSync(logPath, `[STDOUT] ${line}`)
  })

  backendProcess.stderr.on('data', (data) => {
    const line = data.toString()
    fs.appendFileSync(logPath, `[STDERR] ${line}`)
  })

  backendProcess.on('close', (code) => {
    fs.appendFileSync(logPath, `[Main] Backend exited with code ${code}\n`)
    backendProcess = null
  })

  fs.appendFileSync(logPath, `[Main] Backend process started (PID: ${backendProcess.pid})\n`)
  return true
}

function showSplash() {
  splashWindow = new BrowserWindow({
    width: 380,
    height: 220,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    backgroundColor: '#0f1720',
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  })
  splashWindow.loadFile(path.join(__dirname, 'splash.html'))
}

function updateSplash(title, subtitle) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.executeJavaScript(
      `window.setSplashText && window.setSplashText(${JSON.stringify(title)}, ${JSON.stringify(subtitle || '')})`
    ).catch(() => {})
  }
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close()
  }
  splashWindow = null
}

function stopBackend() {
  if (backendProcess) {
    try {
      backendProcess.kill()
    } catch (e) {
      console.error('[Main] Error killing backend:', e)
    }
    backendProcess = null
  }
}

function waitForBackend(maxAttempts = 30, delayMs = 1000) {
  return new Promise((resolve) => {
    let attempts = 0
    const check = () => {
      attempts++
      const req = http.get('http://127.0.0.1:8000/api/health', (res) => {
        if (res.statusCode === 200) {
          backendReady = true
          resolve(true)
        } else {
          if (attempts < maxAttempts) {
            setTimeout(check, delayMs)
          } else {
            resolve(false)
          }
        }
      })
      req.on('error', () => {
        if (attempts < maxAttempts) {
          setTimeout(check, delayMs)
        } else {
          resolve(false)
        }
      })
      req.setTimeout(2000, () => {
        req.destroy()
      })
    }
    check()
  })
}

function createWizardWindow() {
  wizardWindow = new BrowserWindow({
    width: 900,
    height: 700,
    resizable: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      preload: path.join(__dirname, 'preload.js'),
    },
    icon: path.join(__dirname, 'icon.png'),
  })

  const wizardHtml = path.join(__dirname, 'wizard.html')
  wizardWindow.loadFile(wizardHtml)

  // Open DevTools in development
  if (isDev) {
    wizardWindow.webContents.openDevTools()
  }

  wizardWindow.on('closed', () => {
    wizardWindow = null
  })
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      preload: path.join(__dirname, 'preload.js'),
    },
    icon: path.join(__dirname, 'icon.png'),
    show: false,
  })

 if (isDev) {
   console.log('[Main] Loading dev URL: http://localhost:3000')
   mainWindow.loadURL('http://localhost:3000')
 } else {
   const indexPath = path.join(__dirname, 'frontend', 'dist', 'index.html')
   console.log('[Main] Loading file:', indexPath)
   console.log('[Main] File exists:', fs.existsSync(indexPath))
   mainWindow.loadFile(indexPath)
 }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  if (isDev) {
    mainWindow.webContents.openDevTools()
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

ipcMain.handle('get-settings', () => {
  return getSettings()
})

ipcMain.handle('save-settings', (event, settings) => {
  saveSettings(settings)
  return true
})

ipcMain.handle('wizard-complete', (event, settings) => {
  logMain(`wizard-complete called with settings: ${JSON.stringify(settings)}`)
  saveSettings(settings)
  // Раньше здесь сначала закрывалось окно мастера (wizardWindow.close()), а
  // основное окно создавалось только через 1 секунду в setTimeout. Но в момент
  // между закрытием мастера и появлением основного окна открытых окон становилось
  // РОВНО НОЛЬ - а на это событие ('window-all-closed', см. ниже) приложение
  // реагирует полным завершением процесса (это нормально для десктоп-приложений
  // Windows, если не предотвратить намеренно). Именно поэтому после нажатия
  // "Готово" ничего не происходило - весь процесс Electron успевал закрыться
  // раньше, чем срабатывал отложенный createMainWindow().
  //
  // Исправление: создаём основное окно СРАЗУ и закрываем окно мастера только
  // после того, как основное окно реально готово показаться - открытых окон
  // никогда не становится 0, и приложение не завершается само по себе.
  createMainWindow()
  if (mainWindow) {
    mainWindow.once('ready-to-show', () => {
      if (wizardWindow) {
        wizardWindow.close()
      }
    })
  } else if (wizardWindow) {
    wizardWindow.close()
  }
  return true
})

app.whenReady().then(async () => {
  // Стандартное меню Electron (File/Edit/View/Window/Help) предназначено для
  // отладки самого Electron и не нужно в готовом десктоп-приложении для конечного
  // пользователя - оно только путает и выглядит "не как настоящая программа".
  Menu.setApplicationMenu(null)

  showSplash()
  const settings = getSettings()
  logMain(`whenReady: settings = ${JSON.stringify(settings)}`)
  if (!settings || !settings.setupComplete) {
    logMain('Decision: FIRST RUN (setupComplete is not true) -> will show WIZARD')
    const started = startBackend()
    if (!started) {
      closeSplash()
      dialog.showErrorBox(
        'Ошибка запуска сервера',
        `Не удалось запустить сервер. Проверьте:\n1. Python 3.12 установлен\n2. Зависимости бэкенда установлены\n3. Папка backend существует\n\nЛог: ${logPath}`
      )
      app.quit()
      return
    }
    logMain('Waiting for backend to be ready...')
    const ready = await waitForBackend(30, 1000)
    closeSplash()
    if (ready) {
      logMain('Backend is ready. Opening WIZARD window.')
      createWizardWindow()
    } else {
      logMain('ERROR: Backend failed to respond in time. Opening WIZARD anyway.')
      // Окно создаём ДО showErrorBox: showErrorBox - блокирующий модальный
      // диалог, и пока он висит, открытых BrowserWindow было бы 0 - тот же
      // паттерн, что уже вызывал баг с преждевременным app.quit() по
      // window-all-closed (см. wizard-complete handler ниже).
      createWizardWindow()
      dialog.showErrorBox(
        'Сервер не отвечает',
        'Сервер запущен, но не отвечает. Возможно, порт 8000 занят.\n\nПопробуйте:\n1. Перезагрузить компьютер\n2. Или запустить backend вручную:\n   cd backend && py -3.12 -m uvicorn main:root_app --host 127.0.0.1 --port 8000'
      )
    }
  } else {
    logMain('Decision: setupComplete=true -> will show MAIN WINDOW directly (skipping wizard)')
    const started = startBackend()
    const ready = started && await waitForBackend(30, 1000)
    closeSplash()
    if (ready) {
      logMain('Backend is ready. Opening MAIN window.')
      createMainWindow()
    } else {
      logMain('ERROR: Backend failed to respond in time. Opening MAIN window anyway.')
      // См. комментарий у аналогичной ветки WIZARD выше: окно создаём до
      // блокирующего showErrorBox, чтобы не было момента с 0 открытых окон.
      createMainWindow()
      dialog.showErrorBox(
        'Сервер не отвечает',
        `Сервер запущен, но не отвечает. Попробуйте перезапустить приложение.\n\nЛог: ${logPath}`
      )
    }
  }
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    const settings = getSettings()
    if (!settings || !settings.setupComplete) {
      startBackend()
      setTimeout(() => {
        createWizardWindow()
      }, 5000)
    } else {
      startBackend()
      setTimeout(() => {
        createMainWindow()
      }, 5000)
    }
  }
})

app.on('before-quit', () => {
  stopBackend()
})
