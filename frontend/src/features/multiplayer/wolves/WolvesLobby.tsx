import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import {
  closeWolvesRoom,
  createWolvesRoom,
  joinWolvesRoom,
  listWolvesRooms,
  type RoomOut,
} from "@/api/multiplayer"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { RoomCard } from "@/features/multiplayer/gfx/shell"
import { WolvesTable } from "@/features/multiplayer/wolves/WolvesTable"

const ROOMS_KEY = ["multiplayer", "wolves", "rooms"] as const
const NICK_HINT_ID = "mp-wolves-nick-hint"

function joinErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return "Не удалось войти за стол"
  const msg = err.message.toLowerCase()
  if (err.status === 404 || msg.includes("не найден") || msg.includes("not found")) {
    return "Стол не найден или уже закрыт"
  }
  if (err.status === 401 || err.status === 403) {
    return "Нет доступа к столу — проверьте вход"
  }
  if (err.status >= 500) {
    return "Сервер споткнулся. Обновите список и зайдите снова"
  }
  // 409 «полон» больше не блокер (smart join → зритель); если прилетело — мягко.
  if (err.status === 409) {
    return "Слот занят людьми — вас пустят зрителем. Попробуйте ещё раз"
  }
  return err.message || "Не удалось войти за стол"
}

type WolvesLobbyProps = {
  /** Открыт живой стол (true) или список лобби (false) — хаб по этому прячет свой хром. */
  onTableChange?: (atTable: boolean) => void
}

/**
 * Лобби: «Создать стол»; список открытых с «Войти».
 * Каждый заход — новый сид/раунд; mid-join на бот-слот или зритель.
 */
