import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { useSyncExternalStore } from "react"
import { toast } from "sonner"
import {
  fetchResumeData,
  fetchResumeSkills,
  patchResumeData,
  patchResumeSkillState,
  refreshResumeSkillsStream,
  type ResumeData,
  type SkillsPanel,
  type SkillStateUpdate,
  type SkillSuggestionRow,
} from "@/api/resume"
import { OPENROUTER_MISSING_TOAST } from "@/lib/toasts"

export const SKILLS_REFRESH_MUTATION_KEY = ["resume", "skills", "refresh"] as const
export const SKILLS_APPLY_MUTATION_KEY = ["resume", "skills", "apply"] as const
export const SKILLS_APPLY_ALL_MUTATION_KEY = ["resume", "skills", "apply-all"] as const
export const SKILLS_SWAP_MUTATION_KEY = ["resume", "skills", "swap"] as const
export const SKILLS_STATE_MUTATION_KEY = ["resume", "skills", "user-state"] as const

type RefreshProgress = { done: number; total: number; label: string }

let refreshProgress: RefreshProgress | null = null
const progressListeners = new Set<() => void>()

function emitProgress() {
  for (const listener of progressListeners) listener()
}

function setRefreshProgress(next: RefreshProgress | null) {
  refreshProgress = next
  emitProgress()
}

export function useDemandRefreshProgress() {
  return useSyncExternalStore(
    (listener) => {
      progressListeners.add(listener)
      return () => {
        progressListeners.delete(listener)
      }
    },
    () => refreshProgress,
    () => null,
  )
}

/** Единый список «Навыки и спрос» (S-05, U-01). Дешёвый GET — снимок читается, не считается. */
export function useResumeSkills() {
  return useQuery({
    queryKey: ["resume", "skills"],
    queryFn: fetchResumeSkills,
    staleTime: 60_000,
  })
}

/** Пересобрать снимок (SSE-прогресс) — только по кнопке, никогда сама по себе (Решение 2). */
export function useRefreshResumeSkills() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: [...SKILLS_REFRESH_MUTATION_KEY],
    mutationFn: () =>
      refreshResumeSkillsStream((p) => {
        setRefreshProgress(p)
      }),
    onSettled: () => setRefreshProgress(null),
    onSuccess: (snapshot) => {
      qc.setQueryData<SkillsPanel>(["resume", "skills"], (prev) => ({
        rows: snapshot.rows,
        stale: false,
        stale_reason: "",
        selection_rule: snapshot.selection_rule,
        corpus_size: snapshot.corpus_size,
        slots_used: prev?.slots_used ?? 0,
        slots_limit: prev?.slots_limit ?? 30,
        created_at: snapshot.created_at,
      }))
      toast.success("Снимок навыков пересобран")
    },
    onError: () => toast.error(`Не удалось пересобрать навыки. ${OPENROUTER_MISSING_TOAST}`),
  })
}

/** «Скрыть» / «вернуть» одно предложение (Решение 6) — переживает перезагрузку, БД, не стейт. */
export function useSetSkillUserState() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: [...SKILLS_STATE_MUTATION_KEY],
    mutationFn: (body: SkillStateUpdate) => patchResumeSkillState(body),
    onSuccess: (row) => {
      qc.setQueryData<SkillsPanel>(["resume", "skills"], (prev) =>
        prev ? { ...prev, rows: prev.rows.map((r) => (r.skill === row.skill ? row : r)) } : prev,
      )
    },
    onError: () => toast.error("Не удалось обновить навык"),
  })
}

async function currentKeySkills(qc: QueryClient): Promise<string[]> {
  const cached = qc.getQueryData<ResumeData>(["resume", "data"])
  const data = cached ?? (await fetchResumeData())
  return data.key_skills ?? []
}

/** Применить одно действие строки (U-05, Решение 8) — add/drop/rename пишутся сразу в
 * `key_skills`, без «не забудь сохранить». Строка помечается `accepted` (переживает
 * перезагрузку — Решение 6) и на месте перекрашивается в `✓ держу`, минуя следующий
 * пересчёт снимка. */
