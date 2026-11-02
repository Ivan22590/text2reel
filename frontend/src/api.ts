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

export interface MusicTrack {
  id: string
  title: string
  artist: string
  duration: number
  moods: string[]
  url: string
}

export interface TemplateInfo {
  id: string
  name: string
  format: Format
  font: string
  subtitle_mode: 'phrase' | 'karaoke'
  transition: string
  transition_duration: number
  logo_position: LogoPosition
  intro_seconds: number
  outro_seconds: number
}

export type LogoPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'

export interface Meta {
  styles: Option[]
  formats: Option[]
  voices: Option[]
  cameras: string[]
  fonts: Option[]
  logo_positions: LogoPosition[]
  music: MusicTrack[]
  templates: TemplateInfo[]
}

// Per-project brand settings (null = the template default).
export interface Branding {
  font: string | null
  subtitle_color: string | null
  highlight_color: string | null
  accent_color: string
  background_color: string
  logo_position: LogoPosition | null
  logo_opacity: number | null
  intro_text: string
  outro_text: string
}

export interface BrandingOut extends Branding {
  has_logo: boolean
  logo_url: string | null
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
  draft: boolean
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
  music: string // 'auto' | 'none' | track id
  music_track: { id: string; title: string; artist: string } | null
  branding: BrandingOut
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
    kind: 'intro' | 'scene' | 'outro'
    id: number | null
    index: number | null
    start: number
    clip: number
    voice: number
    image_url: string | null
    narration: string
  }[]
  cues: { start: number; end: number; text: string }[]
  music: { id: string; title: string; artist: string } | null
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
  updateProject: (
    id: number,
    data: Partial<Pick<Project, 'title' | 'script' | 'style' | 'format' | 'voice' | 'music'>> & {
      branding?: Branding
    },
  ) => request<Project>('PATCH', `/projects/${id}`, data),
  uploadLogo: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Project>('POST', `/projects/${id}/logo`, form)
  },
  deleteLogo: (id: number) => request<Project>('DELETE', `/projects/${id}/logo`),
  deleteProject: (id: number) => request<void>('DELETE', `/projects/${id}`),
  analyze: (id: number) => request<Project>('POST', `/projects/${id}/analyze`),
  generate: (id: number) => request<Project>('POST', `/projects/${id}/generate`),
  render: (id: number, draft = false) => request<RenderJob>('POST', `/projects/${id}/render`, { draft }),
  timeline: (id: number) => request<Timeline>('GET', `/projects/${id}/timeline`),
  updateScene: (id: number, data: Partial<Pick<Scene, 'narration' | 'visual_prompt' | 'camera'>>) =>
    request<Scene>('PATCH', `/scenes/${id}`, data),
  regenerateScene: (id: number, target: 'image' | 'audio' | 'all', hint = '') =>
    request<Project>('POST', `/scenes/${id}/regenerate`, { target, hint }),
}

export function eventsUrl(projectId: number): string {
  return `/api/projects/${projectId}/events`
}
