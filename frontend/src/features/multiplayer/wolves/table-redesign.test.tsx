// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ActionBar } from "./ActionBar"
import { Booth } from "./Booth"
import { CandidateHand } from "./CandidateHand"
import { LinesPanel } from "./LinesPanel"
import { Transcript } from "./Transcript"
import { PAPER_FIELDS } from "./papers"
import { QUESTION_CHIPS } from "./chips"
import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function seat(over: Partial<WolvesWsSeat> = {}): WolvesWsSeat {
  return {
    id: "c0",
    kind: "candidate",
    public_status: "waiting",
    filled: true,
    is_bot: true,
    nick: null,
    played: [],
    ...over,
  }
}

function pub(over: Partial<WolvesWsPublicState> = {}): WolvesWsPublicState {
  return {
    phase: "inspect",
    slot_index: 0,
    slot_count: 5,
    hr_energy: 4,
    hr_energy_max: 5,
    citations: 0,
    citations_limit: 3,
    bulletin: {
      day_label: "тащил сам или мимо",
      gates: ["Ищем тех, кто вёл продукт сам"],
      offer_allowed: false,
      cards_to_play: 1,
      required_tag: "ownership",
    },
    seats: [seat({ id: "c0", nick: "Костя" }), seat({ id: "c1", is_bot: true })],
    focus_candidate_id: "c0",
    discrepancy_marks: [],
    stamps_this_slot: {},
    answers: {},
    ...over,
  }
}

describe("редизайн стола — компоненты не падают и говорят по-русски", () => {
  it("кабинка: одна таблица-сличение, без «JD» и англицизмов тегов", () => {
    render(
      <Booth
        pub={pub()}
        isHr
        canInspect
        marks={["dates_mismatch"]}
        onToggleMark={() => {}}
        focusSeat={seat({ id: "c0", nick: "Костя" })}
      />,
    )
    expect(screen.getByText(/требование ↔ резюме/)).toBeTruthy()
    expect(screen.getByText(/Бумаги · Костя/)).toBeTruthy()
    expect(screen.getByText(/обязательно: вёл сам/)).toBeTruthy()
    expect(screen.getByText(/штамп ОФФЕР закрыт этот слот/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/\bJD\b/)
    expect(document.body.textContent).not.toMatch(/ownership|dual employment/i)
  })

  it("панель действий в фазе штампа: 4 штампа для фокусного, без сырого «reject»", () => {
    render(
      <ActionBar
        pub={pub({ phase: "stamp" })}
        role="hr"
        focusSeat={seat({ id: "c0", nick: "Костя" })}
        focusStamped={false}
        energy={4}
        offerAllowed
        marks={[]}
        claimFiled={false}
        pendingIntentType=""
        errorText={null}
        onIntent={() => {}}
      />,
    )
    expect(screen.getByRole("button", { name: /Штамп: На собес/ })).toBeTruthy()
    expect(screen.getByRole("button", { name: /Штамп: Отказ/ })).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/\breject\b|\binterview\b/)
  })

  it("панель действий в фазе штампа без фокуса — пустая (подсказка в шапке)", () => {
    const { container } = render(
      <ActionBar
        pub={pub({ phase: "stamp" })}
        role="hr"
        focusSeat={null}
        focusStamped={false}
        energy={4}
        offerAllowed
        marks={[]}
        claimFiled={false}
        pendingIntentType=""
        errorText={null}
        onIntent={() => {}}
      />,
    )
    expect(container.textContent).toBe("")
  })

  it("иск: кнопка называет цену −1⚡ и число выбранных", () => {
    render(
      <ActionBar
        pub={pub({ phase: "inspect" })}
        role="hr"
        focusSeat={seat()}
        focusStamped={false}
        energy={4}
        offerAllowed={false}
        marks={["dates_mismatch", "stack_lie"]}
        claimFiled={false}
        pendingIntentType=""
        errorText={null}
        onIntent={() => {}}
      />,
    )
    expect(screen.getByRole("button", { name: /Иск · −1⚡ \(2\/2\)/ })).toBeTruthy()
  })

  it("стенограмма зовёт игрока ником, а не c0", () => {
    render(<Transcript pub={pub({ phase: "lines", question_chip: "q_stack", answers: { c0: "Стек бил" } })} />)
    expect(screen.getByText(/Костя:/)).toBeTruthy()
    expect(screen.queryByText(/c0:/)).toBeNull()
  })

  it("реплики хрюши: чипы вопросов по-русски, без «Ownership»", () => {
    render(
      <LinesPanel
        pub={pub({ phase: "lines" })}
        isHr
        mySeatId={null}
        onIntent={() => {}}
      />,
    )
    for (const chip of QUESTION_CHIPS) {
      expect(screen.getByRole("button", { name: chip.label })).toBeTruthy()
    }
    expect(document.body.textContent).not.toMatch(/Ownership/)
  })

  it("рука кандидата: кнопка «Выложить», карты кликабельны", () => {
    render(
      <CandidateHand
        hand={[
          { id: "own_1", tag: "ownership", title: "Тащил с нуля" },
          { id: "scale_1", tag: "scale", title: "Нагрузка ×10" },
        ]}
        cardsToPlay={1}
        alreadyPlayed={false}
        canPlay
        onPlay={() => {}}
      />,
    )
    expect(screen.getByRole("button", { name: /Выложить · 0\/1/ })).toBeTruthy()
  })

  it("папки улик покрывают все шесть маркеров движка", () => {
    const ids = PAPER_FIELDS.map((f) => f.id)
    expect(ids).toEqual([
      "dates_mismatch",
      "ip_surname",
      "stack_lie",
      "team_size",
      "calendar_clash",
      "act_fake",
    ])
    const text = PAPER_FIELDS.map((f) => `${f.jdText} ${f.resumeText}`).join(" ")
    expect(text).not.toMatch(/continuous|ownership|dual employment/i)
  })
})
