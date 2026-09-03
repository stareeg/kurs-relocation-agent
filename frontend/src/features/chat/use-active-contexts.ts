import { useCallback, useEffect, useState } from "react"

const STORAGE_KEY = "copilot.active-contexts"

function readStored(): number[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed)
      ? parsed.filter((v: unknown): v is number => typeof v === "number")
      : []
  } catch {
    return []
  }
}

let ids: number[] = readStored()
const listeners = new Set<(next: number[]) => void>()

function commit(next: number[]) {
  ids = next
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l(next))
}

// UX4-16: контекст включается тогглом в списке «Контексты» и подмешивается в КАЖДЫЙ вопрос
// ассистенту по ЛЮБОЙ вакансии, пока не выключен — не привязан к одному сообщению. Модульный
// синглтон + подписчики (не только localStorage) — тоггл в сайдбаре должен сразу видеть уже
// открытый композер диалога, это разные React-поддеревья одной страницы.
export function useActiveContexts() {
  const [state, setState] = useState(ids)

  useEffect(() => {
    listeners.add(setState)
    return () => {
      listeners.delete(setState)
    }
  }, [])

  const toggle = useCallback((id: number) => {
    commit(ids.includes(id) ? ids.filter((v) => v !== id) : [...ids, id])
  }, [])

  const isActive = useCallback((id: number) => state.includes(id), [state])

  return { activeIds: state, toggle, isActive }
}
