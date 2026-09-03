import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type SearchModeOut = components["schemas"]["SearchModeOut"]
export type SearchModePatch = components["schemas"]["SearchModePatch"]
export type SearchMode = SearchModeOut["mode"]

/** GET /api/career/search-mode — текущий режим поиска (ST-01). */
export function fetchSearchMode() {
  return api.get<SearchModeOut>("/api/career/search-mode")
}

/** PATCH /api/career/search-mode — переключить режим поиска. */
export function patchSearchMode(body: SearchModePatch) {
  return api.patch<SearchModeOut>("/api/career/search-mode", body)
}

export type SearchTrackOut = components["schemas"]["SearchTrackOut"]
export type SearchTrackPatch = components["schemas"]["SearchTrackPatch"]

/** GET /api/career/track — включённые треки поиска (основная / вторая работа). */
export function fetchSearchTrack() {
  return api.get<SearchTrackOut>("/api/career/track")
}

/** PATCH /api/career/track — включить или выключить вторую работу. */
export function patchSearchTrack(body: SearchTrackPatch) {
  return api.patch<SearchTrackOut>("/api/career/track", body)
}

export type CareerSnapshot = components["schemas"]["CareerSnapshot"]

/** GET /api/career/snapshot — «Где я сейчас»: снимок фактов без единого поля ввода (Э9.2). */
export function fetchCareerSnapshot() {
  return api.get<CareerSnapshot>("/api/career/snapshot")
}

export type CareerDelta = components["schemas"]["CareerDelta"]

/** GET /api/career/delta — «было → стало» за 30 дней; `null` — истории меньше двух точек (Э9.5). */
export function fetchCareerDelta() {
  return api.get<CareerDelta | null>("/api/career/delta")
}

// —— Лента (Э9.3, обогащение + курсор — Этап 2/3 плана редизайна «Карьеры») ——

export type TimelineEvent = components["schemas"]["TimelineEvent"]
export type TimelineEventView = components["schemas"]["TimelineEventView"]
export type TimelineEventCreateInput = components["schemas"]["TimelineEventCreate"]
export type ManualTimelineKind = TimelineEventCreateInput["kind"]

/** GET /api/career/timeline — лента аккаунта, свежие первыми; `kinds` — фильтр по видам,
 * `beforeId` — курсор «Показать ещё» (id последней увиденной строки). */
export function fetchTimeline(params: { kinds?: string[]; limit?: number; beforeId?: number } = {}) {
  const qs = new URLSearchParams()
  if (params.kinds?.length) qs.set("kinds", params.kinds.join(","))
  if (params.limit) qs.set("limit", String(params.limit))
  if (params.beforeId != null) qs.set("before_id", String(params.beforeId))
  const suffix = qs.toString() ? `?${qs.toString()}` : ""
  return api.get<TimelineEventView[]>(`/api/career/timeline${suffix}`)
}

/** POST /api/career/timeline — единственное ручное действие экрана «Карьера»: добавить событие. */
export function createTimelineEntry(body: TimelineEventCreateInput) {
  return api.post<TimelineEvent>("/api/career/timeline", body)
}

// —— Память (Э9.4) ——

export type CareerFact = components["schemas"]["CareerFact"]
export type CareerFactPatch = components["schemas"]["CareerFactPatch"]

/** GET /api/career/facts — активные факты аккаунта, опционально по виду/источнику. */
export function fetchFacts(params: { type?: string; source?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.type) qs.set("type", params.type)
  if (params.source) qs.set("source", params.source)
  const suffix = qs.toString() ? `?${qs.toString()}` : ""
  return api.get<CareerFact[]>(`/api/career/facts${suffix}`)
}

/** PATCH /api/career/facts/{id} — поправить текст и/или закрепить факт. */
export function patchFact(factId: number, body: CareerFactPatch) {
  return api.patch<CareerFact>(`/api/career/facts/${factId}`, body)
}

/** DELETE /api/career/facts/{id} — удалить неверный факт. */
export function deleteFact(factId: number) {
  return api.del(`/api/career/facts/${factId}`)
}

// —— Портфолио (A-24) ——

export type PortfolioItem = components["schemas"]["PortfolioItem"]
export type PortfolioDraftFromDebriefRequest =
  components["schemas"]["PortfolioDraftFromDebriefRequest"]
export type PortfolioDraftFromOfferRequest = components["schemas"]["PortfolioDraftFromOfferRequest"]

export type PortfolioItemCreateInput = {
  project: string
  role?: string
  outcome?: string
  artifact_url?: string
  source_ref?: string
  notes?: string
}

/** GET /api/career/portfolio — все элементы портфолио аккаунта. */
export function listPortfolioItems() {
  return api.get<PortfolioItem[]>("/api/career/portfolio")
}

/** POST /api/career/portfolio — добавить элемент вручную. */
export function createPortfolioItem(body: PortfolioItemCreateInput) {
  return api.post<PortfolioItem>("/api/career/portfolio", body)
}

/** POST /api/career/portfolio/draft-from-resume — черновик из опыта резюме. */
export function draftPortfolioFromResume() {
  return api.post<PortfolioItem[]>("/api/career/portfolio/draft-from-resume")
}

/** POST /api/career/portfolio/draft-from-debrief — черновик из уже открытого разбора собеса. */
export function draftPortfolioFromDebrief(body: PortfolioDraftFromDebriefRequest) {
  return api.post<PortfolioItem[]>("/api/career/portfolio/draft-from-debrief", body)
}

/** POST /api/career/portfolio/draft-from-offer — черновик из уже открытого оффера. */
export function draftPortfolioFromOffer(body: PortfolioDraftFromOfferRequest) {
  return api.post<PortfolioItem[]>("/api/career/portfolio/draft-from-offer", body)
}

/** DELETE /api/career/portfolio/{id} — удалить элемент (например, неверный авто-черновик). */
export function deletePortfolioItem(itemId: number) {
  return api.del(`/api/career/portfolio/${itemId}`)
}

// —— Дружба (0120) ——

export type FriendshipCodeOut = components["schemas"]["FriendshipCodeOut"]
export type FriendEntry = components["schemas"]["FriendEntry"]
export type FriendProfile = components["schemas"]["FriendProfile"]

export type AddFriendRequestInput = {
  code: string
}

/** GET /api/career/friends/code — код дружбы аккаунта. */
export function fetchFriendshipCode() {
  return api.get<FriendshipCodeOut>("/api/career/friends/code")
}

/** POST /api/career/friends/add — добавить друга по коду. */
export function addFriendByCode(body: AddFriendRequestInput) {
  return api.post<FriendEntry>("/api/career/friends/add", body)
}

/** GET /api/career/friends — список друзей. */
export function listFriends() {
  return api.get<FriendEntry[]>("/api/career/friends")
}

/** GET /api/career/friends/{id}/profile — профиль друга. */
export function fetchFriendProfile(friendAccountId: number) {
  return api.get<FriendProfile>(`/api/career/friends/${friendAccountId}/profile`)
}

/** DELETE /api/career/friends/{id} — удалить друга. */
export function removeFriend(friendAccountId: number) {
  return api.del(`/api/career/friends/${friendAccountId}`)
}
