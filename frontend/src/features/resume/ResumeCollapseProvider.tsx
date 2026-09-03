import { useCallback, useMemo, useState, type ReactNode } from "react"

import { ResumeCollapseContext, type ResumeCollapseState } from "./resume-collapse-context"

export function ResumeCollapseProvider({ children }: { children: ReactNode }) {
  const [signal, setSignal] = useState(0)
  const [collapse, setCollapse] = useState(false)
  const apply = useCallback((next: boolean) => {
    setCollapse(next)
    setSignal((s) => s + 1)
  }, [])
  const value = useMemo<ResumeCollapseState>(
    () => ({ signal, collapse, apply }),
    [signal, collapse, apply],
  )
  return <ResumeCollapseContext.Provider value={value}>{children}</ResumeCollapseContext.Provider>
}
