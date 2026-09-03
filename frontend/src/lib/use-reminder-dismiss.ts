import { useCallback, useSyncExternalStore } from "react"

// Отметка «выполнено» у строк уведомлений (очередь дня в сайдбаре).
// Независимо от одноразовых OnboardingHint (`use-onboarding-hints.ts`) — галочка должна
// работать всегда. Бакеты пересчитываются на бэке живьём (SQL по факту: ответил HR, прошёл
// собес и т.п.) — сама отметка чисто клиентская «спрячь эту строку сейчас», без бэкенда;
// если условие бакета снова станет истинным (например «Напомнить» через несколько дней
// тишины), строка может появиться заново — это ожидаемо, а не баг.

function dismissedKey(bucket: string, vacancyId: string): string {
  return `copilot.reminder.${bucket}.${vacancyId}.dismissed`
}

function readDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1"
  } catch {
    return false
  }
}

function writeDismissed(key: string) {
  try {
    localStorage.setItem(key, "1")
  } catch {
    /* ignore */
  }
}

let epoch = 0
const listeners = new Set<() => void>()

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function getSnapshot() {
  return epoch
}

function bump() {
  epoch += 1
  listeners.forEach((cb) => cb())
}

export function useReminderDismiss() {
  // Подписка на bump() — форсирует ре-рендер потребителей при отметке «выполнено».
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const isDismissed = useCallback(
    (bucket: string, vacancyId: string) => readDismissed(dismissedKey(bucket, vacancyId)),
    [],
  )

  const dismiss = useCallback((bucket: string, vacancyId: string) => {
    writeDismissed(dismissedKey(bucket, vacancyId))
    bump()
  }, [])

  return { isDismissed, dismiss }
}
