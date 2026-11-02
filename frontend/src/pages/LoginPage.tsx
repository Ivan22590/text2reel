import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { api } from '../api'

export default function LoginPage({ onLogin }: { onLogin: (username: string) => void }) {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const submit = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const { username } = await api.login(values.username, values.password)
      onLogin(username)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: '12vh' }}>
      <Card style={{ width: 380 }}>
        <Typography.Title level={3}>Text2Reel</Typography.Title>
        <Typography.Paragraph type="secondary">
          Видео из текста с помощью AI. Войдите с демо-доступом.
        </Typography.Paragraph>
        {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="username" label="Логин" rules={[{ required: true, message: 'Введите логин' }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="Пароль" rules={[{ required: true, message: 'Введите пароль' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            Войти
          </Button>
        </Form>
      </Card>
    </div>
  )
}
