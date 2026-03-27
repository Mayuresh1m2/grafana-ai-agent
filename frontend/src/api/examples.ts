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

export const PLACEHOLDER_KEYS = ['namespace', 'app', 'environment'] as const
export type PlaceholderKey = typeof PLACEHOLDER_KEYS[number]

export async function fetchExamples(): Promise<QueryExample[]> {
  const res = await fetch('/api/v1/examples/')
  if (!res.ok) throw new Error(`Failed to fetch examples: ${res.status}`)
  return res.json()
}

export async function createExample(body: ExampleCreate): Promise<QueryExample> {
  const res = await fetch('/api/v1/examples/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Failed to create example: ${res.status}`)
  return res.json()
}

export async function deleteExample(id: string): Promise<void> {
  const res = await fetch(`/api/v1/examples/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete example: ${res.status}`)
}

export async function searchExamples(query: string, top_k = 3): Promise<QueryExample[]> {
  const res = await fetch('/api/v1/examples/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k }),
  })
  if (!res.ok) throw new Error(`Failed to search examples: ${res.status}`)
  return res.json()
}
