import { describe, expect, it } from "vitest"
import {
  buildExclude,
  EMPTY_SUGGEST_STATE,
  MAX_SEEN,
  nextSuggestState,
  pickFresh,
  rememberSeen,
  type PriorityCandidate,
  type SuggestState,
} from "./priority-suggest"

const cand = (label: string, reason = ""): PriorityCandidate => ({ label, reason })

const state = (patch: Partial<SuggestState> = {}): SuggestState => ({
  ...EMPTY_SUGGEST_STATE,
  ...patch,
})

describe("buildExclude", () => {
  it("регресс: показанные ярлыки попадают в exclude, а не только выбранные", () => {
    // Ровно тот баг: без seen вход запроса не менялся между нажатиями → LLM cache hit → та же
    // порция вариантов → «кнопка ничего не делает».
    const seen = ["LLM & RAG", "MLOps"]
    expect(buildExclude([], seen)).toEqual(["LLM & RAG", "MLOps"])
  })

  it("склеивает выбранное и показанное без дублей", () => {
    expect(buildExclude(["MLOps"], ["MLOps", "Agentic AI"])).toEqual(["MLOps", "Agentic AI"])
  })

  it("обрезает историю до MAX_SEEN", () => {
    const seen = Array.from({ length: MAX_SEEN + 10 }, (_, i) => `n${i}`)
    expect(buildExclude([], seen)).toHaveLength(MAX_SEEN)
  })

  it("пустой вход → пустой exclude (первое нажатие)", () => {
    expect(buildExclude([], [])).toEqual([])
  })
})

describe("pickFresh", () => {
  it("отбрасывает уже показанное и уже выбранное", () => {
    const got = pickFresh(
      [cand("MLOps"), cand("Agentic AI"), cand("AI Safety")],
      ["MLOps"],
      ["Agentic AI"],
    )
    expect(got.map((c) => c.label)).toEqual(["AI Safety"])
  })

  it("модель вернула только старое → пусто (сигнал «круг пройден»)", () => {
    expect(pickFresh([cand("MLOps"), cand("MLOps")], [], ["MLOps"])).toEqual([])
  })

  it("чистит пробелы и выкидывает пустые ярлыки", () => {
    expect(pickFresh([cand("  RAG  "), cand("   ")], [], []).map((c) => c.label)).toEqual(["RAG"])
  })

  it("режет дубли внутри одного ответа", () => {
    expect(pickFresh([cand("RAG"), cand("RAG")], [], [])).toHaveLength(1)
  })

  it("уважает лимит", () => {
    const many = Array.from({ length: 20 }, (_, i) => cand(`n${i}`))
    expect(pickFresh(many, [], [], 6)).toHaveLength(6)
  })
})

describe("rememberSeen", () => {
  it("два нажатия подряд дают растущий exclude — кэш не может залипнуть", () => {
    let seen: string[] = []
    const first = pickFresh([cand("MLOps"), cand("RAG")], [], seen)
    seen = rememberSeen(seen, first)
    const excludeSecondClick = buildExclude([], seen)

    expect(excludeSecondClick).toEqual(["MLOps", "RAG"])
    // Ключ кэша считается от текста запроса: другой exclude → другой вход → реальный вызов.
    expect(buildExclude([], [])).not.toEqual(excludeSecondClick)

    const second = pickFresh([cand("MLOps"), cand("Agentic AI")], [], seen)
    expect(second.map((c) => c.label)).toEqual(["Agentic AI"])
  })

  it("не растёт выше MAX_SEEN", () => {
    const seen = Array.from({ length: MAX_SEEN }, (_, i) => `n${i}`)
    expect(rememberSeen(seen, [cand("новое")])).toHaveLength(MAX_SEEN)
    expect(rememberSeen(seen, [cand("новое")])).toContain("новое")
  })
})

describe("nextSuggestState", () => {
  it("новая порция: кандидаты заменяются, seen накапливается", () => {
    const prev = state({ candidates: [cand("MLOps")], seen: ["MLOps"] })
    const got = nextSuggestState(prev, { priorities: [cand("RAG"), cand("MLOps")] }, [])

    expect(got.kind).toBe("fresh")
    expect(got.state.candidates.map((c) => c.label)).toEqual(["RAG"])
    expect(got.state.seen).toEqual(["MLOps", "RAG"])
  })

  it("исчерпание: seen сбрасывается, кандидаты на экране остаются", () => {
    const prev = state({ candidates: [cand("MLOps")], seen: ["MLOps", "RAG"] })
    const got = nextSuggestState(prev, { priorities: [cand("MLOps"), cand("RAG")] }, [])

    expect(got.kind).toBe("exhausted")
    expect(got.state.seen).toEqual([])
    expect(got.state.candidates.map((c) => c.label)).toEqual(["MLOps"])
  })

  it("уже выбранные приоритеты не возвращаются как кандидаты", () => {
    const got = nextSuggestState(state(), { priorities: [cand("MLOps"), cand("RAG")] }, ["MLOps"])
    expect(got.state.candidates.map((c) => c.label)).toEqual(["RAG"])
  })

  it("оси профиля запоминаются, в том числе на исчерпанном круге", () => {
    const prev = state({ seen: ["MLOps"] })
    const got = nextSuggestState(
      prev,
      { priorities: [cand("MLOps")], role_kind: "И то, и другое", market_segment: "IT" },
      [],
    )

    expect(got.kind).toBe("exhausted")
    expect(got.state.roleKind).toBe("И то, и другое")
    expect(got.state.marketSegment).toBe("IT")
  })

  it("пустые оси в ответе не затирают ранее полученную подсказку", () => {
    const prev = state({ roleKind: "Делаю руками", marketSegment: "IT" })
    const got = nextSuggestState(prev, { priorities: [cand("RAG")], role_kind: "  " }, [])

    expect(got.state.roleKind).toBe("Делаю руками")
    expect(got.state.marketSegment).toBe("IT")
  })

  it("ответ без полей (схема их допускает опциональными) не падает", () => {
    const got = nextSuggestState(state(), {}, [])
    expect(got.kind).toBe("exhausted")
    expect(got.state).toEqual(EMPTY_SUGGEST_STATE)
  })
})