export function WolvesLobby({ onTableChange }: WolvesLobbyProps = {}) {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const deepLinkHandled = useRef(false)

  const roomsQuery = useQuery({
    queryKey: ROOMS_KEY,
    queryFn: listWolvesRooms,
    staleTime: 5_000,
    refetchInterval: 15_000,
  })

  const [joined, setJoined] = useState<RoomOut | null>(null)
  const [autoStart, setAutoStart] = useState(false)
  const [nick, setNick] = useState(() => {
    try {
      return sessionStorage.getItem("mp_wolves_nick") ?? ""
    } catch {
      return ""
    }
  })

  const rememberNick = (value: string) => {
    const cleaned = value.trim().slice(0, 24)
    setNick(cleaned)
    try {
      if (cleaned) sessionStorage.setItem("mp_wolves_nick", cleaned)
      else sessionStorage.removeItem("mp_wolves_nick")
    } catch {
      /* private mode */
    }
  }

  const createMut = useMutation({
    mutationFn: () => createWolvesRoom({ nick: nick.trim() || undefined }),
    onSuccess: (room) => {
      qc.invalidateQueries({ queryKey: ROOMS_KEY })
      setAutoStart(true)
      setJoined(room)
      toast.success(room.name)
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Не удалось создать стол")
    },
  })

  const joinMut = useMutation({
    mutationFn: (code: string) =>
      joinWolvesRoom(code.trim().toUpperCase(), {
        as: "player",
        nick: nick.trim() || undefined,
      }),
    onSuccess: (room) => {
      qc.invalidateQueries({ queryKey: ROOMS_KEY })
      setAutoStart(false)
      setJoined(room)
      const asSpec = room.my_seat_kind === "spectator"
      toast.success(
        asSpec
          ? `Зритель за ${room.code} — сядьте вместо бота, когда готовы`
          : `Вы за столом ${room.code}`,
      )
    },
    onError: (err) => {
      toast.error(joinErrorMessage(err))
    },
  })

  const closeMut = useMutation({
    mutationFn: (code: string) => closeWolvesRoom(code),
    onSuccess: (_, code) => {
      qc.invalidateQueries({ queryKey: ROOMS_KEY })
      if (joined?.code === code) setJoined(null)
      toast.success("Стол закрыт")
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Не удалось закрыть стол")
    },
  })

  // Deep-link: /multiplayer?join=CODE
  useEffect(() => {
    if (deepLinkHandled.current) return
    const raw = searchParams.get("join")
    if (!raw) return
    deepLinkHandled.current = true
    const code = raw.trim().toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6)
    setSearchParams({}, { replace: true })
    if (!/^[A-Z0-9]{6}$/.test(code)) {
      toast.error("Битая ссылка на стол")
      return
    }
    joinMut.mutate(code)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- один раз на mount
  }, [searchParams])

  useEffect(() => {
    onTableChange?.(Boolean(joined))
  }, [joined, onTableChange])

  const rooms = roomsQuery.data ?? []

  if (joined) {
    return (
      <WolvesTable
        room={joined}
        autoStart={autoStart}
        onLeave={() => {
          setJoined(null)
          setAutoStart(false)
          void roomsQuery.refetch()
        }}
        onCloseRoom={() => closeMut.mutate(joined.code)}
        closing={closeMut.isPending}
      />
    )
  }

  const busy = createMut.isPending || joinMut.isPending
  // Без ника место за столом подписано машинным id (`c2`) — в игре про то, кто врёт, это
  // ломает саму возможность обсуждать игроков. Гейтим вход, но не молча: подсказка под полем.
  const nickMissing = nick.trim().length === 0

  return (
    <div className="w-full max-w-3xl space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[10rem] flex-1 space-y-1">
          <span className="mp-mono text-[10px] uppercase tracking-wide text-slate-500">
            Никнейм
          </span>
          <Input
            value={nick}
            onChange={(e) => rememberNick(e.target.value)}
            placeholder="Никнейм"
            maxLength={24}
            className="h-9"
            aria-invalid={nickMissing || undefined}
            aria-describedby={nickMissing ? NICK_HINT_ID : undefined}
          />
          {nickMissing ? (
            <p id={NICK_HINT_ID} className="mp-mono text-[10px] text-slate-500">
              Нужен ник — за столом он вместо ФИО
            </p>
          ) : null}
        </label>
        <Button
          type="button"
          size="sm"
          onClick={() => createMut.mutate()}
          disabled={busy || nickMissing}
        >
          Создать стол
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => roomsQuery.refetch()}
          disabled={roomsQuery.isFetching}
        >
          Обновить
        </Button>
      </div>

      <div className="space-y-2">
        <h3 className="mp-mono text-[11px] uppercase tracking-wide text-slate-500">
          Открытые столы
        </h3>
        {roomsQuery.isLoading ? (
          <p className="mp-mono text-sm text-slate-500">Грузим список…</p>
        ) : roomsQuery.isError ? (
          <div className="rounded-md border border-dashed border-slate-300 bg-slate-50/80 px-3 py-4">
            <p className="text-sm text-slate-700">Список не открылся — сеть или сервер.</p>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="mt-2"
              onClick={() => roomsQuery.refetch()}
            >
              Ещё раз
            </Button>
          </div>
        ) : rooms.length === 0 ? (
          <div className="rounded-md border border-dashed border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt)]/5 px-3 py-5">
            <p className="mp-display text-sm font-semibold text-slate-800">Пока пусто</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              Создайте стол — два бота уже сидят.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {rooms.map((room) => (
              <li key={room.id} className="flex items-stretch gap-2">
                <div className="min-w-0 flex-1">
                  <RoomCard
                    name={room.name}
                    code={room.code}
                    seatsFree={room.seats_free}
                    seatsTotal={room.seats_total}
                    phaseLabel={roomBadge(room)}
                  />
                </div>
                <div className="flex shrink-0 flex-col justify-center gap-1">
                  {room.my_seat_kind === "hr" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-slate-500"
                      disabled={closeMut.isPending}
                      onClick={() => closeMut.mutate(room.code)}
                    >
                      Закрыть
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    disabled={busy || nickMissing}
                    title={nickMissing ? "Сначала введите ник" : undefined}
                    onClick={() => joinMut.mutate(room.code)}
                  >
                    Войти
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function roomBadge(room: RoomOut): string {
  return room.phase_label
}
