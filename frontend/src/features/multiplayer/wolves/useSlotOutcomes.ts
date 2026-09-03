import { useEffect, useRef, useState } from "react"
import { deriveSlotOutcome, type SlotOutcomeMap } from "./slotOutcomes"
import type { WolvesWsPublicState } from "./wolves-ws"

type SnapShot = {
  slot_index: number
  phase: string
  stamps: Record<string, string>
  ticker: string | null | undefined
}

/** Накапливает итоги закрытых слотов по смене slot_index / переходу в reveal. */
export function useSlotOutcomes(pub: WolvesWsPublicState | undefined): SlotOutcomeMap {
  const [outcomes, setOutcomes] = useState<SlotOutcomeMap>({})
  const prevRef = useRef<SnapShot | null>(null)
  const recordedRef = useRef<Set<number>>(new Set())

  useEffect(() => {
    if (!pub) return

    const prev = prevRef.current
    const record = (slotIdx: number, stamps: Record<string, string>, ticker?: string | null) => {
      if (recordedRef.current.has(slotIdx)) return
      recordedRef.current.add(slotIdx)
      setOutcomes((o) => ({
        ...o,
        [slotIdx]: deriveSlotOutcome(stamps, ticker),
      }))
    }

    if (prev) {
      if (pub.slot_index > prev.slot_index) {
        record(prev.slot_index, prev.stamps, prev.ticker)
      }
      if (
        (pub.phase === "reveal" || pub.phase === "ended") &&
        prev.phase === "result" &&
        pub.slot_index === prev.slot_index
      ) {
        record(prev.slot_index, prev.stamps, prev.ticker)
      }
    }

    prevRef.current = {
      slot_index: pub.slot_index,
      phase: pub.phase,
      stamps: { ...(pub.stamps_this_slot ?? {}) },
      ticker: pub.slot_ticker,
    }
  }, [pub])

  useEffect(() => {
    if (pub?.phase === "lobby") {
      setOutcomes({})
      recordedRef.current = new Set()
      prevRef.current = null
    }
  }, [pub?.phase])

  return outcomes
}
