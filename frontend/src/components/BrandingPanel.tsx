import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, ColorPicker, Descriptions, Input, Popconfirm, Row, Select, Slider, Space, Typography, Upload,
} from 'antd'
import { api, type Branding, type Meta, type Project } from '../api'

const MOOD_LABELS: Record<string, string> = {
  calm: 'спокойная',
  happy: 'весёлая',
  epic: 'эпичная',
  sad: 'грустная',
  tense: 'напряжённая',
  corporate: 'деловая',
  mysterious: 'загадочная',
}
const POSITION_LABELS: Record<string, string> = {
  'top-left': 'Слева сверху',
  'top-right': 'Справа сверху',
  'bottom-left': 'Слева снизу',
  'bottom-right': 'Справа снизу',
}
const TRANSITION_LABELS: Record<string, string> = {
  fade: 'плавное затухание',
  slideleft: 'сдвиг влево',
  wipeleft: 'шторка',
  circleopen: 'круг',
}

// Only the editable fields, in a fixed order, so that JSON comparison detects real changes.
const toBranding = (p: Project): Branding => ({
  font: p.branding.font,
  subtitle_color: p.branding.subtitle_color,
  highlight_color: p.branding.highlight_color,
  accent_color: p.branding.accent_color,
  background_color: p.branding.background_color,
  logo_position: p.branding.logo_position,
  logo_opacity: p.branding.logo_opacity,
  intro_text: p.branding.intro_text,
  outro_text: p.branding.outro_text,
})

interface Props {
  project: Project
  meta: Meta | null
  disabled: boolean
  onSaved: () => void
  onError: (message: string) => void
}

