/** Локальный кольцевой буфер UI-контекста для «Что делать?» — не уходит на бэкенд. */

const STORAGE_KEY = "copilot.ui-context.v1"
const MAX_EVENTS = 24

export type UiEventType = "nav" | "open_drawer" | "empty_state" | "error_toast"

export type UiEvent = {
  type: UiEventType
  at: number
  path?: string
  detail?: string
}

export type UiContextSnapshot = {
  events: UiEvent[]
}

function readEvents(): UiEvent[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as UiEvent[]) : []
  } catch {
    return []
  }
}

function writeEvents(events: UiEvent[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(events.slice(-MAX_EVENTS)))
  } catch {
    /* private mode / quota */
  }
}

export function recordUiEvent(event: Omit<UiEvent, "at"> & { at?: number }): void {
  const events = readEvents()
  events.push({ ...event, at: event.at ?? Date.now() })
  writeEvents(events)
}

export function getUiEvents(): UiEvent[] {
  return readEvents()
}

/** Чистить на logout — иначе на общей машине чужой контекст. */
export function clearUiContext(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export function recentPaths(limit = 5): string[] {
  const paths: string[] = []
  for (const e of readEvents().slice().reverse()) {
    if (e.type !== "nav" || !e.path) continue
    if (paths[paths.length - 1] === e.path) continue
    paths.push(e.path)
    if (paths.length >= limit) break
  }
  return paths
}
