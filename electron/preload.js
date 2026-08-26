// Preload script for AST Email Templates
// Единственный мост между страницами (renderer) и главным процессом (main).
// Рендерер НЕ имеет прямого доступа к Node.js (в окнах теперь
// nodeIntegration:false + contextIsolation:true) - только к этим методам через
// контекст window.astAPI.
//
// ВАЖНО (безопасность): каналы IPC строго ограничены белым списком. Даже если
// в приложении случится XSS, злоумышленный код сможет вызвать только эти
// методы и не сможет добраться до произвольных каналов Electron или Node.js.
const { contextBridge, ipcRenderer } = require('electron')

const ALLOWED_INVOKE = new Set([
  'get-settings',
  'save-settings',
  'wizard-complete',
  'update:get-status',
  'update:check',
  'update:install',
  'update:skip',
])
const ALLOWED_LISTEN = new Set(['update:status', 'update:info'])

function safeListener(channel, cb) {
  const wrapped = (_event, payload) => cb(payload)
  ipcRenderer.on(channel, wrapped)
  return () => {
    try { ipcRenderer.removeListener(channel, wrapped) } catch (e) { /* ignore */ }
  }
}

contextBridge.exposeInMainWorld('astAPI', {
  // Универсальная обёртка - используется мастером настройки и окном обновления.
  invoke: (channel, payload) => {
    if (!ALLOWED_INVOKE.has(channel)) {
      return Promise.reject(new Error('IPC-канал не разрешён: ' + channel))
    }
    return ipcRenderer.invoke(channel, payload)
  },
  on(channel, cb) {
    if (!ALLOWED_LISTEN.has(channel)) return () => {}
    return safeListener(channel, cb)
  },
  // Удобные обёртки для React-фронтенда (раздел «Обновления» в профиле).
  updateGetStatus: () => ipcRenderer.invoke('update:get-status'),
  updateCheck: () => ipcRenderer.invoke('update:check'),
  updateInstall: () => ipcRenderer.invoke('update:install'),
  updateSkip: (version) => ipcRenderer.invoke('update:skip', version),
  onUpdateStatus: (cb) => safeListener('update:status', cb),
  onUpdateInfo: (cb) => safeListener('update:info', cb),
})
