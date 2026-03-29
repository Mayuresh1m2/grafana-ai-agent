export const QUERY_CATEGORIES = ['service', 'database', 'infrastructure', 'kubernetes', 'networking'] as const
export type QueryCategory = typeof QUERY_CATEGORIES[number]

export const CATEGORY_LABELS: Record<QueryCategory, string> = {
  service:        'Service',
  database:       'Database',
  infrastructure: 'Infrastructure',
  kubernetes:     'Kubernetes',
  networking:     'Networking',
}

export interface QueryExample {
  id: string
  title: string
  description: string
  query_type: 'loki' | 'prometheus'
  category: QueryCategory
  template: string
  tags: string[]
  placeholders: string[]
  created_at: string
}

export interface ExampleCreate {
  title: string
  description: string
  query_type: 'loki' | 'prometheus'
  category: QueryCategory
  template: string
  tags: string[]
  placeholders: string[]
}

/** Extract every unique {{key}} placeholder name from a template string. */
export function detectPlaceholders(template: string): string[] {
  const matches = [...template.matchAll(/\{\{(\w+)\}\}/g)]
  return [...new Set(matches.map(m => m[1]))]
}

function _qs(grafana_url: string): string {
  return grafana_url ? `?grafana_url=${encodeURIComponent(grafana_url)}` : ''
}

export async function fetchExamples(grafana_url = ''): Promise<QueryExample[]> {
  const res = await fetch(`/api/v1/examples/${_qs(grafana_url)}`)
  if (!res.ok) throw new Error(`Failed to fetch examples: ${res.status}`)
  return res.json()
}

export async function createExample(body: ExampleCreate, grafana_url = ''): Promise<QueryExample> {
  const res = await fetch(`/api/v1/examples/${_qs(grafana_url)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Failed to create example: ${res.status}`)
  return res.json()
}

export async function deleteExample(id: string, grafana_url = ''): Promise<void> {
  const res = await fetch(`/api/v1/examples/${id}${_qs(grafana_url)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete example: ${res.status}`)
}

export async function searchExamples(query: string, grafana_url = '', top_k = 3): Promise<QueryExample[]> {
  const res = await fetch(`/api/v1/examples/search${_qs(grafana_url)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k }),
  })
  if (!res.ok) throw new Error(`Failed to search examples: ${res.status}`)
  return res.json()
}
