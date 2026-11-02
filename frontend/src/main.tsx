import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={ruRU}>
      <App />
    </ConfigProvider>
  </StrictMode>,
)
