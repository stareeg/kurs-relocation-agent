/**
 * Клиент комнаты раздела «Мультиплеер» — generic-половина (Э17.7).
 *
 * Знает про транспорт хаба и ничего про игру: коннект, auth по cookie, auto-reconnect с
 * backoff, heartbeat, персистентность seat_token, разбор служебных кадров
 * (`welcome` / `seat_assigned` / `state` / `error`), поправка на расхождение часов с сервером.
 * `state` — единый конверт `{public, private, rev}` (Э20.1): одно изменение = один коммит.
 * Пара `state_public` / `state_private` осталась разобранной на переходный период (откат
 * сервера / кадр в полёте со старой сборки).
 *
 * Форма игрового состояния приходит параметрами типа — сама она у каждой игры своя и этому
 * классу неинтересна. Тексты ошибок игрок должен читать на языке своей игры, поэтому
 * `humanizeError` передаётся снаружи.
 */

export type GameRoomSnapshot<TPublic, TPrivate> = {
  lobby: boolean
  serverNow: number
  phaseEndsAt: number | null
  public: TPublic
  private: TPrivate | null
  seatToken: string | null
  engineSeatId: string | null
  isHost: boolean
  isSpectator: boolean
  lastError: string | null
  connected: boolean
  /** Идёт попытка reconnect (не «вечный offline»). */
  reconnecting: boolean
  /**
   * Пауза (Dota-стиль): стол заморожен, любой участник ставит и снимает. `resumingAt` != null —
   * идёт 3-сек отсчёт продолжения. `paused` false → остальные поля игнорировать.
   */
  pause: { paused: boolean; by: string; resumingAt: number | null }
  /**
   * Свой интент ушёл в сокет и ещё не подтверждён сервером (Э19.5). Экран показывает «принято,
   * в пути» и блокирует повторный клик, не предсказывая результат — правду по-прежнему
   * приносит кадр состояния. Снимается первым же `state`/`error` или по таймауту.
   */
  pendingIntent: { intent: Record<string, unknown>; at: number } | null
  /**
   * Последний свой интент, который сервер отверг `{type:"error"}` (Э19.6) — причину показываем
   * рядом с местом действия, а не только общим баннером. Снимается следующим кадром состояния.
   */
  intentError: { intent: Record<string, unknown>; message: string } | null
}

export type GameRoomSeed = {
  isHost?: boolean
  engineSeatId?: string | null
  isSpectator?: boolean
}

export type GameRoomOptions<TPublic> = GameRoomSeed & {
  /** Состояние до первого кадра с сервера — форма своя у каждой игры. */
  initialPublic: TPublic
  /** Технический `detail` от сервера → текст для игрока. */
  humanizeError: (detail: string) => string
  /** Префикс ключа в sessionStorage: столы разных игр не должны толкаться. */
  storagePrefix: string
}

type Listener<TPublic, TPrivate> = (snap: GameRoomSnapshot<TPublic, TPrivate>) => void

const MAX_RECONNECT_ATTEMPTS = 8
const RECONNECT_BASE_MS = 600
const RECONNECT_MAX_MS = 12_000
/**
 * Heartbeat клиент→сервер. Наш nginx сокет не рвёт: uvicorn сам шлёт протокольный ping раз
 * в ~20с (замерено на проде — фрейм с опкодом 0x9), и это сбрасывает его `proxy_read_timeout`.
 * Но серверный ping идёт только в одну сторону, а NAT и прокси на стороне игрока
 * (мобильный оператор, корпоративная сеть) считают простой по своему направлению.
 */
const PING_INTERVAL_MS = 25_000
/**
 * Оптимистичное эхо держим не дольше этого (Э19.5): если ни кадр состояния, ни `error` не
 * пришли (пакет потерян, сервер молчит), pending снимаем сами — иначе кнопка залипнет.
 */
const PENDING_INTENT_TIMEOUT_MS = 6_000

