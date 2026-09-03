/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react"
import type { ScoreFixItem } from "./resume-score-fixes"

export type ScoreFixApplyHandler = (fix: ScoreFixItem) => void

type ScoreFixApplyContextValue = {
  applyFix: ScoreFixApplyHandler
  registerApply: (handler: ScoreFixApplyHandler | null) => void
}

const ScoreFixApplyContext = createContext<ScoreFixApplyContextValue | null>(null)

export function ScoreFixApplyProvider({ children }: { children: ReactNode }) {
  const handlerRef = useRef<ScoreFixApplyHandler | null>(null)
  const applyFix = useCallback((fix: ScoreFixItem) => {
    handlerRef.current?.(fix)
  }, [])
  const registerApply = useCallback((handler: ScoreFixApplyHandler | null) => {
    handlerRef.current = handler
  }, [])
  const value = useMemo(
    () => ({ applyFix, registerApply }),
    [applyFix, registerApply],
  )
  return <ScoreFixApplyContext.Provider value={value}>{children}</ScoreFixApplyContext.Provider>
}

export function useRegisterScoreFixApply(handler: ScoreFixApplyHandler | null) {
  const ctx = useContext(ScoreFixApplyContext)
  useEffect(() => {
    if (!ctx) return
    ctx.registerApply(handler)
    return () => ctx.registerApply(null)
  }, [handler, ctx])
}

export function useScoreFixApply(): ScoreFixApplyHandler | null {
  const ctx = useContext(ScoreFixApplyContext)
  return ctx?.applyFix ?? null
}
