import { useState } from "react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { GameButton } from "./GameButton"
import { ANSWER_CHIPS, QUESTION_CHIPS, questionChipById } from "./chips"
import type { WolvesWsPublicState } from "./wolves-ws"

type LinesPanelProps = {
  pub: WolvesWsPublicState
  isHr: boolean
  mySeatId: string | null
  onIntent: (intent: Record<string, unknown>) => void
  vertical?: boolean
}

const MAX_ANSWER = 80

/** Фаза «Реплики» — чипы-ячейки без лишних подписей. */
export function LinesPanel({ pub, isHr, mySeatId, onIntent, vertical = false }: LinesPanelProps) {
  const [draft, setDraft] = useState("")
  const inLines = pub.phase === "lines"
  const questionId = pub.question_chip
  const question = questionId ? questionChipById(questionId) : undefined
  const answers = pub.answers ?? {}
  const myAnswered = mySeatId ? Boolean(answers[mySeatId]) : false
  const stamped = mySeatId ? Boolean(pub.stamps_this_slot?.[mySeatId]) : false
  const canAsk = isHr && inLines
  const canAnswer =
    Boolean(mySeatId) && !isHr && inLines && Boolean(questionId) && !myAnswered && !stamped

  if (!canAsk && !canAnswer) return null

  const sendAnswer = (text: string) => {
    const t = text.trim()
    if (!canAnswer || !t || t.length > MAX_ANSWER) return
    onIntent({ type: "answer_line", text: t.slice(0, MAX_ANSWER) })
    setDraft("")
  }

  const chipClass = (active: boolean) =>
    cn(
      "mp-cell mp-cell--selectable mp-mono w-full px-3 py-2.5 text-[length:var(--mp-text-sm)] text-white/90",
      active && "mp-cell--active",
    )

  return (
    <div className={vertical ? "space-y-2" : "shrink-0 space-y-2 p-3"}>
      {canAsk ? (
        <>
          <div className={`flex gap-1.5 ${vertical ? "flex-col" : "flex-wrap"}`}>
            {QUESTION_CHIPS.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onIntent({ type: "ask_question", chip_id: c.id })}
                className={chipClass(questionId === c.id)}
              >
                {c.label}
              </button>
            ))}
          </div>
          {question ? (
            <p className="mp-enter mp-mono rounded-md bg-[color:var(--mp-bulletin)]/20 px-3 py-2 text-[length:var(--mp-text-sm)] leading-snug text-white/90">
              {question.prompt}
            </p>
          ) : null}
        </>
      ) : null}

      {canAnswer ? (
        <>
          {question ? (
            <p className="mp-enter mp-mono rounded-md bg-[color:var(--mp-bulletin)]/20 px-3 py-2 text-[length:var(--mp-text-sm)] leading-snug text-white/90">
              {question.prompt}
            </p>
          ) : null}
          <div className={`flex gap-1.5 ${vertical ? "flex-col" : "flex-wrap"}`}>
            {ANSWER_CHIPS.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => sendAnswer(c.text)}
                className={chipClass(false)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className={`flex gap-2 ${vertical ? "flex-col" : ""}`}>
            <Input
              value={draft}
              maxLength={MAX_ANSWER}
              placeholder="Своя реплика…"
              className="mp-mono mp-cell h-10 border-0 bg-transparent text-[length:var(--mp-text-sm)] text-white/90 placeholder:text-white/35"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  sendAnswer(draft)
                }
              }}
            />
            <GameButton
              variant="standard"
              pulse={Boolean(draft.trim())}
              disabled={!draft.trim()}
              className={vertical ? "w-full" : ""}
              onClick={() => sendAnswer(draft)}
            >
              Сказать
            </GameButton>
          </div>
        </>
      ) : null}
    </div>
  )
}
