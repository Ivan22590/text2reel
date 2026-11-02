import { Button, Empty, List, Space, Tag, Typography } from 'antd'
import type { Project } from '../api'

// Result player, downloads and render history (FR-5.5).
export default function RenderPanel({ project }: { project: Project }) {
  const done = project.renders.filter((r) => r.status === 'done' && r.video_url)
  const latest = done[0]
  const [w, h] = project.format.split(':').map(Number)

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {latest ? (
        <div style={{ maxWidth: w > h ? 820 : 360 }}>
          <video
            key={latest.video_url}
            src={latest.video_url ?? undefined}
            controls
            style={{ width: '100%', aspectRatio: `${w} / ${h}`, background: '#000', borderRadius: 8 }}
          />
          <Space style={{ marginTop: 8 }}>
            <Button type="primary" href={latest.video_url ?? undefined} download={`text2reel-${project.id}.mp4`}>
              Скачать MP4
            </Button>
            {latest.srt_url && (
              <Button href={latest.srt_url} download={`text2reel-${project.id}.srt`}>
                Скачать субтитры (SRT)
              </Button>
            )}
          </Space>
        </div>
      ) : (
        <Empty description="Видео ещё не собрано" />
      )}
      {project.renders.length > 0 && (
        <List
          size="small"
          header={<Typography.Text strong>История рендеров</Typography.Text>}
          dataSource={project.renders}
          renderItem={(r) => (
            <List.Item>
              <Space wrap>
                <span>#{r.id}</span>
                <Tag>{r.format}</Tag>
                <Tag color={r.status === 'done' ? 'green' : r.status === 'failed' ? 'red' : 'blue'}>{r.status}</Tag>
                {r.started_at && r.finished_at && (
                  <span>
                    {((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000).toFixed(0)} с
                  </span>
                )}
                {r.error && <Typography.Text type="danger">{r.error}</Typography.Text>}
                {r.video_url && <a href={r.video_url}>видео</a>}
              </Space>
            </List.Item>
          )}
        />
      )}
    </Space>
  )
}
