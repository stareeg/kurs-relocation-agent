import { useEffect, useRef, useState } from "react"
import { Loader2, Trash2, Users } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  useAddFriend,
  useFriendProfile,
  useFriends,
  useFriendshipCode,
  useRemoveFriend,
} from "@/features/career/use-career"
import { CopyCodeButton } from "@/features/career/CopyCodeButton"
import type { FriendEntry } from "@/api/career"

// Правка 2026-08-19 (5): компактная версия блока «Друзья» для «Аккаунта» (левая колонка, под
// «Устройствами») — заменяет прежнее отдельное место на вкладке «Карьера» (CareerPage). Один
// инпут одновременно ищет по уже добавленным друзьям и принимает вставленный код (авто-добавление
// при совпадении с форматом кода, как автосейв ключа OpenRouter/токена бота выше на этой странице).
const FRIEND_CODE_RE = /^[A-Z0-9]{6}$/

function FriendScores({ friendAccountId }: { friendAccountId: number }) {
  const { data: profile, isLoading } = useFriendProfile(friendAccountId)
  if (isLoading) {
    return <span className="shrink-0 text-xs text-slate-400">…</span>
  }
  const resume = profile?.resume_score != null ? profile.resume_score : "—"
  const offer = profile?.offer_chance_pct != null ? `${profile.offer_chance_pct}%` : "—"
  return (
    <span className="shrink-0 text-xs font-medium tabular-nums">
      <span className="text-sky-700">{resume}</span>
      <span className="text-slate-300"> / </span>
      <span className="text-emerald-700">{offer}</span>
    </span>
  )
}

function FriendRow({
  friend,
  onRemove,
  removing,
}: {
  friend: FriendEntry
  onRemove: () => void
  removing: boolean
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-100 px-2 py-1.5">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600">
        {(friend.friend_name || "?")[0].toUpperCase()}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-slate-800">
        {friend.friend_name || "Без имени"}
      </span>
      {friend.is_admin_peer ? (
        <span className="shrink-0 text-xs text-slate-400">поддержка</span>
      ) : (
        <FriendScores friendAccountId={friend.friend_account_id} />
      )}
      {friend.is_admin_peer ? null : (
        <button
          type="button"
          title="Удалить друга"
          aria-label="Удалить друга"
          disabled={removing}
          onClick={onRemove}
          className="flex size-6 shrink-0 items-center justify-center rounded-full text-slate-300 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-60"
        >
          {removing ? (
            <Loader2 className="size-3 animate-spin" strokeWidth={2} />
          ) : (
            <Trash2 className="size-3" strokeWidth={2} />
          )}
        </button>
      )}
    </div>
  )
}

export function FriendsCompactSection() {
  const { data: codeData, isLoading: codeLoading } = useFriendshipCode()
  const { data: friends, isLoading: friendsLoading } = useFriends()
  const removeFriend = useRemoveFriend()
  const addFriend = useAddFriend()
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [query, setQuery] = useState("")
  const lastAttempted = useRef("")

  // Авто-добавление по вставленному коду — тот же приём, что автосейв ключа OpenRouter выше.
  useEffect(() => {
    const trimmed = query.trim().toUpperCase()
    if (!FRIEND_CODE_RE.test(trimmed)) return
    if (trimmed === lastAttempted.current || addFriend.isPending) return
    lastAttempted.current = trimmed
    addFriend.mutate({ code: trimmed }, { onSuccess: () => setQuery("") })
  }, [query, addFriend])

  function handleRemove(friend: FriendEntry) {
    setRemovingId(friend.friend_account_id)
    removeFriend.mutate(friend.friend_account_id, { onSettled: () => setRemovingId(null) })
  }

  const q = query.trim().toLowerCase()
  const visible = (friends ?? []).filter(
    (f) => !q || (f.friend_name ?? "").toLowerCase().includes(q),
  )

  return (
    <section className="rounded-xl border bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <Users className="size-4" strokeWidth={2} />
          Друзья
        </h2>
        {codeLoading ? (
          <Skeleton className="h-6 w-24" />
        ) : codeData ? (
          <div className="flex shrink-0 items-center gap-1.5">
            <code className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs font-semibold tracking-widest text-slate-800">
              {codeData.code}
            </code>
            <CopyCodeButton code={codeData.code} />
          </div>
        ) : null}
      </div>

      <Input
        placeholder="Поиск по друзьям или код друга"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className={cn("mb-3 text-sm", addFriend.isPending && "opacity-70")}
      />

      {friendsLoading ? (
        <div className="space-y-1.5">
          <Skeleton className="h-9 w-full rounded-lg" />
          <Skeleton className="h-9 w-full rounded-lg" />
        </div>
      ) : !friends?.length ? (
        <p className="py-2 text-center text-xs text-slate-400">
          Друзей пока нет — вставьте код друга в поле выше.
        </p>
      ) : visible.length === 0 ? (
        <p className="py-2 text-center text-xs text-slate-400">Никого не найдено.</p>
      ) : (
        <div className="space-y-1.5">
          {visible.map((friend) => (
            <FriendRow
              key={friend.id}
              friend={friend}
              onRemove={() => handleRemove(friend)}
              removing={removingId === friend.friend_account_id}
            />
          ))}
        </div>
      )}
    </section>
  )
}
