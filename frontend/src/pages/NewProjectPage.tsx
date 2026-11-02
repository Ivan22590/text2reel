import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Col, Form, Input, Radio, Row, Select, Space, Typography, Upload } from 'antd'
import { api, type Format, type Meta } from '../api'

const MAX_CHARS = 5000
const STYLE_HINTS: Record<string, string> = {
  realism: 'кинематографичное фото',
  anime: 'яркая аниме-иллюстрация',
  watercolor: 'мягкая акварель',
  comic: 'комикс с контуром',
  render3d: 'стилизованный 3D',
  minimal: 'плоская векторная графика',
}

interface Values {
  title?: string
  script: string
  style: string
  format: Format
  voice: string
}

// Script upload and style/format choice (FR-5.1).
export default function NewProjectPage() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm<Values>()
  const navigate = useNavigate()
  const script = Form.useWatch('script', form) ?? ''

  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => setError(e.message))
  }, [])

  const importFile = async (file: File) => {
    try {
      const { text } = await api.parseScript(file)
      form.setFieldValue('script', text.slice(0, MAX_CHARS))
    } catch (e) {
      setError((e as Error).message)
    }
    return false // do not upload automatically
  }

  const submit = async (values: Values) => {
    setBusy(true)
    try {
      const project = await api.createProject(values)
      await api.analyze(project.id)
      navigate(`/projects/${project.id}`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Typography.Title level={3} style={{ margin: 0 }}>
        Новый проект
      </Typography.Title>
      {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />}
      <Form
        form={form}
        layout="vertical"
        onFinish={submit}
        initialValues={{ style: 'watercolor', format: '9:16', voice: 'ru-RU-SvetlanaNeural' }}
      >
        <Row gutter={24}>
          <Col xs={24} lg={14}>
            <Card title="Сценарий">
              <Form.Item name="title" label="Название (необязательно)">
                <Input maxLength={200} placeholder="По умолчанию — первая строка сценария" />
              </Form.Item>
              <Form.Item
                name="script"
                label={`Текст (${script.length} / ${MAX_CHARS})`}
                rules={[{ required: true, message: 'Вставьте текст сценария' }]}
              >
                <Input.TextArea
                  autoSize={{ minRows: 10, maxRows: 22 }}
                  maxLength={MAX_CHARS}
                  placeholder="Вставьте сценарий. Каждые 1–3 предложения станут отдельной сценой с картинкой и озвучкой."
                />
              </Form.Item>
              <Upload accept=".txt,.docx" showUploadList={false} beforeUpload={importFile}>
                <Button>Загрузить из файла (.txt, .docx)</Button>
              </Upload>
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="Стиль и формат">
              <Form.Item name="style" label="Визуальный стиль">
                <Radio.Group style={{ width: '100%' }}>
                  <Row gutter={[8, 8]}>
                    {meta?.styles.map((s) => (
                      <Col span={12} key={s.id}>
                        <Radio.Button value={s.id} style={{ width: '100%', height: 'auto', padding: 8 }}>
                          <div style={{ fontWeight: 600 }}>{s.name}</div>
                          <div style={{ fontSize: 12, opacity: 0.7 }}>{STYLE_HINTS[s.id]}</div>
                        </Radio.Button>
                      </Col>
                    ))}
                  </Row>
                </Radio.Group>
              </Form.Item>
              <Form.Item name="format" label="Формат">
                <Radio.Group
                  optionType="button"
                  options={meta?.formats.map((f) => ({ value: f.id, label: `${f.id} · ${f.name}` }))}
                />
              </Form.Item>
              <Form.Item name="voice" label="Голос">
                <Select options={meta?.voices.map((v) => ({ value: v.id, label: v.name }))} />
              </Form.Item>
              <Button type="primary" htmlType="submit" size="large" block loading={busy}>
                Создать и разбить на сцены
              </Button>
            </Card>
          </Col>
        </Row>
      </Form>
    </Space>
  )
}
