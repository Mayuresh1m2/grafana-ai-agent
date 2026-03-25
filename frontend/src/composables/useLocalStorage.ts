import { ref, watch } from 'vue'
import type { Ref } from 'vue'

/**
 * Reactive ref backed by localStorage.
 * Serialises with JSON.stringify / JSON.parse.
 */
export function useLocalStorage<T>(key: string, defaultValue: T): Ref<T> {
  const stored = localStorage.getItem(key)
  const initial: T = stored != null
    ? (JSON.parse(stored) as T)
    : defaultValue

  const state = ref<T>(initial) as Ref<T>

  watch(state, (val) => {
    try {
      localStorage.setItem(key, JSON.stringify(val))
    } catch {
      // Quota exceeded — silently ignore
    }
  }, { deep: true })

  return state
}
