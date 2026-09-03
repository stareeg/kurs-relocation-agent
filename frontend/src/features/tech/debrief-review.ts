import type { DebriefAnalysis, MockMastery, TranscriptTurn } from "@/api/debrief"

// Сборка разбора расшифровки в ОДИН список «вопрос → как ответил → что доработать».
//
// Раньше эти же данные лежали в ленте тремя отдельными кучами (weak_answers / strong_answers /
// honest_notes как пузыри агента) плюс отдельным блоком мастерства на карточках вопросов — одна
// и та же оценка читалась дважды и выглядела набором несвязанных абзацев. Здесь LLM-поля
// сводятся к одной строке на вопрос: уровень + причина + как исправить + эталон.

/** Уровень ответа в строке разбора. `unknown` — вопрос задали, ответа в расшифровке нет. */
export type ReviewLevel = MockMastery | "unknown" | "honest"

export type ReviewRow = {
  /** Текст вопроса (у «сильных» тезисов без привязки к вопросу — сам тезис). */
  question: string
  level: ReviewLevel
  /** Что пошло не так (weak_answers) или что владелец честно признал (honest_notes). */
  problem: string
  /** Как отвечать в следующий раз (weak_answers.how_to_improve). */
  fix: string
  /** Эталонный ответ, если LLM его дала. */
  reference: string
}

function norm(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, " ").replace(/[?!.,:;—–-]+$/g, "")
}

/**
 * Один список строк разбора в порядке `questions_asked` (порядок собеса), затем — то, что LLM
 * упомянула в weak/honest, но не положила в `questions_asked`, затем «что зашло» из
 * `strong_answers` (у них нет привязки к вопросу — это короткие тезисы).
 */
export function buildReviewRows(a: DebriefAnalysis): ReviewRow[] {
  const weakByQuestion = new Map<string, ReviewRow>()
  for (const w of a.weak_answers ?? []) {
    const q = (w.question ?? "").trim()
    if (!q) continue
    weakByQuestion.set(norm(q), {
      question: q,
      level: "weak",
      problem: (w.what_went_wrong ?? "").trim(),
      fix: (w.how_to_improve ?? "").trim(),
      reference: (w.reference_answer ?? "").trim(),
    })
  }
  const honestByQuestion = new Map<string, ReviewRow>()
  for (const n of a.honest_notes ?? []) {
    const q = (n.question ?? "").trim()
    if (!q) continue
    honestByQuestion.set(norm(q), {
      question: q,
      level: "honest",
      problem: (n.note ?? "").trim(),
      fix: "",
      reference: "",
    })
  }
  const masteryByQuestion = new Map<string, MockMastery>()
  for (const m of a.question_mastery ?? []) {
    const q = (m.question ?? "").trim()
    if (!q || !m.level) continue
    masteryByQuestion.set(norm(q), m.level)
  }

  const rows: ReviewRow[] = []
  const used = new Set<string>()

  for (const raw of a.questions_asked ?? []) {
    const q = (raw ?? "").trim()
    if (!q) continue
    const key = norm(q)
    if (used.has(key)) continue
    used.add(key)
    // Честно раскрытый пробел вне зачёта — сильнее любой оценки мастерства (см. debrief-промпт:
    // такой вопрос не тянет оценку ни вверх, ни вниз).
    const honest = honestByQuestion.get(key)
    if (honest) {
      rows.push({ ...honest, question: q })
      continue
    }
    const weak = weakByQuestion.get(key)
    if (weak) {
      rows.push({ ...weak, question: q })
      continue
    }
    rows.push({
      question: q,
      level: masteryByQuestion.get(key) ?? "unknown",
      problem: "",
      fix: "",
      reference: "",
    })
  }

  // Хвост: LLM иногда разбирает вопрос, которого нет в questions_asked — терять его нельзя.
  for (const [key, row] of honestByQuestion) {
    if (used.has(key)) continue
    used.add(key)
    rows.push(row)
  }
  for (const [key, row] of weakByQuestion) {
    if (used.has(key)) continue
    used.add(key)
    rows.push(row)
  }

  return rows
}

/** Короткие тезисы «что зашло» — без привязки к конкретному вопросу, поэтому отдельным списком. */
export function strongPoints(a: DebriefAnalysis): string[] {
  return (a.strong_answers ?? []).map((s) => (s ?? "").trim()).filter(Boolean)
}

const SPEAKER_INTERVIEWER =
  /^(интервьюер|интервьювер|собеседующий|рекрутер|рекрутёр|hr|hr-менеджер|они|он|она|interviewer|recruiter)\s*[:：]/i
const SPEAKER_CANDIDATE = /^(я|кандидат|candidate|me|мой ответ|ответ)\s*[:：]/i

/**
 * Черновая разбивка только что вставленной расшифровки на реплики — чтобы во время разбора
 * (LLM-задача идёт в фоне десятки секунд) владелец сразу видел свой текст диалогом, а не пустое
 * место со спиннером. Готовая сегментация приезжает от LLM (`analysis.transcript_turns`) и
 * заменяет эту.
 *
 * Правила простые и предсказуемые: подпись говорящего в начале строки задаёт сторону, без подписи
 * реплика продолжает предыдущую, а самый первый безымянный блок считаем вопросом интервьюера.
 */
export function draftTranscriptTurns(transcript: string, limit = 40): TranscriptTurn[] {
  const turns: TranscriptTurn[] = []
  let speaker: TranscriptTurn["speaker"] = "interviewer"
  for (const rawLine of transcript.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    let text = line
    let switched = false
    if (SPEAKER_INTERVIEWER.test(line)) {
      speaker = "interviewer"
      text = line.replace(SPEAKER_INTERVIEWER, "").trim()
      switched = true
    } else if (SPEAKER_CANDIDATE.test(line)) {
      speaker = "candidate"
      text = line.replace(SPEAKER_CANDIDATE, "").trim()
      switched = true
    }
    const prev = turns[turns.length - 1]
    if (!switched && prev && prev.speaker === speaker) {
      prev.text = `${prev.text}\n${text}`
      continue
    }
    if (!text) continue
    if (turns.length >= limit) break
    turns.push({ speaker, text, ts: null })
  }
  return turns
}
