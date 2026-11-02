export interface Health {
  status: string
  version: string
  env: string
  llm_model: string
  image_provider: string
}

export async function getHealth(): Promise<Health> {
  const resp = await fetch('/api/health')
  if (!resp.ok) throw new Error(`API ${resp.status}`)
  return resp.json()
}
