// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { GameRoomSocket } from "./GameRoomSocket"

type Pub = { phase: string }
type Priv = { hand: string[] }

class FakeWS {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static last: FakeWS | null = null
  onopen: (() => void) | null = null
  onclose: ((ev: { code: number; reason: string }) => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  readyState = 0
  sent: string[] = []
  url: string
  constructor(url: string) {
    this.url = url
    FakeWS.last = this
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.readyState = 3
    this.onclose?.({ code: 1000, reason: "" })
  }
  open() {
    this.readyState = 1
    this.onopen?.()
  }
  emit(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
}

function makeSocket() {
  const socket = new GameRoomSocket<Pub, Priv>("ABC", {
    initialPublic: { phase: "lobby" },
    humanizeError: (d) => (d === "phase" ? "не та фаза" : d),
    storagePrefix: "test_",
  })
  socket.connect()
  FakeWS.last!.open()
  return socket
}

beforeEach(() => {
  ;(window as unknown as { WebSocket: unknown }).WebSocket = FakeWS
  FakeWS.last = null
})

afterEach(() => {
  vi.useRealTimers()
})

describe("GameRoomSocket — оптимистичное эхо интентов (Э19.5/19.6)", () => {
  it("sendIntent ставит pendingIntent и шлёт кадр, state_public его снимает", () => {
    const socket = makeSocket()
    socket.sendIntent({ type: "play_cards", card_ids: ["a"] })

    expect(socket.snapshot.pendingIntent?.intent).toEqual({
      type: "play_cards",
      card_ids: ["a"],
    })
    expect(FakeWS.last!.sent).toContain(
      JSON.stringify({ type: "intent", intent: { type: "play_cards", card_ids: ["a"] } }),
    )

    FakeWS.last!.emit({
      type: "state_public",
      state: { phase: "inspect" },
      server_now: new Date().toISOString(),
    })
    expect(socket.snapshot.pendingIntent).toBeNull()
  })

  it("error откатывает pending и запоминает причину рядом с интентом", () => {
    const socket = makeSocket()
    socket.sendIntent({ type: "stamp_candidate", candidate_id: "c1", stamp: "reject" })
    FakeWS.last!.emit({ type: "error", detail: "phase" })

    expect(socket.snapshot.pendingIntent).toBeNull()
    expect(socket.snapshot.intentError).toEqual({
      intent: { type: "stamp_candidate", candidate_id: "c1", stamp: "reject" },
      message: "не та фаза",
    })
    expect(socket.snapshot.lastError).toBe("не та фаза")
  })

  it("следующий state_public стирает inline-ошибку", () => {
    const socket = makeSocket()
    socket.sendIntent({ type: "mark_discrepancy", markers: ["a", "b"] })
    FakeWS.last!.emit({ type: "error", detail: "phase" })
    expect(socket.snapshot.intentError).not.toBeNull()

    FakeWS.last!.emit({
      type: "state_public",
      state: { phase: "lines" },
      server_now: new Date().toISOString(),
    })
    expect(socket.snapshot.intentError).toBeNull()
  })

  it("pending снимается по таймауту, если сервер молчит", () => {
    vi.useFakeTimers()
    const socket = makeSocket()
    socket.sendIntent({ type: "focus_candidate", candidate_id: "c1" })
    expect(socket.snapshot.pendingIntent).not.toBeNull()

    vi.advanceTimersByTime(6000)
    expect(socket.snapshot.pendingIntent).toBeNull()
  })

  it("error без своего интента в полёте не выдумывает intentError", () => {
    const socket = makeSocket()
    FakeWS.last!.emit({ type: "error", detail: "Хост снял вас со слота" })
    expect(socket.snapshot.intentError).toBeNull()
    expect(socket.snapshot.lastError).toBe("Хост снял вас со слота")
  })
})

describe("GameRoomSocket — единый конверт состояния (Э20.1/20.6)", () => {
  const frame = (over: Record<string, unknown> = {}) => ({
    type: "state",
    rev: 1,
    lobby: false,
    server_now: new Date().toISOString(),
    phase_ends_at: null,
    public: { phase: "inspect" },
    private: { hand: ["a"] },
    ...over,
  })

  it("state кладёт public и private за один emit", () => {
    const socket = makeSocket()
    let emits = 0
    socket.subscribe(() => {
      emits++
    })
    emits = 0

    FakeWS.last!.emit(frame())

    expect(emits).toBe(1)
    expect(socket.snapshot.public.phase).toBe("inspect")
    expect(socket.snapshot.private).toEqual({ hand: ["a"] })
  })

  it("state снимает оптимистичное эхо, как раньше это делал state_public", () => {
    const socket = makeSocket()
    socket.sendIntent({ type: "play_cards", card_ids: ["a"] })
    expect(socket.snapshot.pendingIntent).not.toBeNull()
    FakeWS.last!.emit(frame({ rev: 2 }))
    expect(socket.snapshot.pendingIntent).toBeNull()
  })

  it("отбрасывает кадр не новее уже применённого", () => {
    const socket = makeSocket()
    FakeWS.last!.emit(frame({ rev: 5, public: { phase: "lines" } }))
    FakeWS.last!.emit(frame({ rev: 4, public: { phase: "reveal" } }))
    expect(socket.snapshot.public.phase).toBe("lines")
    FakeWS.last!.emit(frame({ rev: 6, public: { phase: "ended" } }))
    expect(socket.snapshot.public.phase).toBe("ended")
  })

  it("welcome сбрасывает счётчик rev — сервер мог перезапуститься", () => {
    const socket = makeSocket()
    FakeWS.last!.emit(frame({ rev: 50, public: { phase: "lines" } }))
    FakeWS.last!.emit({
      type: "welcome",
      seat_token: "t",
      engine_seat_id: "hr",
      is_host: true,
      is_spectator: false,
    })
    FakeWS.last!.emit(frame({ rev: 1, public: { phase: "bulletin" } }))
    expect(socket.snapshot.public.phase).toBe("bulletin")
  })

  it("разбирает блок паузы из кадра state", () => {
    const socket = makeSocket()
    expect(socket.snapshot.pause).toEqual({ paused: false, by: "", resumingAt: null })

    FakeWS.last!.emit(frame({ rev: 2, pause: { paused: true, by: "Костя", resuming_at: null } }))
    expect(socket.snapshot.pause.paused).toBe(true)
    expect(socket.snapshot.pause.by).toBe("Костя")
    expect(socket.snapshot.pause.resumingAt).toBeNull()

    const soon = new Date(Date.now() + 3000).toISOString()
    FakeWS.last!.emit(frame({ rev: 3, pause: { paused: true, by: "Костя", resuming_at: soon } }))
    expect(socket.snapshot.pause.resumingAt).toBe(Date.parse(soon))

    FakeWS.last!.emit(frame({ rev: 4, pause: { paused: false } }))
    expect(socket.snapshot.pause.paused).toBe(false)
  })

  it("в лобби (без ключа private) прежнее приватное состояние не трётся", () => {
    const socket = makeSocket()
    FakeWS.last!.emit(frame({ rev: 1 }))
    expect(socket.snapshot.private).toEqual({ hand: ["a"] })
    FakeWS.last!.emit({
      type: "state",
      rev: 2,
      lobby: true,
      server_now: new Date().toISOString(),
      phase_ends_at: null,
      public: { phase: "lobby" },
    })
    expect(socket.snapshot.private).toEqual({ hand: ["a"] })
    expect(socket.snapshot.lobby).toBe(true)
  })
})
