import { useCallback, useEffect, useRef, useState } from 'react'
import { api, eventsUrl, RUNNING, type Progress, type Project } from '../api'

// Loads a project and follows job progress over SSE while a job is running (FR-5.4).
export function useProject(id: number) {
  const [project, setProject] = useState<Project | null>(null)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const source = useRef<EventSource | null>(null)

  const reload = useCallback(async () => {
    try {
      const data = await api.project(id)
      setProject(data)
      setProgress({
        status: data.status,
        step: data.step,
        progress: data.progress,
        message: data.message,
        error: data.error,
      })
      setError(null)
      return data
    } catch (e) {
      setError((e as Error).message)
      return null
    }
  }, [id])

  const follow = useCallback(() => {
    source.current?.close()
    const es = new EventSource(eventsUrl(id))
    source.current = es
    es.onmessage = (event) => {
      const state = JSON.parse(event.data) as Progress
      setProgress(state)
      if (!RUNNING.includes(state.status)) {
        es.close()
        void reload()
      }
    }
    es.onerror = () => {
      es.close()
      void reload()
    }
  }, [id, reload])

  useEffect(() => {
    void reload().then((data) => {
      if (data && RUNNING.includes(data.status)) follow()
    })
    return () => source.current?.close()
  }, [reload, follow])

  // Starts a background job and subscribes to its progress.
  const run = useCallback(
    async (start: () => Promise<unknown>) => {
      try {
        await start()
        follow()
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [follow],
  )

  const running = progress ? RUNNING.includes(progress.status) : false
  return { project, setProject, progress, running, error, setError, reload, run }
}
