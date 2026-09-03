import { useMemo } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { OPENROUTER_MISSING_TOAST } from "@/lib/toasts"
import {
  compareOffersStream,
  createOffer,
  deleteOffer,
  listOffers,
  negotiateOffer,
  parseOffer,
  patchOffer,
  reorderOffers,
  type OfferComparison,
  type OfferCompareResponse,
  type OfferCreateRequest,
  type OfferParseApiRequest,
  type OfferRecord,
  type OfferUpdateRequest,
} from "@/api/offers"

const KEY = ["offers"] as const

export function useOffers() {
  return useQuery({ queryKey: KEY, queryFn: listOffers, staleTime: 15_000 })
}

// Заменить/добавить оффер в кэше списка по vacancy_id (без рефетча — без мигания матрицы).
function upsertInCache(qc: ReturnType<typeof useQueryClient>, offer: OfferRecord) {
  qc.setQueryData<OfferRecord[]>(KEY, (prev) => {
    const list = prev ?? []
    const idx = list.findIndex((o) => o.vacancy_id === offer.vacancy_id)
    if (idx === -1) return [offer, ...list]
    const next = list.slice()
    next[idx] = offer
    return next
  })
}

export function useCreateOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: OfferCreateRequest) => createOffer(req),
    onSuccess: (offer) => {
      upsertInCache(qc, offer)
      toast.success("Оффер добавлен")
    },
    onError: () => toast.error("Не удалось добавить оффер"),
  })
}

export function usePatchOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ vacancyId, patch }: { vacancyId: string; patch: OfferUpdateRequest }) =>
      patchOffer(vacancyId, patch),
    onSuccess: (offer) => upsertInCache(qc, offer),
    onError: () => toast.error("Не удалось сохранить правку"),
  })
}

export function useDeleteOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vacancyId: string) => deleteOffer(vacancyId),
    onSuccess: (_void, vacancyId) => {
      qc.setQueryData<OfferRecord[]>(KEY, (prev) =>
        (prev ?? []).filter((o) => o.vacancy_id !== vacancyId),
      )
      toast.success("Оффер убран")
    },
    onError: () => toast.error("Не удалось убрать оффер"),
  })
}

// Сравнение — только по явному клику «Сравнить» (раньше пересчитывалось само на любую правку
// оффера, включая drag-n-drod приоритета — это било по деньгам на пустом месте, см. история
// правки). Ключ запроса стабильный (не зависит от состава/правок офферов), поэтому обычное
// поведение React Query само держит предыдущий бриф видимым на экране, пока считается новый
// (isFetching=true, data — ещё старая): именно так «старый бриф не пропадает» без ручного кэша.
// Сервер всё равно кэширует ответ по хэшу входов (compare/save_offer_comparison_cache), так
// что повторный клик без изменений не дёргает LLM повторно.
export function useOfferComparison(offers: OfferRecord[]) {
  const vacancyIds = useMemo(() => offers.map((o) => o.vacancy_id), [offers])
  const qc = useQueryClient()

  const query = useQuery({
    queryKey: ["offers", "decide"],
    // L-49: rankings/verdict приезжают по отдельности — партиал сразу в кэш (тот же приём, что у
    // generateScreeningQuestionsStream), начиная от уже показанного сравнения (не мигает пустотой).
    queryFn: () => {
      const seed = qc.getQueryData<OfferCompareResponse>(["offers", "decide"])
      let comparison: OfferComparison | null | undefined = seed?.comparison
      return compareOffersStream(
        (event) => {
          if (event.type === "rankings") {
            comparison = {
              ...(comparison ?? EMPTY_COMPARISON),
              rankings: event.rankings,
              favorable_fields: event.favorable_fields,
            }
            qc.setQueryData<OfferCompareResponse>(["offers", "decide"], {
              offers: seed?.offers ?? [],
              comparison,
              detail: "",
            })
          }
          if (event.type === "verdict") {
            comparison = {
              ...(comparison ?? EMPTY_COMPARISON),
              sensitivity: event.sensitivity,
              recommendation: event.recommendation,
            }
            qc.setQueryData<OfferCompareResponse>(["offers", "decide"], {
              offers: seed?.offers ?? [],
              comparison,
              detail: "",
            })
          }
          if (event.type === "done") {
            qc.setQueryData<OfferCompareResponse>(["offers", "decide"], event.response)
          }
        },
        { vacancy_ids: vacancyIds },
      )
    },
    enabled: false,
    staleTime: Infinity,
  })

  return { ...query, compare: () => query.refetch() }
}

const EMPTY_COMPARISON: OfferComparison = {
  rankings: [],
  sensitivity: [],
  recommendation: "",
  markdown: "",
  favorable_fields: {},
  compared_at: new Date(0).toISOString(),
}

// LLM-парсинг письма HR под выбранную вакансию. Возвращает обновлённый OfferRecord,
// кладётся в кэш списка (как useCreateOffer/usePatchOffer). overwrite=true — перезапись
// непустых полей (редко; по умолчанию merge добивает только пустые).
export function useParseOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: OfferParseApiRequest) => parseOffer(req),
    onSuccess: (offer) => {
      upsertInCache(qc, offer)
      toast.success("Письмо разобрано — поля оффера заполнены")
    },
    onError: () => toast.error(`Не удалось разобрать письмо. ${OPENROUTER_MISSING_TOAST}`),
  })
}

// OF-11: ручной приоритет колонок матрицы через drag-n-drop. onMutate переставляет кэш сразу
// (мгновенный отклик, без ожидания ответа сервера) — сервер лишь персистит порядок.
export function useReorderOffers() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vacancyIds: string[]) => reorderOffers(vacancyIds),
    onMutate: (vacancyIds: string[]) => {
      const prev = qc.getQueryData<OfferRecord[]>(KEY)
      qc.setQueryData<OfferRecord[]>(KEY, (list) => {
        if (!list) return list
        const byId = new Map(list.map((o) => [o.vacancy_id, o]))
        const reordered = vacancyIds.map((id) => byId.get(id)).filter((o): o is OfferRecord => !!o)
        const rest = list.filter((o) => !vacancyIds.includes(o.vacancy_id))
        return [...reordered, ...rest]
      })
      return { prev }
    },
    onError: (_err, _vacancyIds, ctx) => {
      if (ctx?.prev) qc.setQueryData(KEY, ctx.prev)
      toast.error("Не удалось сохранить порядок")
    },
    onSuccess: (offers) => {
      for (const offer of offers) upsertInCache(qc, offer)
    },
  })
}

// RD-17: аргументы для торга. Персист на офере — `offer.negotiation` в кэше обновляется сразу
// (перечитывать/показывать без повторной генерации до следующего явного клика «Торг»).
export function useNegotiateOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vacancyId: string) => negotiateOffer(vacancyId),
    onSuccess: ({ offer }) => upsertInCache(qc, offer),
    onError: () => toast.error(OPENROUTER_MISSING_TOAST),
  })
}
