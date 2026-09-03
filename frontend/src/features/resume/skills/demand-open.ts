import { useCallback, useSyncExternalStore } from "react"

// Общий спойлер блока «Спрос»: копия в «Балле резюме» (критерий «Навыки») и в секции
// «Навыки» должны открываться/закрываться вместе. localStorage переживает перезагрузку,
// подписчики в том же окне синхронизируются через этот стор — `usePersistedBoolean`
// этого не умеет (не ретранслирует set соседнему хуку).

const KEY = "copilot.resume.demand-open"

function read(): boolean {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw != null) return raw === "1"
  } catch {
    /* ignore */
  }
  return true
}

let open = read()
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function getDemandOpen(): boolean {
  return open
}

export function setDemandOpen(next: boolean | ((prev: boolean) => boolean)): void {
  const value = typeof next === "function" ? next(open) : next
  if (value === open) return
  open = value
  try {
    localStorage.setItem(KEY, value ? "1" : "0")
  } catch {
    /* ignore */
  }
  emit()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useDemandOpen() {
  const value = useSyncExternalStore(subscribe, getDemandOpen, () => true)
  const set = useCallback((next: boolean | ((prev: boolean) => boolean)) => {
    setDemandOpen(next)
  }, [])
  return [value, set] as const
}
