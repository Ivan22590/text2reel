import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Alert, Button, Card, Progress, Select, Space, Spin, Steps, Tabs, Typography } from 'antd'
import { api, type Meta, type Timeline } from '../api'
import { useProject } from '../hooks/useProject'
import RenderPanel from '../components/RenderPanel'
import BrandingPanel from '../components/BrandingPanel'
import SceneCard from '../components/SceneCard'
import StatusTag from '../components/StatusTag'
import TimelineView from '../components/TimelineView'

const STEP_LABELS: Record<string, string> = { scenes: 'Сцены', images: 'Кадры и озвучка', render: 'Монтаж' }

export default function ProjectPage() {
  const id = Number(useParams().id)
  const { project, progress, running, error, setError, reload, run } = useProject(id)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [tab, setTab] = useState('scenes')

  useEffect(() => {
    api.meta().then(setMeta).catch(() => undefined)
  }, [])

  const assetsKey = project?.scenes.map((s) => `${s.image_url}|${s.audio_url}`).join()
  const lookKey = project ? JSON.stringify([project.music, project.branding, project.format]) : ''
  useEffect(() => {
    if (project?.scenes.length) api.timeline(id).then(setTimeline).catch(() => setTimeline(null))
  }, [id, project?.scenes.length, assetsKey, lookKey])

  useEffect(() => {
    if (project?.status === 'done') setTab('video')
  }, [project?.status])

  if (!project) return error ? <Alert type="error" message={error} showIcon /> : <Spin />

  const status = progress?.status ?? project.status
  const hasScenes = project.scenes.length > 0
  const allAssets = hasScenes && project.scenes.every((s) => s.image_url && s.audio_url)
  const current = !hasScenes ? 0 : !allAssets ? 1 : status === 'done' ? 3 : 2

  const change = async (data: Parameters<typeof api.updateProject>[1]) => {
    try {
      await api.updateProject(id, data)
      await reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const missing = project.scenes.filter((s) => !(s.image_url && s.audio_url)).length

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
        <Space wrap>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {project.title || `Проект ${project.id}`}
          </Typography.Title>
          <StatusTag status={status} />
          <Typography.Text type="secondary">потрачено {project.cost_rub.toFixed(2)} ₽</Typography.Text>
        </Space>
        <Space wrap>
          <Select
            value={project.style}
            disabled={running}
            style={{ width: 150 }}
            onChange={(style) => void change({ style })}
            options={meta?.styles.map((s) => ({ value: s.id, label: s.name }))}
          />
          <Select
            value={project.format}
            disabled={running}
            style={{ width: 100 }}
            onChange={(format) => void change({ format })}
            options={meta?.formats.map((f) => ({ value: f.id, label: f.id }))}
          />
          <Select
            value={project.voice}
            disabled={running}
            style={{ width: 210 }}
            onChange={(voice) => void change({ voice })}
            options={meta?.voices.map((v) => ({ value: v.id, label: v.name }))}
          />
        </Space>
      </Space>

      <Card>
        <Steps
          current={current}
          items={[
            { title: 'Разбивка на сцены' },
            { title: 'Кадры и озвучка' },
            { title: 'Монтаж видео' },
            { title: 'Готово' },
          ]}
        />
        <Space wrap style={{ marginTop: 16 }}>
          <Button disabled={running} onClick={() => void run(() => api.analyze(id))}>
            {hasScenes ? 'Разбить заново' : 'Разбить на сцены'}
          </Button>
          <Button
            type={hasScenes && !allAssets ? 'primary' : 'default'}
            disabled={running || !hasScenes || allAssets}
            onClick={() => void run(() => api.generate(id))}
          >
            Сгенерировать {missing ? `(${missing})` : ''}
          </Button>
          <Button
            type={allAssets ? 'primary' : 'default'}
            disabled={running || !allAssets}
            onClick={() => void run(() => api.render(id))}
          >
            Собрать видео
          </Button>
        </Space>
        {running && progress && (
          <div style={{ marginTop: 16 }}>
            <Typography.Text>
              {STEP_LABELS[progress.step] ?? progress.step}: {progress.message}
            </Typography.Text>
            <Progress percent={Math.round(progress.progress)} status="active" />
          </div>
        )}
      </Card>

      {(error || progress?.error) && (
        <Alert type="error" showIcon closable message={error ?? progress?.error} onClose={() => setError(null)} />
      )}

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'scenes',
            label: `Сцены (${project.scenes.length})`,
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                {project.scenes.map((scene) => (
                  <SceneCard
                    key={`${scene.id}-${scene.narration}-${scene.visual_prompt}`}
                    scene={scene}
                    aspect={project.format}
                    disabled={running}
                    onChanged={() => void reload()}
                    onError={setError}
                    onRegenerate={(sceneId, target, hint) =>
                      void run(() => api.regenerateScene(sceneId, target, hint))
                    }
                  />
                ))}
              </Space>
            ),
          },
          {
            key: 'timeline',
            label: 'Таймлайн',
            children: timeline ? (
              <TimelineView
                timeline={timeline}
                onSceneClick={(sceneId) => {
                  setTab('scenes')
                  setTimeout(() => document.getElementById(`scene-${sceneId}`)?.scrollIntoView({ behavior: 'smooth' }), 50)
                }}
              />
            ) : (
              <Spin />
            ),
          },
          {
            key: 'style',
            label: 'Музыка и стиль',
            children: (
              <BrandingPanel project={project} meta={meta} disabled={running} onSaved={() => void reload()} onError={setError} />
            ),
          },
          { key: 'video', label: 'Видео', children: <RenderPanel project={project} /> },
          {
            key: 'script',
            label: 'Сценарий',
            children: <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{project.script}</Typography.Paragraph>,
          },
        ]}
      />
    </Space>
  )
}
