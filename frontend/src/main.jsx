import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App.jsx'
import './index.css'

// HashRouter вместо BrowserRouter: собранное Electron-приложение грузит фронтенд
// как file:///.../dist/index.html, а не с настоящего HTTP-сервера. BrowserRouter
// использует History API и требует, чтобы любой путь (например /templates) можно
// было запросить у сервера напрямую - при обновлении страницы (F5) на таком пути
// это приводило к попытке открыть несуществующий файл и белому экрану.
// HashRouter хранит маршрут после "#" и всегда открывает один и тот же index.html.
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)
