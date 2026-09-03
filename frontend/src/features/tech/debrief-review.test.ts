import { describe, expect, it } from "vitest"
import type { DebriefAnalysis } from "@/api/debrief"
import { buildReviewRows, draftTranscriptTurns, strongPoints } from "./debrief-review"

function analysis(partial: Partial<DebriefAnalysis>): DebriefAnalysis {
  return {
    next_steps_signal: "unknown",
    overall_impression: 5,
    summary: "",
    interview_format: "other",
    ...partial,
  } as DebriefAnalysis
}

describe("buildReviewRows", () => {
  it("держит порядок собеса и склеивает оценку с разбором одного вопроса", () => {
    const rows = buildReviewRows(
      analysis({
        questions_asked: ["Что такое RAG?", "Как шардировали Postgres?", "Кафка или RabbitMQ?"],
        question_mastery: [
          { question: "Что такое RAG?", level: "confident" },
          { question: "Кафка или RabbitMQ?", level: "medium" },
        ],
        weak_answers: [
          {
            question: "Как шардировали Postgres?",
            what_went_wrong: "Не назвал ключ шардирования",
            how_to_improve: "Начни с ключа и распределения",
            reference_answer: "Шардируем по tenant_id",
          },
        ],
      }),
    )
    expect(rows.map((r) => r.question)).toEqual([
      "Что такое RAG?",
      "Как шардировали Postgres?",
      "Кафка или RabbitMQ?",
    ])
    expect(rows[0].level).toBe("confident")
    expect(rows[1].level).toBe("weak")
    expect(rows[1].fix).toBe("Начни с ключа и распределения")
    expect(rows[1].reference).toBe("Шардируем по tenant_id")
    expect(rows[2].level).toBe("medium")
  })

  it("вопрос без ответа в расшифровке — уровень unknown, без выдуманной оценки", () => {
    const rows = buildReviewRows(analysis({ questions_asked: ["А про Spark спрашивали?"] }))
    expect(rows).toHaveLength(1)
    expect(rows[0].level).toBe("unknown")
    expect(rows[0].problem).toBe("")
  })

  it("честно раскрытый пробел не в зачёт — перебивает оценку мастерства", () => {
    const rows = buildReviewRows(
      analysis({
        questions_asked: ["Работали с Kubernetes?"],
        question_mastery: [{ question: "Работали с Kubernetes?", level: "weak" }],
        honest_notes: [{ question: "Работали с Kubernetes?", note: "Сказал, что не трогал" }],
      }),
    )
    expect(rows[0].level).toBe("honest")
    expect(rows[0].problem).toBe("Сказал, что не трогал")
  })

  it("разобранный вопрос вне questions_asked не теряется", () => {
    const rows = buildReviewRows(
      analysis({
        questions_asked: ["Что такое RAG?"],
        weak_answers: [
          {
            question: "А про латентность?",
            what_went_wrong: "Промолчал",
            how_to_improve: "Назови p95",
            reference_answer: "",
          },
        ],
      }),
    )
    expect(rows.map((r) => r.question)).toEqual(["Что такое RAG?", "А про латентность?"])
  })

  it("совпадение вопросов не зависит от регистра, пробелов и хвостового знака", () => {
    const rows = buildReviewRows(
      analysis({
        questions_asked: ["Что  такое   RAG?"],
        question_mastery: [{ question: "что такое rag", level: "confident" }],
      }),
    )
    expect(rows[0].level).toBe("confident")
  })

  it("дубли в questions_asked схлопываются в одну строку", () => {
    const rows = buildReviewRows(
      analysis({ questions_asked: ["Что такое RAG?", "что такое RAG"] }),
    )
    expect(rows).toHaveLength(1)
  })
})

describe("strongPoints", () => {
  it("чистит пустые тезисы", () => {
    expect(strongPoints(analysis({ strong_answers: ["Хорошо про GraphRAG", "  ", ""] }))).toEqual([
      "Хорошо про GraphRAG",
    ])
  })
})

describe("draftTranscriptTurns", () => {
  it("подписи говорящих задают сторону реплики", () => {
    const turns = draftTranscriptTurns("HR: расскажите про опыт\nЯ: вёл команду из шести человек")
    expect(turns).toEqual([
      { speaker: "interviewer", text: "расскажите про опыт", ts: null },
      { speaker: "candidate", text: "вёл команду из шести человек", ts: null },
    ])
  })

  it("строка без подписи продолжает предыдущую реплику", () => {
    const turns = draftTranscriptTurns("Я: делал RAG\nна двух слоях")
    expect(turns).toHaveLength(1)
    expect(turns[0].text).toBe("делал RAG\nна двух слоях")
  })

  it("текст без подписей целиком считается репликой интервьюера", () => {
    const turns = draftTranscriptTurns("просто заметки после звонка")
    expect(turns).toEqual([
      { speaker: "interviewer", text: "просто заметки после звонка", ts: null },
    ])
  })

  it("режет длинную расшифровку по лимиту реплик", () => {
    const src = Array.from({ length: 10 }, (_, i) => `HR: q${i}\nЯ: a${i}`).join("\n")
    expect(draftTranscriptTurns(src, 5)).toHaveLength(5)
  })

  it("пустой вход даёт пустой список", () => {
    expect(draftTranscriptTurns("   \n\n")).toEqual([])
  })
})
