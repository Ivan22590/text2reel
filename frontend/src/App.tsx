import { useEffect, useState } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { Button, Layout, Space, Spin, Typography } from 'antd'
import { api } from './api'
import LoginPage from './pages/LoginPage'
import NewProjectPage from './pages/NewProjectPage'
import ProjectPage from './pages/ProjectPage'
import ProjectsPage from './pages/ProjectsPage'

export default function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    api
      .me()
      .then((me) => setUser(me.username))
      .catch(() => setUser(null))
  }, [])

  if (user === undefined) return <Spin style={{ display: 'block', marginTop: '30vh' }} />
  if (user === null) return <LoginPage onLogin={setUser} />

  const logout = async () => {
    await api.logout().catch(() => undefined)
    setUser(null)
  }

  return (
    <BrowserRouter>
      <Layout style={{ minHeight: '100vh' }}>
        <Layout.Header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Link to="/" style={{ color: '#fff', fontSize: 20, fontWeight: 700 }}>
            Text2Reel
          </Link>
          <Space>
            <Typography.Text style={{ color: '#ffffffb3' }}>{user}</Typography.Text>
            <Button size="small" onClick={() => void logout()}>
              Выйти
            </Button>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24, maxWidth: 1280, width: '100%', margin: '0 auto' }}>
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/new" element={<NewProjectPage />} />
            <Route path="/projects/:id" element={<ProjectPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </BrowserRouter>
  )
}