/** Коды закрытия, после которых reconnect бессмысленен (auth / стола нет). */
const FATAL_CLOSE_CODES = new Set([4401, 4403, 4404, 4001])

function wsUrl(roomCode: string, seatToken: string | null): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
  const host = window.location.host
  const base = import.meta.env.VITE_API_BASE ?? ""
  let root: string
  if (base.startsWith("http")) {
    root = base.replace(/^http/, "ws")
  } else {
    root = `${proto}//${host}${base}`
  }
  const q = seatToken ? `?seat_token=${encodeURIComponent(seatToken)}` : ""
  return `${root}/api/multiplayer/ws/${encodeURIComponent(roomCode)}${q}`
}

export function loadSeatToken(prefix: string, roomCode: string): string | null {
  try {
    return sessionStorage.getItem(`${prefix}${roomCode}`)
  } catch {
    return null
  }
}

export function saveSeatToken(prefix: string, roomCode: string, token: string) {
  try {
    sessionStorage.setItem(`${prefix}${roomCode}`, token)
  } catch {
    /* private mode */
  }
}

export class GameRoomSocket<TPublic, TPrivate> {
  private ws: WebSocket | null = null
  private listeners = new Set<Listener<TPublic, TPrivate>>()
  private snap: GameRoomSnapshot<TPublic, TPrivate>
  private skewMs = 0
  private roomCode: string
  private opts: GameRoomOptions<TPublic>
  /** Клиент сам закрыл сокет — не считать аварией и не reconnect. */
  private intentionalClose = false
  private reconnectAttempt = 0
  private reconnectTimer: number | null = null
  private pingTimer: number | null = null
  private pendingTimer: number | null = null
  private stopped = false
  /**
   * Э20.6: номер последнего применённого конверта `state`. Кадр не новее уже применённого
   * отбрасываем — после reconnect + `sync` в полёте может оказаться устаревший. Сбрасывается
   * на `welcome`: новое соединение = новая последовательность (сервер мог перезапуститься и
   * начать нумерацию заново).
   */
  private lastRev: number | null = null

  constructor(roomCode: string, opts: GameRoomOptions<TPublic>) {
    this.roomCode = roomCode
    this.opts = opts
    const isHost = Boolean(opts.isHost)
    const engineSeatId = opts.engineSeatId ?? (isHost ? "hr" : null)
    const isSpectator = opts.isSpectator ?? engineSeatId == null
    this.snap = {
      lobby: true,
      serverNow: Date.now(),
      phaseEndsAt: null,
      public: opts.initialPublic,
      private: null,
      seatToken: loadSeatToken(opts.storagePrefix, roomCode),
      engineSeatId,
      isHost,
      isSpectator,
      lastError: null,
      connected: false,
      reconnecting: false,
      pause: { paused: false, by: "", resumingAt: null },
      pendingIntent: null,
      intentError: null,
    }
  }

  get snapshot() {
    return this.snap
  }

  subscribe(fn: Listener<TPublic, TPrivate>) {
    this.listeners.add(fn)
    fn(this.snap)
    return () => this.listeners.delete(fn)
  }

  /**
   * Пара для `useSyncExternalStore` (Э19.3): подписка без синхронного вызова (React читает
   * начальное значение сам) + `getSnapshot`, отдающий стабильную ссылку между событиями —
   * поэтому React батчит кадр состояния и следующие за ним `line_delta` в один коммит и не
   * перерисовывается на тик секундомера, который живёт в своём листе. С Э20.1 состояние
   * приходит одним конвертом, так что батчить пару public/private больше не требуется.
   * Стрелки-поля: ссылки стабильны на весь срок жизни сокета.
   */
  subscribeStore = (onStoreChange: () => void): (() => void) => {
    this.listeners.add(onStoreChange)
    return () => this.listeners.delete(onStoreChange)
  }