export function useApplySkillAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: [...SKILLS_APPLY_MUTATION_KEY],
    mutationFn: async (row: SkillSuggestionRow) => {
      const previous = await currentKeySkills(qc)
      const oldKey = row.skill.toLowerCase()
      let next = previous
      if (row.state === "add") {
        next = previous.some((s) => s.toLowerCase() === oldKey)
          ? previous
          : [...previous, row.skill]
      } else if (row.state === "drop") {
        next = previous.filter((s) => s.toLowerCase() !== oldKey)
      } else if (row.state === "rename" && row.renames_to) {
        const newName = row.renames_to
        const newKey = newName.toLowerCase()
        const withoutOld = previous.filter((s) => s.toLowerCase() !== oldKey)
        next = withoutOld.some((s) => s.toLowerCase() === newKey)
          ? withoutOld
          : [...withoutOld, newName]
      }
      const saved = await patchResumeData({ key_skills: next })
      const updatedRow = await patchResumeSkillState({ skill: row.skill, user_state: "accepted" })
      return { saved, updatedRow }
    },
    onSuccess: ({ saved, updatedRow }) => {
      qc.setQueryData<ResumeData>(["resume", "data"], saved)
      qc.setQueryData<SkillsPanel>(["resume", "skills"], (prev) =>
        prev
          ? { ...prev, rows: prev.rows.map((r) => (r.skill === updatedRow.skill ? updatedRow : r)) }
          : prev,
      )
      void qc.invalidateQueries({ queryKey: ["resume", "gap"] })
    },
    onError: () => toast.error("Не удалось применить"),
  })
}

/** Обмен внутри строки (U-04, Решение 7): при 30/30 добавить можно только вместе с удалением
 * самого слабого `drop` из этого же снимка — одна правка `key_skills`, один PATCH. */
export function useSwapResumeSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: [...SKILLS_SWAP_MUTATION_KEY],
    mutationFn: async ({ add, drop }: { add: string; drop: string }) => {
      const previous = await currentKeySkills(qc)
      const dropKey = drop.toLowerCase()
      const withoutDrop = previous.filter((s) => s.toLowerCase() !== dropKey)
      const addKey = add.toLowerCase()
      const next = withoutDrop.some((s) => s.toLowerCase() === addKey)
        ? withoutDrop
        : [...withoutDrop, add]
      const saved = await patchResumeData({ key_skills: next })
      return { saved, previous }
    },
    onSuccess: ({ saved, previous }, { add, drop }) => {
      qc.setQueryData<ResumeData>(["resume", "data"], saved)
      void qc.invalidateQueries({ queryKey: ["resume", "skills"] })
      toast.success(`${add} добавлен, ${drop} убран`, {
        action: {
          label: "Отменить",
          onClick: () => {
            patchResumeData({ key_skills: previous })
              .then((restored) => {
                qc.setQueryData<ResumeData>(["resume", "data"], restored)
                void qc.invalidateQueries({ queryKey: ["resume", "skills"] })
              })
              .catch(() => toast.error("Не удалось отменить обмен"))
          },
        },
      })
    },
    onError: () => toast.error("Не удалось обменять навык"),
  })
}

/** «Применить все»: пакетно выполнить все pending-действия снимка (add/drop/rename) одним
 * набором правок `key_skills`, без построчных кликов. */
export function useApplyAllSkillActions() {
  const qc = useQueryClient()
  const applyAction = useApplySkillAction()
  return useMutation({
    mutationKey: [...SKILLS_APPLY_ALL_MUTATION_KEY],
    mutationFn: async (rows: SkillSuggestionRow[]) => {
      const results = []
      for (const row of rows) {
        // Последовательно, чтобы каждая правка видела итог предыдущей (currentKeySkills).
        // Параллельно нельзя — read-modify-write паттерн сломается.
        results.push(await applyAction.mutateAsync(row))
      }
      return results
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["resume", "gap"] })
      toast.success("Все действия по навыкам применены")
    },
    onError: () => toast.error("Не удалось применить все действия"),
  })
}
