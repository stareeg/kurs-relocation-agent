import type { PrepQuestionOut } from "@/api/prep"
import type { HrQuestion, ScreeningQuestion } from "@/api/screening"

// Общий маппинг вопросов пакета Скринингов (hr_questions/groups) в PrepQuestionOut — форму,
// которую понимает QuestionBubble (features/tech/PrepChat.tsx). Раньше жил только в
// HrScreeningPrepView (Техички); теперь тот же маппинг нужен и QuestionsChatPanel (Скрининги) и
// TechPage (мок-вопросы HR-скрининга как контент ленты Техичек) — вынесен сюда, чтобы не плодить
// копии.

export function hrQuestionCard(q: HrQuestion): PrepQuestionOut {
  return {
    category: "behavioral",
    text: q.question,
    hint: q.intent,
    answer: q.draft_answer,
    outcome: null,
    mastery: null,
    // Требование вакансии, на стыке с которым появился вопрос — вместо отдельного списка
    // «Требования вакансии» в левой панели (дублировал этот же вопрос).
    topic: q.requirement?.trim() || null,
  }
}

export function askQuestionCard(q: ScreeningQuestion, groupTitle: string): PrepQuestionOut {
  return {
    category: "questions_to_ask",
    text: q.question,
    hint: q.probe,
    answer: q.expect,
    outcome: null,
    mastery: null,
    topic: groupTitle,
  }
}
