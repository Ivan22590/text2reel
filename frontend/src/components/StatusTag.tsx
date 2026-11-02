import { Tag } from 'antd'
import type { ProjectStatus } from '../api'

const LABELS: Record<ProjectStatus, [string, string]> = {
  draft: ['черновик', 'default'],
  analyzing: ['разбивка на сцены', 'processing'],
  scenes_ready: ['сцены готовы', 'blue'],
  generating: ['генерация', 'processing'],
  assets_ready: ['готово к монтажу', 'cyan'],
  rendering: ['монтаж', 'processing'],
  done: ['видео готово', 'green'],
  failed: ['ошибка', 'red'],
}

export default function StatusTag({ status }: { status: ProjectStatus }) {
  const [label, color] = LABELS[status] ?? [status, 'default']
  return <Tag color={color}>{label}</Tag>
}
