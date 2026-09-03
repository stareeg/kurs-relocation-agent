import type { Job } from "@/api/jobs"
import type { PrepChatMessageOut, PrepChatRequest } from "@/api/prep"

/** Синхрон с `EXTERNAL_TRANSCRIPT_MARKER` в core/interview/prep.py */
const EXTERNAL_TRANSCRIPT_MARKER = "<<<COPILOT_EXTERNAL_TRANSCRIPT>>>"

export function formatExternalTranscriptMessage(transcript: string): string {
  return `Внешняя переписка (парсинг)\n\n${EXTERNAL_TRANSCRIPT_MARKER}\n${transcript.trim()}`
}

export function extractExternalTranscript(content: string): string | null {
  const idx = content.indexOf(EXTERNAL_TRANSCRIPT_MARKER)
  if (idx < 0) return null
  const rest = content.slice(idx + EXTERNAL_TRANSCRIPT_MARKER.length).replace(/^\n/, "")
  return rest.length > 0 ? rest : null
}

/** Канал реплики в единой ленте чата подготовки (UX8: разделение «Агент» / «Внешний ИИ»). */
export type PrepChatChannel = "agent" | "external"

// Явного поля-канала в записи нет (chat.py PrepChatMessageOut) — реплика внешнего ИИ узнаётся по
// маркеру транскрипта, ответ ассистента наследует канал реплики-вопроса перед ним (та же лента,
// хронологический порядок). Используется и для фильтра «глазик», и для подписи автора в пузыре.
export function classifyPrepChatChannels(messages: PrepChatMessageOut[]): PrepChatChannel[] {
  let current: PrepChatChannel = "agent"
  return messages.map((m) => {
    if (m.role === "user") {
      current = extractExternalTranscript(m.content) != null ? "external" : "agent"
    }
    return current
  })
}

/** Подпись реплики в ленте/буфере обмена — как messageAuthorLabel в разделе «Чаты». */
export function prepMessageAuthorLabel(mine: boolean, channel: PrepChatChannel): string {
  if (mine) return channel === "external" ? "Я → Внешний ИИ" : "Я"
  return channel === "external" ? "Внешний ИИ" : "Агент"
}

// План §6.6: у сообщения без текста (картинка и есть пузырь) при копировании подставляется
// заголовок распознавания — иначе вставка выделения в Telegram теряет смысл.
function prepMessageCopyBody(m: PrepChatMessageOut, body: string): string {
  if (body) return body
  const title = m.attachments?.[0]?.analysis?.title
  return m.attachments?.length ? `[картинка: ${title ?? "вложение"}]` : body
}

/** Текст выделенных сообщений чата подготовки для буфера обмена (выделение → Копировать). */
export function formatPrepMessagesForCopy(
  messages: PrepChatMessageOut[],
  channelById: Map<number, PrepChatChannel>,
): string {
  return messages
    .map((m) => {
      const mine = m.role === "user"
      const channel = channelById.get(m.id) ?? "agent"
      const external = mine ? extractExternalTranscript(m.content) : null
      const body = (external ?? sanitizeChatContent(m.content)).trim()
      return `${prepMessageAuthorLabel(mine, channel)}: ${prepMessageCopyBody(m, body)}`
    })
    .join("\n\n")
}

/** Убрать утечку JSON-конверта {"kind":"chat","text":...} из старых/битых реплик. */
export function sanitizeChatContent(content: string): string {
  const t = content.trim()
  if (!(t.startsWith("{") && t.includes('"kind"'))) return content
  try {
    const parsed = JSON.parse(t) as { text?: unknown }
    if (typeof parsed.text === "string" && parsed.text.trim()) return parsed.text.trim()
  } catch {
    /* fall through */
  }
  const m = t.match(/"text"\s*:\s*"((?:\\.|[^"\\])*)"/)
  if (m) {
    try {
      return JSON.parse(`"${m[1]}"`) as string
    } catch {
      return m[1].replace(/\\n/g, "\n").replace(/\\"/g, '"')
    }
  }
  return "Не удалось разобрать ответ. Напишите ещё раз."
}

// Общий билдер тела запроса чата подготовки — раньше жил только в PrepChat.tsx, теперь используется
// и точечными «канонными» отправками (клик по теме/вопросу в DebriefSection), чтобы контекст вакансии
// собирался одинаково независимо от того, кто инициировал сообщение.
export function buildPrepChatBody(
  job: Job | null,
  stage: string,
  focusTopics: string[],
  message: string,
  history: PrepChatMessageOut[],
  replyToMessageId?: number | null,
  attachmentIds?: number[],
): PrepChatRequest {
  const hasScore = !!job?.score && Object.keys(job.score).length > 0
  return {
    message,
    history: history.slice(-12),
    vacancy_text: job?.vacancy_text,
    title: job?.title,
    company: job?.company,
    salary_text: job?.salary_text,
    score: hasScore ? (job?.score as never) : null,
    stage: stage as never,
    focus_topics: focusTopics,
    ...(replyToMessageId != null ? { reply_to_message_id: replyToMessageId } : {}),
    ...(attachmentIds && attachmentIds.length > 0 ? { attachment_ids: attachmentIds } : {}),
  }
}
