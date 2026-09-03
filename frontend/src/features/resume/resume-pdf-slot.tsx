/* Context + hook в одном файле — стандартный паттерн; fast-refresh для хука не критичен. */
/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import type { ResumeData } from "@/api/resume"
import { ResumePdfUpload } from "./ResumePdfUpload"

type ResumePdfSlot = {
  onParsed: (data: ResumeData) => void
  disabled?: boolean
  hasManualEdits?: boolean
}

const ResumePdfSlotContext = createContext<{
  slot: ResumePdfSlot | null
  setSlot: (slot: ResumePdfSlot | null) => void
}>({ slot: null, setSlot: () => {} })

/** Мост: форма регистрирует разбор PDF, композер чата рисует компактную загрузку. */
export function ResumePdfSlotProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<ResumePdfSlot | null>(null)
  const value = useMemo(() => ({ slot, setSlot }), [slot])
  return <ResumePdfSlotContext.Provider value={value}>{children}</ResumePdfSlotContext.Provider>
}

export function useRegisterResumePdfSlot(slot: ResumePdfSlot) {
  const { setSlot } = useContext(ResumePdfSlotContext)
  const { onParsed, disabled, hasManualEdits } = slot
  useEffect(() => {
    setSlot({ onParsed, disabled, hasManualEdits })
    return () => setSlot(null)
  }, [onParsed, disabled, hasManualEdits, setSlot])
}

export function ResumePdfUploadSlot({ compact }: { compact?: boolean }) {
  const { slot } = useContext(ResumePdfSlotContext)
  if (!slot) return null
  return (
    <ResumePdfUpload
      compact={compact}
      onParsed={slot.onParsed}
      disabled={slot.disabled}
      hasManualEdits={slot.hasManualEdits}
    />
  )
}