// Music, brand colours/fonts, logo and intro/outro cards (FR-6.2, FR-6.4).
// Changes apply to the next "Собрать видео": scenes and frames are not regenerated.
export default function BrandingPanel({ project, meta, disabled, onSaved, onError }: Props) {
  const [music, setMusic] = useState(project.music)
  const [brand, setBrand] = useState<Branding>(toBranding(project))
  const [saving, setSaving] = useState(false)
  const template = meta?.templates.find((t) => t.format === project.format)

  // Adopt server state after a save or when the project changes under us.
  const serverKey = JSON.stringify([project.music, toBranding(project)])
  useEffect(() => {
    setMusic(project.music)
    setBrand(toBranding(project))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey])

  const dirty = useMemo(() => JSON.stringify([music, brand]) !== serverKey, [music, brand, serverKey])
  const set = <K extends keyof Branding>(key: K, value: Branding[K]) => setBrand((b) => ({ ...b, [key]: value }))

  const save = async () => {
    setSaving(true)
    try {
      await api.updateProject(project.id, { music, branding: brand })
      onSaved()
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const trackLabel = (t: Meta['music'][number]) =>
    `${t.title} · ${MOOD_LABELS[t.moods[0]] ?? t.moods[0]} · ${Math.floor(t.duration / 60)}:${String(Math.round(t.duration % 60)).padStart(2, '0')}`
  const playing = music === 'none' ? null : music === 'auto' ? project.music_track?.id : music
  const playingTrack = meta?.music.find((t) => t.id === playing)

  const logoAction = async (action: () => Promise<unknown>) => {
    try {
      await action()
      onSaved()
    } catch (e) {
      onError((e as Error).message)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        type="info"
        showIcon
        message="Изменения применятся при следующей сборке видео. Кадры и озвучка заново не генерируются."
      />
      <Row gutter={[24, 24]}>
        <Col xs={24} lg={12}>
          <Card title="Фоновая музыка" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Select
                style={{ width: '100%' }}
                value={music}
                disabled={disabled}
                onChange={setMusic}
                options={[
                  { value: 'auto', label: 'Автоподбор по настроению сцен' },
                  { value: 'none', label: 'Без музыки' },
                  ...(meta?.music ?? []).map((t) => ({ value: t.id, label: trackLabel(t) })),
                ]}
              />
              {music === 'auto' && (
                <Typography.Text type="secondary">
                  {project.music_track
                    ? `Подобран трек: «${project.music_track.title}», ${project.music_track.artist}`
                    : 'Трек подберётся после разбивки на сцены'}
                </Typography.Text>
              )}
              {playingTrack && (
                <audio key={playingTrack.id} src={playingTrack.url} controls preload="none" style={{ width: '100%' }} />
              )}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Музыка под лицензией CC0, подробности в assets/music/LICENSES.md
              </Typography.Text>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title={template ? `Шаблон формата: ${template.name} (${template.format})` : 'Шаблон формата'} size="small">
            {template ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="Субтитры">
                  {template.subtitle_mode === 'karaoke' ? 'по словам, текущее слово подсвечено' : 'по фразам'}
                </Descriptions.Item>
                <Descriptions.Item label="Переход между сценами">
                  {TRANSITION_LABELS[template.transition] ?? template.transition}, {template.transition_duration} с
                </Descriptions.Item>
                <Descriptions.Item label="Шрифт по умолчанию">{template.font}</Descriptions.Item>
                <Descriptions.Item label="Логотип по умолчанию">{POSITION_LABELS[template.logo_position]}</Descriptions.Item>
                <Descriptions.Item label="Карточки">
                  интро {template.intro_seconds} с, аутро {template.outro_seconds} с
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Typography.Text type="secondary">Загрузка…</Typography.Text>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="Субтитры" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space wrap>
                <span>Шрифт</span>
                <Select
                  style={{ width: 190 }}
                  allowClear
                  placeholder={template ? `По шаблону (${template.font})` : 'По шаблону'}
                  value={brand.font ?? undefined}
                  disabled={disabled}
                  onChange={(v) => set('font', v ?? null)}
                  options={meta?.fonts.map((f) => ({ value: f.id, label: <span>{f.name}</span> }))}
                />
              </Space>
              <Space wrap>
                <span>Цвет текста</span>
                <ColorPicker
                  format="hex"
                  value={brand.subtitle_color ?? '#FFFFFF'}
                  disabled={disabled}
                  onChange={(_, hex) => set('subtitle_color', hex.toUpperCase())}
                />
                {template?.subtitle_mode === 'karaoke' && (
                  <>
                    <span>Подсветка слова</span>
                    <ColorPicker
                      format="hex"
                      value={brand.highlight_color ?? '#FFD700'}
                      disabled={disabled}
                      onChange={(_, hex) => set('highlight_color', hex.toUpperCase())}
                    />
                  </>
                )}
                <Button
                  size="small"
                  disabled={disabled}
                  onClick={() => setBrand((b) => ({ ...b, font: null, subtitle_color: null, highlight_color: null }))}
                >
                  Сбросить
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="Логотип" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space align="center" wrap>
                {project.branding.logo_url ? (
                  <img
                    src={project.branding.logo_url}
                    alt="Логотип"
                    style={{ height: 56, maxWidth: 160, objectFit: 'contain', background: '#8884', borderRadius: 6 }}
                  />
                ) : (
                  <Typography.Text type="secondary">Логотип не загружен</Typography.Text>
                )}
                <Upload
                  accept=".png,.jpg,.jpeg,.webp"
                  showUploadList={false}
                  disabled={disabled}
                  beforeUpload={(file) => {
                    void logoAction(() => api.uploadLogo(project.id, file))
                    return false
                  }}
                >
                  <Button disabled={disabled}>{project.branding.has_logo ? 'Заменить' : 'Загрузить (PNG, JPG, WebP до 2 МБ)'}</Button>
                </Upload>
                {project.branding.has_logo && (
                  <Popconfirm title="Удалить логотип?" onConfirm={() => void logoAction(() => api.deleteLogo(project.id))}>
                    <Button danger disabled={disabled}>
                      Удалить
                    </Button>
                  </Popconfirm>
                )}
              </Space>
              {project.branding.has_logo && (
                <>
                  <Space wrap>
                    <span>Положение</span>
                    <Select
                      style={{ width: 180 }}
                      allowClear
                      placeholder={template ? `По шаблону (${POSITION_LABELS[template.logo_position]})` : 'По шаблону'}
                      value={brand.logo_position ?? undefined}
                      disabled={disabled}
                      onChange={(v) => set('logo_position', v ?? null)}
                      options={meta?.logo_positions.map((p) => ({ value: p, label: POSITION_LABELS[p] }))}
                    />
                  </Space>
                  <div style={{ maxWidth: 320 }}>
                    <span>Непрозрачность: {Math.round((brand.logo_opacity ?? 0.9) * 100)}%</span>
                    <Slider
                      min={10}
                      max={100}
                      value={Math.round((brand.logo_opacity ?? 0.9) * 100)}
                      disabled={disabled}
                      onChange={(v) => set('logo_opacity', v / 100)}
                    />
                  </div>
                </>
              )}
            </Space>
          </Card>
        </Col>

        <Col xs={24}>
          <Card title="Карточки в начале и в конце (необязательно)" size="small">
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Input
                  addonBefore="Интро"
                  placeholder="Название проекта, например: Лисья история"
                  value={brand.intro_text}
                  maxLength={80}
                  disabled={disabled}
                  onChange={(e) => set('intro_text', e.target.value)}
                />
              </Col>
              <Col xs={24} md={12}>
                <Input
                  addonBefore="Аутро"
                  placeholder="Призыв, например: Подписывайтесь на канал!"
                  value={brand.outro_text}
                  maxLength={80}
                  disabled={disabled}
                  onChange={(e) => set('outro_text', e.target.value)}
                />
              </Col>
              <Col xs={24}>
                <Space wrap>
                  <span>Цвета фона карточки</span>
                  <ColorPicker
                    format="hex"
                    value={brand.background_color}
                    disabled={disabled}
                    onChange={(_, hex) => set('background_color', hex.toUpperCase())}
                  />
                  <span>→</span>
                  <ColorPicker
                    format="hex"
                    value={brand.accent_color}
                    disabled={disabled}
                    onChange={(_, hex) => set('accent_color', hex.toUpperCase())}
                  />
                  <Typography.Text type="secondary">карточка есть, только если текст не пустой</Typography.Text>
                </Space>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
      <Button type="primary" size="large" disabled={!dirty || disabled} loading={saving} onClick={() => void save()}>
        Сохранить музыку и стиль
      </Button>
    </Space>
  )
}
