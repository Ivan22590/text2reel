import { Empty, Tooltip, Typography } from 'antd'
import type { Timeline } from '../api'

const PX_PER_SECOND = 48
const TRACK_HEIGHT = 44
const COLORS = ['#4f6bed', '#13a8a8', '#d4380d', '#7cb305', '#c41d7f', '#d48806']

// Timeline preview (FR-5.3): video, narration and subtitle tracks laid out exactly as the
// compositor will render them (data from GET /projects/{id}/timeline).
export default function TimelineView({ timeline, onSceneClick }: { timeline: Timeline; onSceneClick?: (id: number) => void }) {
  if (!timeline.ready) {
    return <Empty description="Таймлайн появится, когда у всех сцен будут кадр и озвучка" />
  }
  const width = Math.ceil(timeline.total * PX_PER_SECOND) + 16
  const ticks = Array.from({ length: Math.floor(timeline.total) + 1 }, (_, i) => i)
  const x = (seconds: number) => seconds * PX_PER_SECOND

  const track = (label: string, children: React.ReactNode) => (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
      <Typography.Text type="secondary" style={{ width: 90, flexShrink: 0, fontSize: 12 }}>
        {label}
      </Typography.Text>
      <div style={{ position: 'relative', height: TRACK_HEIGHT, width }}>{children}</div>
    </div>
  )

  return (
    <div style={{ overflowX: 'auto', paddingBottom: 8 }}>
      <Typography.Text type="secondary">
        Длительность: {timeline.total.toFixed(1)} с
        {timeline.music ? ` · музыка: «${timeline.music.title}»` : ' · без музыки'}
      </Typography.Text>
      <div style={{ marginTop: 8, minWidth: width + 90 }}>
        {track(
          'Время',
          ticks.map((t) => (
            <span key={t} style={{ position: 'absolute', left: x(t), top: 24, fontSize: 11, color: '#999' }}>
              |{t % 5 === 0 ? `${t}с` : ''}
            </span>
          )),
        )}
        {track(
          'Видео',
          timeline.scenes.map((s, i) => {
            const isCard = s.kind !== 'scene'
            const color = isCard ? '#8c8c8c' : COLORS[(s.index ?? 0) % COLORS.length]
            const label = isCard ? (s.kind === 'intro' ? 'Интро' : 'Аутро') : String((s.index ?? 0) + 1)
            return (
              <Tooltip key={`${s.kind}-${i}`} title={isCard ? `${label}: карточка с названием` : `Сцена ${label}: ${s.narration}`}>
                <div
                  onClick={() => s.id !== null && onSceneClick?.(s.id)}
                  style={{
                    position: 'absolute',
                    left: x(s.start),
                    width: x(s.clip) - 2,
                    height: TRACK_HEIGHT,
                    borderRadius: 4,
                    cursor: isCard ? 'default' : 'pointer',
                    overflow: 'hidden',
                    background: s.image_url ? `center / cover url(${s.image_url})` : color,
                    border: `2px solid ${color}`,
                    color: '#fff',
                    fontSize: 12,
                    textShadow: '0 0 3px #000',
                    padding: '2px 4px',
                  }}
                >
                  {label}
                </div>
              </Tooltip>
            )
          }),
        )}
        {track(
          'Озвучка',
          timeline.scenes
            .filter((s) => s.kind === 'scene')
            .map((s) => (
              <div
                key={s.id}
                style={{
                  position: 'absolute',
                  left: x(s.start),
                  width: x(s.voice),
                  top: 10,
                  height: TRACK_HEIGHT - 20,
                  borderRadius: 4,
                  background: COLORS[(s.index ?? 0) % COLORS.length],
                  opacity: 0.6,
                }}
              />
            )),
        )}
        {track(
          'Субтитры',
          timeline.cues.map((c, i) => (
            <Tooltip key={i} title={c.text}>
              <div
                style={{
                  position: 'absolute',
                  left: x(c.start),
                  width: Math.max(4, x(c.end - c.start) - 1),
                  top: 6,
                  height: TRACK_HEIGHT - 12,
                  borderRadius: 3,
                  background: '#fadb14',
                  fontSize: 10,
                  overflow: 'hidden',
                  whiteSpace: 'nowrap',
                  padding: '2px 3px',
                }}
              >
                {c.text}
              </div>
            </Tooltip>
          )),
        )}
      </div>
    </div>
  )
}
