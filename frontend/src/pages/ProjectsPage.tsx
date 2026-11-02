import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, List, Popconfirm, Space, Typography } from 'antd'
import { api, type Project } from '../api'
import StatusTag from '../components/StatusTag'

// Project history (FR-5.5).
export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = () =>
    api
      .projects()
      .then(setProjects)
      .catch((e: Error) => setError(e.message))
  useEffect(() => {
    void load()
  }, [])

  const remove = async (id: number) => {
    try {
      await api.deleteProject(id)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Мои проекты
        </Typography.Title>
        <Button type="primary" size="large" onClick={() => navigate('/new')}>
          Новый проект
        </Button>
      </Space>
      {error && <Alert type="error" message={error} showIcon />}
      <List
        loading={projects === null}
        dataSource={projects ?? []}
        locale={{ emptyText: <Empty description="Пока нет проектов — создайте первый ролик" /> }}
        renderItem={(p) => (
          <List.Item
            actions={[
              <Link key="open" to={`/projects/${p.id}`}>
                Открыть
              </Link>,
              <Popconfirm key="del" title="Удалить проект?" onConfirm={() => void remove(p.id)}>
                <Button type="link" danger>
                  Удалить
                </Button>
              </Popconfirm>,
            ]}
          >
            <List.Item.Meta
              title={<Link to={`/projects/${p.id}`}>{p.title || `Проект ${p.id}`}</Link>}
              description={
                <Space wrap>
                  <StatusTag status={p.status} />
                  <span>{p.format}</span>
                  <span>{p.style}</span>
                  <span>{new Date(p.created_at).toLocaleString('ru-RU')}</span>
                  <span>{p.cost_rub.toFixed(2)} ₽</span>
                </Space>
              }
            />
          </List.Item>
        )}
      />
    </Space>
  )
}
