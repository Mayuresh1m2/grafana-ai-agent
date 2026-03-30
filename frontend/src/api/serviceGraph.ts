export const NODE_TYPES = ['service', 'topic', 'queue', 'database', 'external'] as const
export type NodeType = typeof NODE_TYPES[number]

export const EDGE_TYPES = ['rest', 'grpc', 'publish', 'subscribe', 'reads', 'writes', 'calls'] as const
export type EdgeType = typeof EDGE_TYPES[number]

export const NODE_TYPE_LABELS: Record<NodeType, string> = {
  service:    'Service',
  topic:      'Topic',
  queue:      'Queue',
  database:   'Database',
  external:   'External',
}

export const EDGE_TYPE_LABELS: Record<EdgeType, string> = {
  rest:       'REST',
  grpc:       'gRPC',
  publish:    'Publish',
  subscribe:  'Subscribe',
  reads:      'Reads',
  writes:     'Writes',
  calls:      'Calls',
}

export interface GraphNode {
  id: string
  node_type: NodeType
  name: string
  description: string
  tech: string
  position_x: number
  position_y: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  edge_type: EdgeType
  label: string
}

export interface ServiceGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  updated_at: string
}

export async function fetchGraph(): Promise<ServiceGraph> {
  const res = await fetch('/api/v1/service-graph/')
  if (!res.ok) throw new Error(`Failed to load service graph: ${res.status}`)
  return res.json()
}

export async function saveGraph(nodes: GraphNode[], edges: GraphEdge[]): Promise<ServiceGraph> {
  const res = await fetch('/api/v1/service-graph/', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nodes, edges }),
  })
  if (!res.ok) throw new Error(`Failed to save service graph: ${res.status}`)
  return res.json()
}
