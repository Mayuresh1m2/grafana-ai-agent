export const ENTITY_TYPES = ['service', 'namespace', 'database', 'deployment'] as const
export type EntityType = typeof ENTITY_TYPES[number]

export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  service:    'Service',
  namespace:  'Namespace',
  database:   'Database',
  deployment: 'Deployment',
}

export interface ServiceEntity {
  id: string
  name: string
  namespace: string
  entity_type: EntityType
  aliases: string[]
  description: string
  created_at: string
}

export interface EntityCreate {
  name: string
  namespace: string
  entity_type: EntityType
  aliases: string[]
  description: string
}

export async function fetchEntities(): Promise<ServiceEntity[]> {
  const res = await fetch('/api/v1/entities/')
  if (!res.ok) throw new Error(`Failed to fetch entities: ${res.status}`)
  return res.json()
}

export async function createEntity(body: EntityCreate): Promise<ServiceEntity> {
  const res = await fetch('/api/v1/entities/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Failed to create entity: ${res.status}`)
  return res.json()
}

export async function deleteEntity(id: string): Promise<void> {
  const res = await fetch(`/api/v1/entities/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete entity: ${res.status}`)
}
