import { describe, expect, it } from "vitest"
import type { HrQuestion, ScreeningQuestion } from "@/api/screening"
import { askQuestionCard, hrQuestionCard } from "./question-cards"

// Унификация HR-скрининга в Техичках: мок-вопросы screening-пакета (hr_questions/groups)
// маппятся в PrepQuestionOut[], чтобы лента PrepChatThread Техичек показывала их теми же
// карточками QuestionBubble, что и prep-вопросы тех. этапов. После вставки реальной расшифровки
// (stage="screening" в БД) hasRealDebriefForStage подменяет их пустым массивом — реальные вопросы
// видны в DebriefSection. Здесь покрываем сам маппинг — инвариант формы для QuestionBubble.

describe("hrQuestionCard", () => {
  it("маппит вопрос от HR в PrepQuestionOut с behavioral-категорией", () => {
    const q: HrQuestion = {
      question: "Опыт с RAG?",
      requirement: "Продовый опыт с RAG",
      intent: "проверяют глубину",
      draft_answer: "Гибрид двух слоёв.",
    }
    expect(hrQuestionCard(q)).toEqual({
      category: "behavioral",
      text: "Опыт с RAG?",
      hint: "проверяют глубину",
      answer: "Гибрид двух слоёв.",
      outcome: null,
      mastery: null,
      topic: "Продовый опыт с RAG",
    })
  })

  it("пустое требование → topic null (не пустая строка)", () => {
    const q: HrQuestion = {
      question: "Кем видите себя через год?",
      requirement: "   ",
      intent: "роверяют честность",
      draft_answer: "",
    }
    expect(hrQuestionCard(q).topic).toBeNull()
  })
})

describe("askQuestionCard", () => {
  it("маппит вопрос кандидата к HR в questions_to_ask с темой группы", () => {
    const q: ScreeningQuestion = {
      question: "Чем заменяете?",
      probe: "скрытая текучка",
      expect: "конкретика - хорошо",
    }
    expect(askQuestionCard(q, "Размытые границы роли")).toEqual({
      category: "questions_to_ask",
      text: "Чем заменяете?",
      hint: "скрытая текучка",
      answer: "конкретика - хорошо",
      outcome: null,
      mastery: null,
      topic: "Размытые границы роли",
    })
  })
})
