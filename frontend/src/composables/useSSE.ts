import type { SSEEvent } from '@/types/chat'

/**
 * Connects to an SSE stream via fetch + ReadableStream (supports POST).
 * Falls back gracefully if the body can't be read.
 *
 * @returns cancel function — call to abort the active stream
 */
export function useSSE(
  url: string,
  payload: Record<string, unknown>,
  onEvent: (event: SSEEvent) => void,
  onDone: () => void,
  onError: (err: Error) => void,
): () => void {
  const controller = new AbortController()

  ;(async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('Response body is not readable')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE lines are delimited by "\n\n"
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''   // keep incomplete chunk

        for (const part of parts) {
          const dataLine = part
            .split('\n')
            .find((l) => l.startsWith('data: '))
          if (!dataLine) continue

          const raw = dataLine.slice(6).trim()
          if (!raw || raw === '[DONE]') continue

          try {
            const event = JSON.parse(raw) as SSEEvent
            if (event.type === 'done') {
              onDone()
              return
            }
            onEvent(event)
          } catch {
            // Malformed JSON — skip
          }
        }
      }

      onDone()
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      onError(err instanceof Error ? err : new Error(String(err)))
    }
  })()

  return () => controller.abort()
}
