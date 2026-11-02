// Typed client for the backend API (docs/ARCHITECTURE.md §4).

export type Format = '9:16' | '16:9' | '1:1'
export type ProjectStatus =
  | 'draft'
  | 'analyzing'
  | 'scenes_ready'
  | 'generating'
  | 'assets_ready'
  | 'rendering'
  | 'done'
  | 'failed'

export const RUNNING: ProjectStatus[] = ['analyzing', 'generating', 'rendering']

export interface Option {
  id: string
  name: string
}

export interface Meta {
  styles: Option[]
  formats: Option[]
  voices: Option[]
  cameras: string[]
}

export interface Scene {
  id: number
  index: number
  narration: string
  visual_prompt: string
  mood: string
  camera: string
  status: string
  error: string | null
  duration: number | null
  image_url: string | null
  audio_url: string | null
}

export interface RenderJob {
  id: number
  format: Format
  status: string
  error: string | null
  video_url: string | null
  srt_url: string | null
  started_at: string | null
  finished_at: string | null
  cost_rub: number
}

export interface Project {
  id: number
  title: string
  script: string
  style: string
  format: Format
  voice: string
  status: ProjectStatus
  step: string
  progress: number
  message: string
  error: string | null
  cost_rub: number
  created_at: string
  scenes: Scene[]
  renders: RenderJob[]
}

export interface Progress {
  status: ProjectStatus
  step: string
  progress: number
  message: string
  error: string | null
}

export interface Timeline {
  ready: boolean
  total: number
  transition?: number
  scenes: {
    id: number
    index: number
    start: number
    clip: number
    voice: number
    image_url: string | null
    narration: string
  }[]
  cues: { start: number; end: number; text: string }[]
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: {} }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const resp = await fetch(`/api${path}`, init)
  if (!resp.ok) {
    let message = `Ошибка ${resp.status}`
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, message)
  }
  return resp.status === 204 ? (undefined as T) : resp.json()
}

export const api = {
  login: (username: string, password: string) =>
    request<{ username: string }>('POST', '/auth/login', { username, password }),
  logout: () => request<void>('POST', '/auth/logout'),
  me: () => request<{ username: string }>('GET', '/auth/me'),
  meta: () => request<Meta>('GET', '/meta'),
  parseScript: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ text: string }>('POST', '/scripts/parse', form)
  },
  projects: () => request<Project[]>('GET', '/projects'),
  project: (id: number) => request<Project>('GET', `/projects/${id}`),
  createProject: (data: { title?: string; script: string; style: string; format: Format; voice: string }) =>
    request<Project>('POST', '/projects', data),
  updateProject: (id: number, data: Partial<Pick<Project, 'title' | 'script' | 'style' | 'format' | 'voice'>>) =>
    request<Project>('PATCH', `/projects/${id}`, data),
  deleteProject: (id: number) => request<void>('DELETE', `/projects/${id}`),
  analyze: (id: number) => request<Project>('POST', `/projects/${id}/analyze`),
  generate: (id: number) => request<Project>('POST', `/projects/${id}/generate`),
  render: (id: number) => request<RenderJob>('POST', `/projects/${id}/render`, {}),
  timeline: (id: number) => request<Timeline>('GET', `/projects/${id}/timeline`),
  updateScene: (id: number, data: Partial<Pick<Scene, 'narration' | 'visual_prompt' | 'camera'>>) =>
    request<Scene>('PATCH', `/scenes/${id}`, data),
  regenerateScene: (id: number, target: 'image' | 'audio' | 'all', hint = '') =>
    request<Project>('POST', `/scenes/${id}/regenerate`, { target, hint }),
}

export function eventsUrl(projectId: number): string {
  return `/api/projects/${projectId}/events`
}
