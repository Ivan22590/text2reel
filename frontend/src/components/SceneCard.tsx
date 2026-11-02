import { useState } from 'react'
import { Alert, Button, Card, Image, Input, Popover, Select, Space, Tag, Tooltip, Typography } from 'antd'
import { api, type Scene } from '../api'

const CAMERA_LABELS: Record<string, string> = {
  zoom_in: 'Приближение',
  zoom_out: 'Отдаление',
  pan_left: 'Панорама влево',
  pan_right: 'Панорама вправо',
  static: 'Статично',
}

interface Props {
  scene: Scene
  aspect: string
  disabled: boolean
  onChanged: () => void
  onRegenerate: (sceneId: number, target: 'image' | 'audio', hint: string) => void
  onError: (message: string) => void
}

// One scene in the editor (FR-5.2): frame, narration, visual prompt, camera, regeneration.
export default function SceneCard({ scene, aspect, disabled, onChanged, onRegenerate, onError }: Props) {
  const [narration, setNarration] = useState(scene.narration)
  const [prompt, setPrompt] = useState(scene.visual_prompt)
  const [hint, setHint] = useState('')
  const [saving, setSaving] = useState(false)
  const dirty = narration !== scene.narration || prompt !== scene.visual_prompt

  const save = async (data: Partial<Scene>) => {
    setSaving(true)
    try {
      await api.updateScene(scene.id, data)
      onChanged()
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const [w, h] = aspect.split(':').map(Number)
  const status =
    scene.status === 'ready' ? (
      <Tag color="green">готова</Tag>
    ) : scene.status === 'failed' ? (
      <Tag color="red">ошибка</Tag>
    ) : (
      <Tag>нужна генерация</Tag>
    )

  return (
    <Card
      id={`scene-${scene.id}`}
      size="small"
      title={
        <Space>
          Сцена {scene.index + 1} {status}
          {scene.duration ? <Typography.Text type="secondary">{scene.duration.toFixed(1)} с</Typography.Text> : null}
        </Space>
      }
      extra={<Tag>{scene.mood}</Tag>}
    >
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ width: 160, flexShrink: 0 }}>
          <div
            style={{
              aspectRatio: `${w} / ${h}`,
              background: 'var(--ant-color-fill-tertiary, #f0f0f0)',
              borderRadius: 6,
              overflow: 'hidden',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {scene.image_url ? (
              <Image src={scene.image_url} width="100%" alt={`Сцена ${scene.index + 1}`} />
            ) : (
              <Typography.Text type="secondary">нет кадра</Typography.Text>
            )}
          </div>
          {scene.audio_url && <audio src={scene.audio_url} controls style={{ width: '100%', marginTop: 8 }} />}
        </div>
        <Space direction="vertical" style={{ flex: 1, minWidth: 260 }}>
          <Typography.Text strong>Текст озвучки</Typography.Text>
          <Input.TextArea
            value={narration}
            onChange={(e) => setNarration(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            disabled={disabled}
          />
          <Typography.Text strong>Визуальное описание (для генерации кадра)</Typography.Text>
          <Input.TextArea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            disabled={disabled}
          />
          <Space wrap>
            <Select
              value={scene.camera}
              style={{ width: 180 }}
              disabled={disabled}
              onChange={(camera) => void save({ camera })}
              options={Object.entries(CAMERA_LABELS).map(([value, label]) => ({ value, label }))}
            />
            <Button
              type="primary"
              disabled={!dirty || disabled}
              loading={saving}
              onClick={() => void save({ narration, visual_prompt: prompt })}
            >
              Сохранить
            </Button>
            <Popover
              trigger="click"
              title="Что изменить в кадре? (необязательно)"
              content={
                <Space direction="vertical">
                  <Input
                    placeholder="например: ночью, крупный план"
                    value={hint}
                    onChange={(e) => setHint(e.target.value)}
                    maxLength={300}
                  />
                  <Button type="primary" onClick={() => onRegenerate(scene.id, 'image', hint)}>
                    Перегенерировать
                  </Button>
                </Space>
              }
            >
              <Button disabled={disabled}>Новый кадр</Button>
            </Popover>
            <Tooltip title="Синтезировать озвучку заново (бесплатно)">
              <Button disabled={disabled} onClick={() => onRegenerate(scene.id, 'audio', '')}>
                Новая озвучка
              </Button>
            </Tooltip>
          </Space>
          {scene.error && <Alert type="error" showIcon message={scene.error} />}
        </Space>
      </div>
    </Card>
  )
}
