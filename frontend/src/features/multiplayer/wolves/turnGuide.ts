/**
 * Э35.1: «что делать сейчас» — одна строка, всегда на виду.
 *
 * Фаза на экране раньше читалась только по подсвеченному сегменту `PhaseRail` и по тому,
 * какие кнопки вдруг стали активными. Здесь ответ на два вопроса сразу: что происходит и
 * чей ход. Тексты — в одной таблице (пара «фаза × роль»), а не рассыпаны по компонентам.
 */

export type TurnRole = "hr" | "candidate" | "spectator"

export type TurnGuideInput = {
  /** Сырая фаза движка, включая `between` / `lobby` / `reveal`. */
  phase: string
  role: TurnRole
  /** Фаза `play`: сколько кандидатов выложили карты из скольких. */
  playedCount?: number
  candidateCount?: number
  /** Фаза `play` (кандидат): сколько карт требует бюллетень. */
  cardsToPlay?: number
  /** Фаза `stamp` (хрюша): сколько кандидатов ещё без штампа. */
  toStamp?: number
  /** Хрюша, фаза `inspect`: иск уже подан. */
  claimFiled?: boolean
  /** Кандидат — своё состояние в текущем слоте. */
  iPlayed?: boolean
  iAnswered?: boolean
  iStamped?: boolean
  /** Вопрос хрюши уже задан (фаза `lines`). */
  questionAsked?: boolean
  /** Зритель между слотами может сесть вместо бота. */
  canSit?: boolean
}

export type TurnGuide = {
  /** Что делать / что происходит — одна фраза. */
  text: string
  /** true = ход не твой, просто ждёшь (блок в приглушённом тоне). */
  waiting: boolean
}

const act = (text: string): TurnGuide => ({ text, waiting: false })
const wait = (text: string): TurnGuide => ({ text, waiting: true })

function hrGuide(i: TurnGuideInput): TurnGuide {
  switch (i.phase) {
    case "bulletin":
      return act("Прочти бюллетень и жми «Ок, к подаче карт»")
    case "play":
      return wait(
        `Ждёшь карты кандидатов — выложили ${i.playedCount ?? 0} из ${i.candidateCount ?? 0}`,
      )
    case "inspect":
      return i.claimFiled
        ? act("Иск подан — жми «К суду»")
        : act("Отметь две несостыковки в бумагах и подай иск, или жми «Далее»")
    case "lines":
      return act("Задай кандидатам вопрос, потом «Далее»")
    case "stamp":
      return (i.toStamp ?? 0) > 0
        ? act(`Штампуй кандидатов — осталось ${i.toStamp}`)
        : wait("Решения по кандидатам приняты — ждёшь")
    case "judge":
      return wait("Судья разбирает иск…")
    case "result":
      return act("Итог слота — жми «Закрыть слот»")
    case "between":
      return wait("Передышка перед следующим слотом")
    default:
      return wait("Ждёшь начала слота")
  }
}

function candidateGuide(i: TurnGuideInput): TurnGuide {
  switch (i.phase) {
    case "bulletin":
      return wait("Смотри вакансию слота — скоро твой ход")
    case "play":
      if (i.iPlayed) return wait("Карты на столе — ждёшь остальных")
      return act(
        i.cardsToPlay && i.cardsToPlay > 1
          ? `Выложи ${i.cardsToPlay} карты опыта`
          : "Выложи карту опыта",
      )
    case "inspect":
      return wait("Хрюша изучает бумаги — жди")
    case "lines":
      if (i.iStamped) return wait("Решение по тебе принято")
      if (!i.questionAsked) return wait("Ждёшь вопрос хрюши")
      if (i.iAnswered) return wait("Ответ ушёл — ждёшь остальных")
      return act("Ответь на вопрос хрюши — чип или своя строка")
    case "stamp":
      return wait("Хрюша решает по тебе — жди")
    case "judge":
      return wait("Судья разбирает иск — жди")
    case "result":
      return wait("Итог слота")
    case "between":
      return wait("Передышка перед следующим слотом")
    default:
      return wait("Ждёшь начала слота")
  }
}

function spectatorGuide(i: TurnGuideInput): TurnGuide {
  if (i.phase === "between" && i.canSit) {
    return act("Между слотами можно сесть вместо бота")
  }
  return wait("Смотришь партию")
}

export function turnGuide(i: TurnGuideInput): TurnGuide {
  if (i.role === "hr") return hrGuide(i)
  if (i.role === "candidate") return candidateGuide(i)
  return spectatorGuide(i)
}
