// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { LiveEventsChannel } from "./live-events"

function bodyFrom(text: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text))
      controller.close()
    },
  })
}

describe("LiveEventsChannel (L-45)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("подключается, разбирает part-кадры и рассылает слушателям", async () => {
    const frames = 'event: part\ndata: {"type":"VacancyScored","subject":"v1"}\n\n'
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: bodyFrom(frames) })
    vi.stubGlobal("fetch", fetchMock)

    const channel = new LiveEventsChannel()
    const events: unknown[] = []
    const unsubEvent = channel.onEvent((p) => events.push(p))
    const connections: boolean[] = []
    const unsubConn = channel.onConnectionChange((c) => connections.push(c))

    channel.start()
    await vi.waitFor(() => expect(events).toHaveLength(1))

    expect(events[0]).toEqual({ type: "VacancyScored", subject: "v1" })
    expect(connections[0]).toBe(false) // начальное состояние при подписке
    expect(connections).toContain(true)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/events/stream"),
      expect.objectContaining({
        credentials: "include",
        headers: { Accept: "text/event-stream" },
      }),
    )

    channel.stop()
    unsubEvent()
    unsubConn()
  })

  it("игнорирует кадры без строкового type", async () => {
    const frames = 'event: part\ndata: {"subject":"v1"}\n\n'
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body: bodyFrom(frames) }))

    const channel = new LiveEventsChannel()
    const events: unknown[] = []
    channel.onEvent((p) => events.push(p))
    channel.start()

    // Дать микротаскам стрима прогнаться, ничего не должно прилететь.
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(events).toHaveLength(0)
    channel.stop()
  })

  it("после разрыва соединения помечает connected=false и переподключается", async () => {
    vi.useFakeTimers()
    let calls = 0
    const fetchMock = vi.fn().mockImplementation(() => {
      calls += 1
      return Promise.resolve({ ok: true, body: bodyFrom("") })
    })
    vi.stubGlobal("fetch", fetchMock)

    const channel = new LiveEventsChannel()
    const connections: boolean[] = []
    channel.onConnectionChange((c) => connections.push(c))
    channel.start()

    // Первый цикл: connect → connected=true → тело пустое (done сразу) → connected=false.
    await vi.waitFor(() => expect(connections).toEqual([false, true, false]))
    expect(calls).toBe(1)

    await vi.advanceTimersByTimeAsync(3_000)
    await vi.waitFor(() => expect(calls).toBe(2))

    channel.stop()
  })

  it("stop() обрывает соединение и не переподключается", async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: bodyFrom("") })
    vi.stubGlobal("fetch", fetchMock)

    const channel = new LiveEventsChannel()
    channel.start()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    channel.stop()
    expect(channel.isConnected()).toBe(false)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("реконнект (F-05): onReconnect не зовётся на первом подключении, зовётся на втором+", async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: bodyFrom("") })
    vi.stubGlobal("fetch", fetchMock)

    const channel = new LiveEventsChannel()
    const reconnects: number[] = []
    channel.onReconnect(() => reconnects.push(reconnects.length))
    channel.start()

    // Первый цикл: connect → connected=true → тело пустое → connected=false. Это не реконнект.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(channel.isConnected()).toBe(false))
    expect(reconnects).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(3_000)
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(reconnects).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(3_000)
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(reconnects).toHaveLength(2)

    channel.stop()
  })

  it("F-06: скрытая вкладка останавливает соединение, видимая — переподключает", async () => {
    vi.useFakeTimers()
    // Новый стрим на каждый вызов — переиспользованный уже залочен предыдущим getReader().
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        body: new ReadableStream({
          start() {
            // ничего не шлём и не закрываем — как долгоживущее SSE-соединение
          },
        }),
      }),
    )
    vi.stubGlobal("fetch", fetchMock)
    const hidden = vi.spyOn(document, "hidden", "get")

    const channel = new LiveEventsChannel()
    const unbind = channel.bindVisibilityPause()
    channel.start()
    await vi.waitFor(() => expect(channel.isConnected()).toBe(true))
    expect(fetchMock).toHaveBeenCalledTimes(1)

    hidden.mockReturnValue(true)
    document.dispatchEvent(new Event("visibilitychange"))
    expect(channel.isConnected()).toBe(false)

    // В фоне не переподключается сам — таймер реконнекта не запускается после stop().
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    hidden.mockReturnValue(false)
    document.dispatchEvent(new Event("visibilitychange"))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    unbind()
    channel.stop()
  })

  it("F-06: unbind снимает подписку на visibilitychange", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        body: new ReadableStream({
          start() {
            // ничего не шлём и не закрываем
          },
        }),
      }),
    )
    vi.stubGlobal("fetch", fetchMock)
    const hidden = vi.spyOn(document, "hidden", "get")

    const channel = new LiveEventsChannel()
    const unbind = channel.bindVisibilityPause()
    channel.start()
    await vi.waitFor(() => expect(channel.isConnected()).toBe(true))

    unbind()
    hidden.mockReturnValue(true)
    document.dispatchEvent(new Event("visibilitychange"))
    expect(channel.isConnected()).toBe(true)

    channel.stop()
  })

  it("не открывает второе соединение при повторном start()", async () => {
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise(() => {
          // висит вечно — как долгоживущее SSE-соединение
        }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const channel = new LiveEventsChannel()
    channel.start()
    channel.start()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    channel.stop()
  })
})
