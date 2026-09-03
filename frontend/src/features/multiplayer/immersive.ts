import { useSyncExternalStore } from "react"

/**
 * «Иммерсивный режим» раздела: пока открыт живой стол, хром вокруг игры мешает —
 * шапка хаба с описанием и «Как играть» не нужна, левый рельс лучше свернуть.
 *
 * Модульный стор, а не контекст: флаг ставит страница глубоко в дереве (`MultiplayerPage`
 * по состоянию `WolvesLobby`), а читает его `AppShell` — общего родителя у них нет.
 * Уходит в false на размонтировании страницы (см. `MultiplayerPage`).
 */

let immersive = false
const listeners = new Set<() => void>()

export function setImmersive(next: boolean): void {
  if (immersive === next) return
  immersive = next
  for (const fn of listeners) fn()
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function getSnapshot(): boolean {
  return immersive
}

/** true — на экране живой стол, окружение стоит убрать. */
export function useImmersive(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
