import { useState } from "react"
import { Slider } from "@/components/ui/slider"
import {
  BONUS_PCT_DEFAULT,
  BONUS_PCT_STEPS,
  bonusPctIndex,
  type BonusPct,
} from "@/features/offers/bonus"

// Discrete exponential scale (5…150). Index-based so the thumb spends equal travel
// on 5→10 and on 100→150 — a linear 1–150 slider would bunch the useful 10–30% range.
export function BonusPctSlider({
  value,
  onCommit,
}: {
  value: number | null
  onCommit: (pct: BonusPct) => void
}) {
  const committedIdx = bonusPctIndex(value)
  const [draftIdx, setDraftIdx] = useState<number | null>(null)
  const idx = draftIdx ?? committedIdx
  const pct = BONUS_PCT_STEPS[idx] ?? BONUS_PCT_DEFAULT

  return (
    <div className="space-y-1">
      <p className="text-right text-sm font-semibold tabular-nums text-slate-900">{pct}%</p>
      <Slider
        min={0}
        max={BONUS_PCT_STEPS.length - 1}
        step={1}
        value={[idx]}
        onValueChange={([next]) => setDraftIdx(next ?? idx)}
        onValueCommit={([next]) => {
          const i = next ?? idx
          setDraftIdx(i)
          onCommit(BONUS_PCT_STEPS[i] ?? BONUS_PCT_DEFAULT)
        }}
        aria-label="Процент премии"
      />
      <div className="flex justify-between text-[10px] text-slate-400">
        <span>5%</span>
        <span>150%</span>
      </div>
    </div>
  )
}
