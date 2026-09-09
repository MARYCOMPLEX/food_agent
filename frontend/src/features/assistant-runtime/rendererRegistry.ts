import type {
  AssistantUiBlockRegistry,
  AssistantUiBlockRendererEntry,
} from './types'

/**
 * Renderer registry owned by the application. The backend only sends a
 * renderer key; it can never select a component or import executable code.
 */
export function createUiBlockRegistry(
  initialEntries: AssistantUiBlockRendererEntry[] = [],
): AssistantUiBlockRegistry {
  const entries = new Map<string, AssistantUiBlockRendererEntry>()
  for (const entry of initialEntries) entries.set(entry.renderer, entry)

  return {
    get: renderer => entries.get(renderer),
    register: (entry) => {
      entries.set(entry.renderer, entry)
    },
    unregister: (renderer) => {
      entries.delete(renderer)
    },
    list: () => [...entries.values()],
  }
}
