import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  addFriendByCode,
  createPortfolioItem,
  createTimelineEntry,
  deleteFact,
  deletePortfolioItem,
  draftPortfolioFromDebrief,
  draftPortfolioFromOffer,
  draftPortfolioFromResume,
  fetchCareerDelta,
  fetchCareerSnapshot,
  fetchFacts,
  fetchFriendProfile,
  fetchFriendshipCode,
  fetchTimeline,
  listFriends,
  listPortfolioItems,
  patchFact,
  removeFriend,
  type AddFriendRequestInput,
  type CareerFactPatch,
  type PortfolioDraftFromDebriefRequest,
  type PortfolioDraftFromOfferRequest,
  type PortfolioItemCreateInput,
  type TimelineEventCreateInput,
} from "@/api/career"

const PORTFOLIO_KEY = ["career", "portfolio"] as const
const FRIENDS_KEY = ["career", "friends"] as const
const SNAPSHOT_KEY = ["career", "snapshot"] as const
const DELTA_KEY = ["career", "delta"] as const
const TIMELINE_KEY = ["career", "timeline"] as const
const FACTS_KEY = ["career", "facts"] as const

// —— Снимок «Где я сейчас» (Э9.2) ——

export function useCareerSnapshot() {
  return useQuery({
    queryKey: SNAPSHOT_KEY,
    queryFn: fetchCareerSnapshot,
    staleTime: 30_000,
  })
}

// —— Дельта «Что изменилось» (Э9.5) ——

export function useCareerDelta() {
  return useQuery({
    queryKey: DELTA_KEY,
    queryFn: fetchCareerDelta,
    staleTime: 60_000,
  })
}

// —— Лента (Э9.3, курсор «Показать ещё» — Этап 3.3) ——

const TIMELINE_PAGE_SIZE = 25

export function useTimeline(kinds?: string[]) {
  return useInfiniteQuery({
    queryKey: [...TIMELINE_KEY, kinds?.length ? [...kinds].sort() : "all"],
    queryFn: ({ pageParam }: { pageParam: number | undefined }) =>
      fetchTimeline({ kinds, limit: TIMELINE_PAGE_SIZE, beforeId: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.length === TIMELINE_PAGE_SIZE ? (lastPage.at(-1)?.id ?? undefined) : undefined,
    staleTime: 15_000,
  })
}

export function useCreateTimelineEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TimelineEventCreateInput) => createTimelineEntry(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TIMELINE_KEY })
      toast.success("Событие добавлено")
    },
    onError: () => toast.error("Не удалось добавить событие"),
  })
}

// —— Память (Э9.4) ——

export function useFacts(params: { type?: string; source?: string } = {}) {
  return useQuery({
    queryKey: [...FACTS_KEY, params.type ?? "all", params.source ?? "all"],
    queryFn: () => fetchFacts(params),
    staleTime: 15_000,
  })
}

export function usePatchFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ factId, patch }: { factId: number; patch: CareerFactPatch }) =>
      patchFact(factId, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: FACTS_KEY }),
    onError: () => toast.error("Не удалось сохранить факт"),
  })
}

export function useDeleteFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (factId: number) => deleteFact(factId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: FACTS_KEY })
      toast.success("Факт удалён")
    },
    onError: () => toast.error("Не удалось удалить факт"),
  })
}

// —— Портфолио ——

export function usePortfolioItems() {
  return useQuery({ queryKey: PORTFOLIO_KEY, queryFn: listPortfolioItems, staleTime: 30_000 })
}

export function useCreatePortfolioItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PortfolioItemCreateInput) => createPortfolioItem(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PORTFOLIO_KEY })
      toast.success("Элемент портфолио добавлен")
    },
    onError: () => toast.error("Не удалось добавить элемент"),
  })
}

export function useDraftPortfolioFromResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => draftPortfolioFromResume(),
    onSuccess: (items) => {
      qc.invalidateQueries({ queryKey: PORTFOLIO_KEY })
      toast.success(
        items.length
          ? `Добавлено из резюме: ${items.length}`
          : "В резюме нечего добавить в портфолио",
      )
    },
    onError: () => toast.error("Не удалось собрать черновик из резюме"),
  })
}

export function useDraftPortfolioFromDebrief() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PortfolioDraftFromDebriefRequest) => draftPortfolioFromDebrief(body),
    onSuccess: (items) => {
      qc.invalidateQueries({ queryKey: PORTFOLIO_KEY })
      toast.success(items.length ? "Черновик из разбора добавлен" : "В разборе нет сильных ответов")
    },
    onError: () => toast.error("Не удалось собрать черновик из разбора"),
  })
}

export function useDraftPortfolioFromOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PortfolioDraftFromOfferRequest) => draftPortfolioFromOffer(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PORTFOLIO_KEY })
      toast.success("Черновик из оффера добавлен")
    },
    onError: () => toast.error("Не удалось собрать черновик из оффера"),
  })
}

export function useDeletePortfolioItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (itemId: number) => deletePortfolioItem(itemId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PORTFOLIO_KEY })
      toast.success("Удалено")
    },
    onError: () => toast.error("Не удалось удалить"),
  })
}

// —— Дружба (0120) ——

export function useFriendshipCode() {
  return useQuery({
    queryKey: [...FRIENDS_KEY, "code"],
    queryFn: fetchFriendshipCode,
    staleTime: 60_000,
  })
}

export function useFriends() {
  return useQuery({
    queryKey: FRIENDS_KEY,
    queryFn: listFriends,
    staleTime: 30_000,
  })
}

export function useFriendProfile(friendAccountId: number | null) {
  return useQuery({
    queryKey: [...FRIENDS_KEY, "profile", friendAccountId],
    queryFn: () => fetchFriendProfile(friendAccountId!),
    enabled: friendAccountId != null,
    staleTime: 15_000,
  })
}

export function useAddFriend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AddFriendRequestInput) => addFriendByCode(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: FRIENDS_KEY })
      toast.success("Друг добавлен")
    },
    onError: (err: Error) => {
      const msg = err.message || "Не удалось добавить друга"
      if (msg.includes("404")) {
        toast.error("Код дружбы не найден")
      } else if (msg.includes("400")) {
        toast.error("Нельзя добавить самого себя")
      } else if (msg.includes("409")) {
        toast.error("Уже в друзьях")
      } else {
        toast.error(msg)
      }
    },
  })
}

export function useRemoveFriend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (friendAccountId: number) => removeFriend(friendAccountId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: FRIENDS_KEY })
      toast.success("Друг удалён")
    },
    onError: () => toast.error("Не удалось удалить друга"),
  })
}