  getSnapshot = (): GameRoomSnapshot<TPublic, TPrivate> => this.snap

  private emit() {
    for (const fn of this.listeners) fn(this.snap)
  }

  /**
   * Кадр, которого generic-слой не знает, — игра разбирает сама (вернуть true, если разобрала).
   * Заведено под стрим реплик: `line_delta` идёт между состояниями и полный кадр состояния
   * из-за него не гоняется.
   */
  protected onGameFrame(msg: Record<string, unknown>): boolean {
    void msg
    return false
  }

  /**
   * Слой игры поверх пришедшего состояния (живые реплики, локальные наложения). Вызывается
   * на каждом кадре состояния, поэтому обязан быть чистым и дешёвым.
   */
  protected decoratePublic(pub: TPublic): TPublic {
    return pub
  }

  /** Подменить игровое состояние из своего разбора кадра и разбудить подписчиков. */
  protected setPublic(pub: TPublic) {
    this.snap = { ...this.snap, public: pub }
    this.emit()
  }

  private rememberToken(token: string) {
    saveSeatToken(this.opts.storagePrefix, this.roomCode, token)
  }

  connect() {
    this.stopped = false
    this.clearReconnectTimer()
    this.clearPendingIntent()
    this.intentionalClose = false
    this.detachSocket()
    const token = loadSeatToken(this.opts.storagePrefix, this.roomCode) ?? this.snap.seatToken
    const ws = new WebSocket(wsUrl(this.roomCode, token))
    this.ws = ws

    ws.onopen = () => {
      this.reconnectAttempt = 0
      this.startHeartbeat()
      this.snap = { ...this.snap, connected: true, reconnecting: false, lastError: null }
      this.emit()
    }

    ws.onclose = (ev) => {
      if (this.ws !== ws) return
      this.ws = null
      this.stopHeartbeat()
      const intentional = this.intentionalClose
      this.snap = { ...this.snap, connected: false }
      this.emit()
      if (intentional || this.stopped) return
      if (FATAL_CLOSE_CODES.has(ev.code)) {
        this.snap = {
          ...this.snap,
          lastError: this.opts.humanizeError(
            ev.code === 4401
              ? "auth"
              : ev.code === 4404 || ev.code === 4001
                ? "closed"
                : ev.reason || "нет доступа",
          ),
          reconnecting: false,
        }
        this.emit()
        return
      }
      this.scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose придёт следом; не дублируем «оборвалось» при intentional/Strict Mode.
      if (this.intentionalClose || this.ws !== ws) return
    }

    ws.onmessage = (ev) => {
      if (this.ws !== ws) return
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(String(ev.data)) as Record<string, unknown>
      } catch {
        return
      }
      this.handle(msg)
    }
  }

  private scheduleReconnect() {
    if (this.stopped || this.intentionalClose) return
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      this.snap = {
        ...this.snap,
        reconnecting: false,
        lastError: "Связь со столом потеряна. Нажмите «Переподключить» или обновите страницу.",
      }
      this.emit()
      return
    }
    const attempt = this.reconnectAttempt
    this.reconnectAttempt += 1
    const delay = Math.min(
      RECONNECT_MAX_MS,
      RECONNECT_BASE_MS * 2 ** attempt + Math.floor(Math.random() * 200),
    )
    this.snap = {
      ...this.snap,
      reconnecting: true,
      lastError: `Нет связи — переподключение (${this.reconnectAttempt}/${MAX_RECONNECT_ATTEMPTS})…`,
    }
    this.emit()
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      if (!this.stopped && !this.intentionalClose) this.connect()
    }, delay)
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer != null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  /** Снять оптимистичное эхо (Э19.5). Не эмитит сам — вызывающий уже кладёт новый snap. */
  private clearPendingIntent() {
    if (this.pendingTimer != null) {
      window.clearTimeout(this.pendingTimer)
      this.pendingTimer = null
    }
    if (this.snap.pendingIntent) {
      this.snap = { ...this.snap, pendingIntent: null }
    }
  }

  /** Держим направление клиент→сервер живым; сервер отвечает `pong`. */
  private startHeartbeat() {
    this.stopHeartbeat()
    this.pingTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) this.send({ type: "ping" })
    }, PING_INTERVAL_MS)
  }

  private stopHeartbeat() {
    if (this.pingTimer != null) {
      window.clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  /** Снять хендлеры до close — иначе Strict Mode/replace даёт ложный onerror. */
  private detachSocket() {
    this.stopHeartbeat()
    if (!this.ws) return
    const prev = this.ws
    prev.onopen = null
    prev.onclose = null
    prev.onerror = null
    prev.onmessage = null
    if (prev.readyState === WebSocket.OPEN || prev.readyState === WebSocket.CONNECTING) {
      try {
        prev.close()
      } catch {
        /* ignore */
      }
    }
    this.ws = null
  }

  private handle(msg: Record<string, unknown>) {
    const type = msg.type
    if (type === "welcome") {
      const seatToken = String(msg.seat_token ?? "")
      if (seatToken) this.rememberToken(seatToken)
      this.lastRev = null // новое соединение — новая последовательность кадров (Э20.6)
      this.snap = {
        ...this.snap,
        seatToken,
        engineSeatId: (msg.engine_seat_id as string | null) ?? null,
        isHost: Boolean(msg.is_host),
        isSpectator: Boolean(msg.is_spectator),
        connected: true,
        reconnecting: false,
        lastError: null,
      }
      this.emit()
      return
    }
    if (type === "seat_assigned") {
      const seatToken = msg.seat_token != null ? String(msg.seat_token) : this.snap.seatToken
      if (seatToken) this.rememberToken(seatToken)
      this.snap = {
        ...this.snap,
        seatToken,
        engineSeatId: (msg.engine_seat_id as string | null) ?? null,
        isSpectator: Boolean(msg.is_spectator),
      }
      this.emit()
      return
    }
    if (type === "state") {
      // Э20.1: public и private одним конвертом — один emit, один коммит React.
      // Э20.6: устаревший по rev кадр отбрасываем целиком.
      const rev = typeof msg.rev === "number" ? msg.rev : null
      if (rev != null && this.lastRev != null && rev <= this.lastRev) return
      if (rev != null) this.lastRev = rev
      const serverNowIso = msg.server_now as string | undefined
      const endsIso = msg.phase_ends_at as string | null | undefined
      const serverNow = serverNowIso ? Date.parse(serverNowIso) : Date.now()
      this.skewMs = serverNow - Date.now()
      // Пришло свежее состояние — своё оптимистичное эхо и инлайн-ошибка больше не нужны (Э19.5/19.6).
      this.clearPendingIntent()
      const pauseRaw = (msg.pause ?? null) as
        | { paused?: unknown; by?: unknown; resuming_at?: unknown }
        | null
      const resumingIso = pauseRaw?.resuming_at
      this.snap = {
        ...this.snap,
        lobby: Boolean(msg.lobby),
        serverNow,
        phaseEndsAt: endsIso ? Date.parse(endsIso) : null,
        pause: {
          paused: Boolean(pauseRaw?.paused),
          by: typeof pauseRaw?.by === "string" ? pauseRaw.by : "",
          resumingAt: typeof resumingIso === "string" ? Date.parse(resumingIso) : null,
        },
        public: this.decoratePublic((msg.public as TPublic) ?? this.snap.public),
        // Приватная половина есть в кадре всегда, пока идёт партия; в лобби ключа нет —
        // прежнее значение не трогаем.
        private: "private" in msg ? ((msg.private as TPrivate) ?? null) : this.snap.private,
        intentError: null,
      }
      this.emit()
      return
    }
    // Переходный период: пара state_public / state_private от старой сборки сервера (откат)
    // или кадр в полёте во время деплоя. Новый сервер шлёт только `state`.
    if (type === "state_public") {
      const serverNowIso = msg.server_now as string | undefined
      const endsIso = msg.phase_ends_at as string | null | undefined
      const serverNow = serverNowIso ? Date.parse(serverNowIso) : Date.now()
      this.skewMs = serverNow - Date.now()
      this.clearPendingIntent()
      this.snap = {
        ...this.snap,
        lobby: Boolean(msg.lobby),
        serverNow,
        phaseEndsAt: endsIso ? Date.parse(endsIso) : null,
        public: this.decoratePublic((msg.state as TPublic) ?? this.snap.public),
        intentError: null,
      }
      this.emit()
      return
    }
    if (type === "state_private") {
      this.snap = { ...this.snap, private: (msg.state as TPrivate) ?? null }
      this.emit()
      return
    }
    if (type === "error") {
      const detail = String(msg.detail ?? "").trim()
      const message = this.opts.humanizeError(detail)
      // Если ошибка — ответ на свой интент, откатываем эхо и запоминаем причину для места действия (Э19.6).
      const rejected = this.snap.pendingIntent
      this.clearPendingIntent()
      this.snap = {
        ...this.snap,
        lastError: message,
        intentError: rejected ? { intent: rejected.intent, message } : this.snap.intentError,
      }
      this.emit()
      return
    }
    this.onGameFrame(msg)
  }

  secondsLeft(nowMs = Date.now()): number | null {
    if (this.snap.phaseEndsAt == null) return null
    const adjustedNow = nowMs + this.skewMs
    return Math.max(0, Math.ceil((this.snap.phaseEndsAt - adjustedNow) / 1000))
  }

  // --- протокол хаба (одинаков у всех игр раздела) --------------------------------

  startMatch() {
    this.send({ type: "start" })
  }

  claimSeat(seatId: string) {
    this.send({ type: "claim_seat", seat_id: seatId })
  }

  hostAction(
    action: "kick" | "fill_bot" | "assign_hr" | "add_slot",
    opts: { seatId?: string; accountId?: number } = {},
  ) {
    this.send({
      type: "host",
      action,
      seat_id: opts.seatId,
      account_id: opts.accountId,
    })
  }

  sendIntent(intent: Record<string, unknown>) {
    // Оптимистичное эхо (Э19.5): показать «принято» до round-trip, снять по state/error/таймауту.
    if (this.pendingTimer != null) window.clearTimeout(this.pendingTimer)
    this.snap = {
      ...this.snap,
      pendingIntent: { intent, at: Date.now() },
      intentError: null,
    }
    this.pendingTimer = window.setTimeout(() => {
      this.pendingTimer = null
      if (this.snap.pendingIntent) {
        this.snap = { ...this.snap, pendingIntent: null }
        this.emit()
      }
    }, PENDING_INTENT_TIMEOUT_MS)
    this.emit()
    this.send({ type: "intent", intent })
  }

  sync() {
    this.send({ type: "sync" })
  }

  /** Пауза (Dota-стиль): ставит любой участник, держится бессрочно. */
  pauseMatch() {
    this.send({ type: "pause" })
  }

  /** Снять паузу — сервер даёт 3-сек отсчёт и возвращает таймер фазы с остатком. */
  resumeMatch() {
    this.send({ type: "resume" })
  }

  /** Ручной retry после исчерпания backoff. */
  reconnectNow() {
    this.stopped = false
    this.reconnectAttempt = 0
    this.snap = { ...this.snap, lastError: null, reconnecting: true }
    this.emit()
    this.connect()
  }

  private send(payload: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload))
    }
  }

  close() {
    this.stopped = true
    this.intentionalClose = true
    this.clearReconnectTimer()
    this.clearPendingIntent()
    this.detachSocket()
    this.snap = { ...this.snap, connected: false, reconnecting: false }
  }
}
