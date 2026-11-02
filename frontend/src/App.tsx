import { useEffect, useState } from 'react'
import { Alert, Card, Descriptions, Layout, Spin, Typography } from 'antd'
import { getHealth, type Health } from './api'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch((e: Error) => setError(e.message))
  }, [])

  return (
    <Layout style={{ minHeight: '100vh', padding: 24 }}>
      <Typography.Title>Text2Reel</Typography.Title>
      <Typography.Paragraph>Видео из текста с помощью AI. Интерфейс в разработке.</Typography.Paragraph>
      <Card title="Состояние API" style={{ maxWidth: 480 }}>
        {error && <Alert type="error" message={`API недоступен: ${error}`} />}
        {!error && !health && <Spin />}
        {health && (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Статус">{health.status}</Descriptions.Item>
            <Descriptions.Item label="Версия">{health.version}</Descriptions.Item>
            <Descriptions.Item label="LLM">{health.llm_model}</Descriptions.Item>
            <Descriptions.Item label="Картинки">{health.image_provider}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </Layout>
  )
}
