import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  createInterviewStage,
  deleteInterviewStage,
  fetchInterviewStages,
  patchInterviewStage,
  reorderInterviewStages,
  type InterviewStageCreate,
  type InterviewStageListResponse,
  type InterviewStageOut,
  type InterviewStagePatch,
} from "@/api/interview-stages"
import { CHAIN_STAGE_LABELS } from "./stages"

// Цепочка этапов вакансии (RD-19) — степпер Техничек/дровер/шапка диалога читают одно и то же.
export function useInterviewStages(vacancyId: string | null) {
  return useQuery({
    queryKey: ["interview-stages", vacancyId],
    queryFn: () => fetchInterviewStages(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 60_000,
  })
}

// P-11: оптимистичные апдейты кэша ["interview-stages", vacancyId] — зеркалит хелперы ["jobs"]
// (use-jobs.ts). Раньше все четыре мутации ждали ответ сервера и только тогда инвалидировали —
// клик по «пройден»/перетаскивание в степпере ощутимо отставали (RTT + рефетч).
function getCache(qc: ReturnType<typeof useQueryClient>, vacancyId: string) {
  return qc.getQueryData<InterviewStageListResponse>(["interview-stages", vacancyId])
}

function setCache(
  qc: ReturnType<typeof useQueryClient>,
  vacancyId: string,
  data: InterviewStageListResponse,
) {
  qc.setQueryData<InterviewStageListResponse>(["interview-stages", vacancyId], data)
}

function patchStagesCache(
  qc: ReturnType<typeof useQueryClient>,
  vacancyId: string,
  map: (items: InterviewStageOut[]) => InterviewStageOut[],
) {
  qc.setQueryData<InterviewStageListResponse>(["interview-stages", vacancyId], (old) =>
    old ? { ...old, items: map(old.items ?? []) } : old,
  )
}

export function useAddInterviewStage(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: InterviewStageCreate) => createInterviewStage(vacancyId!, body),
    onMutate: async (body) => {
      if (!vacancyId) return
      await qc.cancelQueries({ queryKey: ["interview-stages", vacancyId] })
      const prev = getCache(qc, vacancyId)
      // Временный id (отрицательный, реальные — serial из PG) — карточка видна сразу, реальные
      // поля (position, id) подставит инвалидация на settled.
      const optimistic: InterviewStageOut = {
        id: -Date.now(),
        vacancy_id: vacancyId,
        stage_type: body.stage_type,
        stage_label: CHAIN_STAGE_LABELS[body.stage_type] ?? body.stage_type,
        scheduled_at: body.scheduled_at ?? null,
        format: body.format,
        status: "scheduled",
        position: prev?.items?.length ?? 0,
        notes: body.notes,
        source_message_id: null,
        created_at: new Date().toISOString(),
      }
      patchStagesCache(qc, vacancyId, (items) => [...items, optimistic])
      return { prev }
    },
    onError: (err, _body, ctx) => {
      if (vacancyId && ctx?.prev) setCache(qc, vacancyId, ctx.prev)
      toast.error(err instanceof Error ? err.message : "Не удалось добавить этап")
    },
    onSettled: () => {
      if (vacancyId) void qc.invalidateQueries({ queryKey: ["interview-stages", vacancyId] })
    },
  })
}

export function usePatchInterviewStage(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ stageId, body }: { stageId: number; body: InterviewStagePatch }) =>
      patchInterviewStage(vacancyId!, stageId, body),
    onMutate: async ({ stageId, body }) => {
      if (!vacancyId) return
      await qc.cancelQueries({ queryKey: ["interview-stages", vacancyId] })
      const prev = getCache(qc, vacancyId)
      patchStagesCache(qc, vacancyId, (items) =>
        items.map((it) => {
          if (it.id !== stageId) return it
          const next = { ...it, ...body }
          if (body.stage_type)
            next.stage_label = CHAIN_STAGE_LABELS[body.stage_type] ?? next.stage_label
          return next
        }),
      )
      return { prev }
    },
    onError: (err, _vars, ctx) => {
      if (vacancyId && ctx?.prev) setCache(qc, vacancyId, ctx.prev)
      toast.error(err instanceof Error ? err.message : "Не удалось изменить этап")
    },
    onSettled: () => {
      if (vacancyId) void qc.invalidateQueries({ queryKey: ["interview-stages", vacancyId] })
    },
  })
}

export function useDeleteInterviewStage(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (stageId: number) => deleteInterviewStage(vacancyId!, stageId),
    onMutate: async (stageId) => {
      if (!vacancyId) return
      await qc.cancelQueries({ queryKey: ["interview-stages", vacancyId] })
      const prev = getCache(qc, vacancyId)
      patchStagesCache(qc, vacancyId, (items) => items.filter((it) => it.id !== stageId))
      return { prev }
    },
    onError: (err, _stageId, ctx) => {
      if (vacancyId && ctx?.prev) setCache(qc, vacancyId, ctx.prev)
      toast.error(err instanceof Error ? err.message : "Не удалось убрать этап")
    },
    onSettled: () => {
      if (vacancyId) void qc.invalidateQueries({ queryKey: ["interview-stages", vacancyId] })
    },
  })
}

export function useReorderInterviewStages(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (orderedIds: number[]) => reorderInterviewStages(vacancyId!, orderedIds),
    onMutate: async (orderedIds) => {
      if (!vacancyId) return
      await qc.cancelQueries({ queryKey: ["interview-stages", vacancyId] })
      const prev = getCache(qc, vacancyId)
      patchStagesCache(qc, vacancyId, (items) => {
        const byId = new Map(items.map((it) => [it.id, it]))
        return orderedIds
          .map((id) => byId.get(id))
          .filter((it): it is InterviewStageOut => it != null)
      })
      return { prev }
    },
    onError: (err, _orderedIds, ctx) => {
      if (vacancyId && ctx?.prev) setCache(qc, vacancyId, ctx.prev)
      toast.error(err instanceof Error ? err.message : "Не удалось изменить порядок")
    },
    onSettled: () => {
      if (vacancyId) void qc.invalidateQueries({ queryKey: ["interview-stages", vacancyId] })
    },
  })
}
