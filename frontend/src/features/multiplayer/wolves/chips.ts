/**
 * Чипы реплик — id совпадают с `QUESTION_CHIPS` в `core/domains/multiplayer/deck.py`.
 * Ответ-чипы — только UI: уходят как `answer_line.text` (≤80).
 */

export type QuestionChip = {
  id: string
  /** Короткий ярлык на кнопке */
  label: string
  /** Полная формулировка «вопроса дня» */
  prompt: string
}

export type AnswerChip = {
  id: string
  label: string
  /** Текст, который уйдёт на сервер */
  text: string
}

/** Канон вопрос-чипов хрюши (порядок = deck.QUESTION_CHIPS). */
export const QUESTION_CHIPS: readonly QuestionChip[] = [
  {
    id: "q_incident",
    label: "Инцидент",
    prompt: "Расскажи про инцидент: что роняли и кто поднял?",
  },
  {
    id: "q_ownership",
    label: "Своя зона",
    prompt: "Где ты отвечал сам, а не «мы командой»?",
  },
  {
    id: "q_stack",
    label: "Стек",
    prompt: "Какой стек реально в проде, без «видел»?",
  },
  {
    id: "q_why_us",
    label: "Почему мы",
    prompt: "Почему эта вакансия, а не соседний оффер?",
  },
  {
    id: "q_salary",
    label: "Вилка",
    prompt: "Вилка и запасной оффер: что на столе до пятницы?",
  },
  {
    id: "q_second_job",
    label: "Календарь",
    prompt: "Стендапы в двух местах — как с календарем?",
  },
] as const

/** Готовые ответы кандидата (альтернатива свободному вводу). */
export const ANSWER_CHIPS: readonly AnswerChip[] = [
  { id: "a_stack", label: "Стек бил", text: "Стек бил, дедлайны жёсткие." },
  { id: "a_own", label: "Тащил один", text: "Тащил один, тимлид был в отпуске." },
  { id: "a_inc", label: "Поднял прод", text: "Поднял прод за ночь, постмортем на утро." },
  { id: "a_batna", label: "Есть контр", text: "Контр уже на столе — выше вилка." },
  { id: "a_soft", label: "Без эскалации", text: "Погасил конфликт без эскалации в Slack." },
  { id: "a_bluff", label: "Звучит гладко", text: "Мы закрыли эпик в срок, детали в резюме." },
] as const

export const QUESTION_CHIP_IDS: readonly string[] = QUESTION_CHIPS.map((c) => c.id)

export function questionChipById(id: string): QuestionChip | undefined {
  return QUESTION_CHIPS.find((c) => c.id === id)
}
