import { afterEach, describe, expect, it, vi } from "vitest"
import { getRumBuffer, resetRumForTests } from "@/lib/rum"
import { drainFrames, eventKind, isTerminalSse, streamSse, type SseEvent } from "./sse"

// Прогоняем буфер чанками, как ReadableStream, собираем события и остаток.
function collect(chunks: string[]): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = []
  let buffer = ""
  for (const ch of chunks) {
    buffer += ch
    buffer = drainFrames(buffer, (e) => events.push(e))
  }
  return { events, rest: buffer }
}

describe("drainFrames — единый SSE (A-14)", () => {
  it("парсит кадр event/data без id", () => {
    const { events, rest } = collect([
      'event: progress\ndata: {"type":"node_start","node":"chat"}\n\n',
    ])
    expect(rest).toBe("")
    expect(events).toEqual([
      {
        seq: null,
        event: "progress",
        data: { type: "node_start", node: "chat" },
      },
    ])
  })

  it("парсит кадр id/event/data", () => {
    const { events, rest } = collect([
      'id: 0\nevent: part\ndata: {"type":"token","text":"привет"}\n\n',
    ])
    expect(rest).toBe("")
    expect(events).toEqual([{ seq: 0, event: "part", data: { type: "token", text: "привет" } }])
  })

  it("склеивает кадр, пришедший двумя чанками", () => {
    const { events } = collect(["event: pa", 'rt\ndata: {"type":"token","text":"привет"}\n\n'])
    expect(events).toEqual([{ seq: null, event: "part", data: { type: "token", text: "привет" } }])
  })

  it("отдаёт несколько кадров и сохраняет незавершённый хвост", () => {
    const buf =
      'event: part\ndata: {"type":"token","text":"a"}\n\n' +
      'event: part\ndata: {"type":"token","text":"b"}\n\n' +
      "event: hi"
    const { events, rest } = collect([buf])
    expect(events.map((e) => e.event)).toEqual(["part", "part"])
    expect(rest).toBe("event: hi")
  })

  it("разбирает result + done канона A-14", () => {
    const frames =
      'event: part\ndata: {"type":"result","answer":"ок","follow_ups":["уточни"]}\n\n' +
      'event: done\ndata: {"type":"done","status":"done"}\n\n'
    const { events } = collect([frames])
    expect(events[0]).toMatchObject({
      event: "part",
      data: { type: "result", answer: "ок", follow_ups: ["уточни"] },
    })
    expect(events[1]).toMatchObject({
      event: "done",
      data: { type: "done", status: "done" },
    })
  })

  it("терпит \\r\\n и не валится на битом JSON", () => {
    const { events } = collect(["id: 9\r\nevent: error\r\ndata: not-json\r\n\n"])
    expect(events[0]).toMatchObject({
      seq: 9,
      event: "error",
      data: { raw: "not-json" },
    })
  })

  it("игнорирует heartbeat-комментарии", () => {
    const { events } = collect([
      ": heartbeat\n\n" +
        'event: progress\ndata: {"type":"progress","done":1,"total":3}\n\n' +
        ": heartbeat\n\n",
    ])
    expect(events).toHaveLength(1)
    expect(events[0].event).toBe("progress")
  })

  it("парсит screening part/done", () => {
    const frames =
      'id: 0\nevent: progress\ndata: {"type":"status","stage":"brief"}\n\n' +
      'id: 1\nevent: part\ndata: {"type":"pitch","partial":{"vacancy_id":"1"}}\n\n' +
      'id: 2\nevent: done\ndata: {"type":"done","pack":{"vacancy_id":"1"}}\n\n'
    const { events } = collect([frames])
    expect(events.map((e) => e.event)).toEqual(["progress", "part", "done"])
    expect(eventKind(events[1])).toBe("pitch")
    expect(isTerminalSse(events[2])).toBe(true)
  })
})

describe("eventKind / isTerminalSse", () => {
  it("берёт data.type, иначе event", () => {
    expect(eventKind({ seq: 0, event: "part", data: { type: "token", text: "x" } })).toBe("token")
    expect(eventKind({ seq: null, event: "done", data: {} })).toBe("done")
  })

  it("терминальные — done и error", () => {
    expect(isTerminalSse({ seq: 0, event: "done", data: {} })).toBe(true)
    expect(isTerminalSse({ seq: 0, event: "error", data: {} })).toBe(true)
    expect(isTerminalSse({ seq: 0, event: "part", data: {} })).toBe(false)
  })
})

describe("streamSse", () => {
  afterEach(() => {
    resetRumForTests()
    vi.unstubAllGlobals()
  })

  it("шлёт Accept: text/event-stream и Last-Event-ID, парсит поток", async () => {
    const frames =
      'id: 3\nevent: part\ndata: {"type":"token","text":"a"}\n\n' +
      'id: 4\nevent: done\ndata: {"type":"done","status":"done"}\n\n'
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(frames))
          controller.close()
        },
      }),
    })
    vi.stubGlobal("fetch", fetchMock)

    const events: SseEvent[] = []
    await streamSse("/api/chat/stream", {
      body: { message: "hi" },
      lastEventId: 2,
      timeoutMs: 0,
      onEvent: (e) => events.push(e),
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers.Accept).toBe("text/event-stream")
    expect(headers["Last-Event-ID"]).toBe("2")
    expect(events.map((e) => e.event)).toEqual(["part", "done"])
    expect(events[0].seq).toBe(3)
  })

  it("rumInteraction ставит ttfb / first_token / done (L-04)", async () => {
    const frames =
      'event: part\ndata: {"type":"token","text":"a"}\n\n' +
      'event: done\ndata: {"type":"done"}\n\n'
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(frames))
            controller.close()
          },
        }),
      }),
    )

    await streamSse("/api/chat/stream", {
      body: { message: "hi" },
      timeoutMs: 0,
      rumInteraction: "chat",
      onEvent: () => {},
    })

    expect(getRumBuffer().map((e) => e.kind)).toEqual(["rum_ttfb", "rum_first_token", "rum_done"])
  })
})
