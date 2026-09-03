import { drainFrames, type SseEvent } from "@/api/sse"

const BASE = import.meta.env.VITE_API_BASE ?? ""
const RECONNECT_DELAY_MS = 3_000

export type LiveEventPayload = {
  type: string
  subject?: string
  fields?: Record<string, unknown>
}

type LiveEventListener = (payload: LiveEventPayload) => void
type ConnectionListener = (connected: boolean) => void
type ReconnectListener = () => void

/**
 * Постоянное SSE-соединение `GET /api/events/stream` (L-45): один канал на всё приложение —
 * доменные события (VacancyScored, ApplicationStageChanged, …) приходят пока открыта вкладка,
 * фронт сам решает по `type`, какие query keys инвалидировать (см. `use-live-invalidation.ts`).
 *
 * Разрыв (сеть, рестарт бэка) — короткая пауза и переподключение по кругу; между попытками
 * `isConnected()` отдаёт `false` — потребители (`use-jobs`/`use-market-*`/`use-stack-demand`)
 * включают `refetchInterval` как запасной поллинг, пока канал не поднимется обратно.
 */
export class LiveEventsChannel {
  private listeners = new Set<LiveEventListener>()
  private connectionListeners = new Set<ConnectionListener>()
  private reconnectListeners = new Set<ReconnectListener>()
  private connected = false
  private everConnected = false
  private stopped = true
  private controller: AbortController | null = null

  start(): void {
    if (!this.stopped) return
    this.stopped = false
    void this.loop()
  }

  stop(): void {
    this.stopped = true
    this.controller?.abort()
    this.controller = null
    this.setConnected(false)
  }

  onEvent(listener: LiveEventListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** Колбэк зовётся сразу с текущим состоянием, дальше — на каждой смене. */
  onConnectionChange(listener: ConnectionListener): () => void {
    this.connectionListeners.add(listener)
    listener(this.connected)
    return () => this.connectionListeners.delete(listener)
  }

  /**
   * F-05: зовётся на КАЖДОМ подключении, кроме самого первого — то есть именно на реконнекте
   * после разрыва (сеть, рестарт бэка). Бэк реплей не хранит, так что единственный дешёвый
   * способ не потерять пропущенные события — разовый полный рефреш у потребителя.
   */
  onReconnect(listener: ReconnectListener): () => void {
    this.reconnectListeners.add(listener)
    return () => this.reconnectListeners.delete(listener)
  }

  isConnected(): boolean {
    return this.connected
  }

  /**
   * F-06: очередь на бэке — 200 кадров на соединение (`core/platform/events/live.py`); фоновая
   * вкладка не читает поток, очередь переполняется, и события молча теряются (лог-предупреждение
   * на бэке, реплея нет). Раз соединение всё равно бесполезно в фоне — закрываем его сами:
   * `hidden` → `stop()`, `visible` → `start()`. Возврат — обычный реконнект, полный рефреш
   * добивает пропущенное через `onReconnect` (F-05), отдельного вызова здесь не нужно.
   */
  bindVisibilityPause(): () => void {
    const handleVisibility = (): void => {
      if (document.hidden) {
        this.stop()
      } else {
        this.start()
      }
    }
    document.addEventListener("visibilitychange", handleVisibility)
    return () => document.removeEventListener("visibilitychange", handleVisibility)
  }

  private setConnected(value: boolean): void {
    if (this.connected === value) return
    this.connected = value
    if (value) {
      if (this.everConnected) {
        for (const listener of this.reconnectListeners) listener()
      }
      this.everConnected = true
    }
    for (const listener of this.connectionListeners) listener(value)
  }

  private async loop(): Promise<void> {
    while (!this.stopped) {
      const controller = new AbortController()
      this.controller = controller
      try {
        await this.connectOnce(controller.signal)
      } catch {
        // сеть/401/сервер лёг — тихо переподключаемся ниже, экран не должен на это реагировать
      }
      this.setConnected(false)
      if (this.stopped) return
      await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS))
    }
  }

  private async connectOnce(signal: AbortSignal): Promise<void> {
    const response = await fetch(`${BASE}/api/events/stream`, {
      credentials: "include",
      headers: { Accept: "text/event-stream" },
      signal,
    })
    if (!response.ok || !response.body) return
    this.setConnected(true)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        buffer = drainFrames(buffer, (e: SseEvent) => this.dispatch(e))
      }
    } finally {
      reader.releaseLock()
    }
  }

  private dispatch(e: SseEvent): void {
    const data = e.data as LiveEventPayload
    if (typeof data.type !== "string") return
    for (const listener of this.listeners) listener(data)
  }
}

export const liveEvents = new LiveEventsChannel()
