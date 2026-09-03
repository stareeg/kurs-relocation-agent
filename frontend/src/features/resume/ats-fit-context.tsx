/**
 * FR2-34/35/38: общий стейт пайплайна «Подогнать под ATS» + прогресс блоков.
 * Кнопка в ResumeScoreCard → правки текста инлайн (U-07: навыки сюда больше не заходят —
 * предложения по навыкам живут только в снимке S-04 / `SkillsPanel`, U-01).
 */
/* Context + hook в одном файле — стандартный паттерн; fast-refresh для хука не критичен. */
/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import type { AtsFitResult } from "@/api/resume"
import {
  invalidateResumeScore,
  notifyAtsApplied,
  useAtsFitResume,
  type AtsFitProgress,
} from "./use-resume"

export type AtsFitTextProposal = {
  key: string
  label: string
  original: string
  proposed: string
}

function collectOkProposals(result: AtsFitResult | null): AtsFitTextProposal[] {
  if (!result) return []
  const out: AtsFitTextProposal[] = []
  for (const exp of result.experience ?? []) {
    if (exp.status === "ok" && exp.proposed.trim()) {
      const who =
        [exp.company, exp.position].filter(Boolean).join(" · ") || `Опыт #${exp.index + 1}`
      out.push({
        key: `exp:${exp.index}`,
        label: who,
        original: exp.original ?? "",
        proposed: exp.proposed,
      })
    }
  }
  const about = result.about
  if (about?.status === "ok" && about.proposed.trim()) {
    out.push({
      key: "about",
      label: "Обо мне",
      original: about.original ?? "",
      proposed: about.proposed,
    })
  }
  return out
}

export type AtsFitContextValue = {
  run: () => void
  isPending: boolean
  isError: boolean
  result: AtsFitResult | null
  /** FR2-38: прогресс параллельных блоков во время пайплайна. */
  progress: AtsFitProgress | null
  clear: () => void
  allOk: AtsFitTextProposal[]
  pending: AtsFitTextProposal[]
  /** Текстовые блоки (для счётчика сводки). */
  totalOk: number
  pendingCount: number
  acceptedCount: number
  hasActionable: boolean
  proposalFor: (key: string) => AtsFitTextProposal | null
  markAccepted: (key: string) => void
  dismiss: (key: string) => void
  skipAll: () => void
}

const AtsFitContext = createContext<AtsFitContextValue | null>(null)

export function AtsFitProvider({ children }: { children: ReactNode }) {
  const [progress, setProgress] = useState<AtsFitProgress | null>(null)
  const mutation = useAtsFitResume(setProgress)
  const [result, setResult] = useState<AtsFitResult | null>(null)
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set())
  const [acceptedCount, setAcceptedCount] = useState(0)

  const resetLocal = useCallback(() => {
    setDismissed(new Set())
    setAcceptedCount(0)
  }, [])

  // Только из явного клика (ResumeScoreCard). Не вызывать из рендера / при mount —
  // иначе StrictMode даст двойной платный LLM-запрос (FR2-64, бывший GapAuditSheet).
  const run = useCallback(() => {
    setResult(null)
    setProgress(null)
    resetLocal()
    mutation.mutate(undefined, {
      onSuccess: (data) => {
        setResult(data)
        setProgress(null)
        resetLocal()
      },
      onError: () => setProgress(null),
    })
  }, [mutation, resetLocal])

  const clear = useCallback(() => {
    setResult(null)
    setProgress(null)
    resetLocal()
    mutation.reset()
  }, [mutation, resetLocal])

  const allOk = useMemo(() => collectOkProposals(result), [result])

  const pending = useMemo(() => allOk.filter((p) => !dismissed.has(p.key)), [allOk, dismissed])

  const totalOk = allOk.length
  const pendingCount = pending.length
  const hasActionable = totalOk > 0

  const dismiss = useCallback((key: string) => {
    setDismissed((prev) => new Set(prev).add(key))
  }, [])

  const qc = useQueryClient()

  // Принятая правка сразу уходит в сохранённое резюме (через хук формы) и инвалидирует балл —
  // не ждём ручного «Сохранить».
  const markAccepted = useCallback(
    (key: string) => {
      setAcceptedCount((n) => n + 1)
      setDismissed((prev) => new Set(prev).add(key))
      notifyAtsApplied()
      invalidateResumeScore(qc)
    },
    [qc],
  )

  const skipAll = useCallback(() => {
    setDismissed(new Set(allOk.map((p) => p.key)))
  }, [allOk])

  const proposalFor = useCallback(
    (key: string) => pending.find((p) => p.key === key) ?? null,
    [pending],
  )

  const value = useMemo<AtsFitContextValue>(
    () => ({
      run,
      isPending: mutation.isPending,
      isError: mutation.isError,
      result,
      progress,
      clear,
      allOk,
      pending,
      totalOk,
      pendingCount,
      acceptedCount,
      hasActionable,
      proposalFor,
      markAccepted,
      dismiss,
      skipAll,
    }),
    [
      run,
      clear,
      mutation.isPending,
      mutation.isError,
      result,
      progress,
      allOk,
      pending,
      totalOk,
      pendingCount,
      acceptedCount,
      hasActionable,
      proposalFor,
      markAccepted,
      dismiss,
      skipAll,
    ],
  )

  return <AtsFitContext.Provider value={value}>{children}</AtsFitContext.Provider>
}

export function useAtsFit(): AtsFitContextValue {
  const ctx = useContext(AtsFitContext)
  if (!ctx) {
    throw new Error("useAtsFit: нужен AtsFitProvider (ResumePage)")
  }
  return ctx
}
