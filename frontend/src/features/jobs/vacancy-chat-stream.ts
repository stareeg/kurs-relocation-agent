import type { QueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import { streamChat } from "@/api/chat"
import type { SseEvent } from "@/api/sse"
import type { AttachmentOut } from "@/api/attachments"
import type { ConversationOut, ConvMessage } from "@/api/conversations"
import type { Job } from "@/api/jobs"

// Стрим ответа агента живёт ЗДЕСЬ, а не в состоянии компонента (баг «ответ агента пропадает при
// переключении диалога», 2026-08-03): `VacancyConversationPane` монтируется с `key={vacancyId}`
// (ChatPage.tsx), так что смена вакансии в разделе Чаты полностью уничтожает компонент. Раньше
// `pending`/`isRunning` были локальным useState, а размонтирование дёргало `abortRef.current?.abort()`
// — это рвало fetch к `/api/chat/stream`, бэкенд (`stream_answer`) ловил отмену ДО записи обмена в
// БД (`append_llm_exchange` вызывается только после полного стрима) и обмен исчезал целиком, а не
// только оптимистичный пузырь. Здесь стрим не привязан к жизненному циклу React-компонента и его
// никто не абортит на unmount — вкладка может уйти в фон и вернуться, ответ доедет и запишется.
//
// Очередь, а не одиночный слот (2026-08-11, баг «второй вопрос стирает первый»): раньше `pending`
// был единственным полем — если владелец отправлял новый вопрос до того, как предыдущий обмен
// подтверждённо лёг в кэш `messages`, второй `ask()` либо молча ничего не делал (гард по
// `isRunning`), либо, если `isRunning` уже успел сброситься, целиком перезаписывал `pending` и
// неподтверждённый первый ответ пропадал с экрана. Теперь у вакансии массив обменов `queue`: каждый
// получает свой `localId`, обрабатываются строго по одному (drain), непринятые в очередь не
// теряются, а ждут своей очереди со статусом "queued" — видно в ленте как «В ожидании».

export const convKey = (vacancyId: string | null) => ["conversation", vacancyId] as const
export const conversationsListKey = ["conversations-list"] as const

const HISTORY_LIMIT = 12

export type PendingStatus = "queued" | "sending" | "done"

export interface PendingExchange {
  /** Локальный id обмена (не id сообщения в БД — тот появляется только после персиста). */
  localId: string
  question: string
  answer: string
  status: PendingStatus
  error?: boolean
  /** Момент отправки вопроса — пузырь пока не персистирован, но время уже показываем. */
  askedAt: number
  /**
   * Вложения этого вопроса (Э2-6) — уже загруженные `AttachmentOut` из композера, не только id:
   * оптимистичный пузырь рисует картинку сразу через `AttachmentGrid`, не дожидаясь рефетча ленты.
   */
  attachments?: AttachmentOut[]
}

export interface StreamSnapshot {
  /** По одной вакансии — обмены в порядке отправки (FIFO), а не единственный слот. */
  queue: PendingExchange[]
  isRunning: boolean
  lastFollowUps: string[]
}

const EMPTY_SNAPSHOT: StreamSnapshot = { queue: [], isRunning: false, lastFollowUps: [] }

/** Обмен уже в ленте — можно убирать его из очереди, не теряя ответ. */
export function exchangePersistedInMessages(
  messages: ConvMessage[],
  question: string,
  answer: string | null | undefined,
  attachmentIds: number[] = [],
): boolean {
  const q = question.trim()
  const hasUser = messages.some((m) => {
    if (m.kind !== "llm_user") return false
    if (q) return m.body.trim() === q
    // Картинка(и) без текста (Э2-5): текст всегда пуст, сверяем по набору id вложений вопроса.
    if (attachmentIds.length === 0) return false
    const ids = (m.attachments ?? []).map((a) => a.id).sort((x, y) => x - y)
    const wanted = [...attachmentIds].sort((x, y) => x - y)
    return ids.length === wanted.length && ids.every((id, i) => id === wanted[i])
  })
  if (!hasUser) return false
  const a = (answer ?? "").trim()
  if (!a) return true
  return messages.some((m) => m.kind === "llm_assistant" && m.body.trim() === a)
}

function buildHistory(messages: ConvMessage[]): { role: "user" | "assistant"; text: string }[] {
  return messages
    .filter((m) => m.kind === "llm_user" || m.kind === "llm_assistant")
    .filter((m) => m.body.trim())
    .slice(-HISTORY_LIMIT)
    .map(
      (m) => ({ role: m.kind === "llm_assistant" ? "assistant" : "user", text: m.body }) as const,
    )
}

function vacancyPayload(job: Job) {
  return {
    vacancy_id: job.vacancy_id,
    vacancy_text: job.vacancy_text,
    title: job.title,
    company: job.company,
    salary_text: job.salary_text,
    score: job.score,
  }
}

export interface AskParams {
  vacancyId: string
  job: Job
  qc: QueryClient
  text: string
  noteIds?: number[]
  replyToMessageId?: number
  /** Готовые вложения текущего вопроса из композера (Э2-6) — текст может быть пуст. */
  attachments?: AttachmentOut[]
}

type Listener = () => void

let nextLocalId = 0

class VacancyChatStreamStore {
  private snapshots = new Map<string, StreamSnapshot>()
  private listeners = new Map<string, Set<Listener>>()
  private askParams = new Map<string, AskParams>()
  private draining = new Set<string>()

  getSnapshot = (vacancyId: string): StreamSnapshot =>
    this.snapshots.get(vacancyId) ?? EMPTY_SNAPSHOT

  subscribe = (vacancyId: string, listener: Listener): (() => void) => {
    let set = this.listeners.get(vacancyId)
    if (!set) {
      set = new Set()
      this.listeners.set(vacancyId, set)
    }
    set.add(listener)
    return () => {
      set.delete(listener)
      if (set.size === 0) this.listeners.delete(vacancyId)
    }
  }

  /** Убрать конкретный обмен из очереди (по его localId) — не «весь pending разом». */
  clearPending(vacancyId: string, localId?: string) {
    const target = localId ?? this.getSnapshot(vacancyId).queue[0]?.localId
    if (!target) return
    this.askParams.delete(target)
    this.patch(vacancyId, (s) => ({ ...s, queue: s.queue.filter((e) => e.localId !== target) }))
  }

  clearFollowUps(vacancyId: string) {
    this.patch(vacancyId, (s) => (s.lastFollowUps.length ? { ...s, lastFollowUps: [] } : s))
  }

  private patch(vacancyId: string, updater: (prev: StreamSnapshot) => StreamSnapshot) {
    const prev = this.snapshots.get(vacancyId) ?? EMPTY_SNAPSHOT
    const next = updater(prev)
    if (next === prev) return
    this.snapshots.set(vacancyId, next)
    this.listeners.get(vacancyId)?.forEach((l) => l())
  }

  private patchExchange(
    vacancyId: string,
    localId: string,
    updater: (e: PendingExchange) => PendingExchange,
  ) {
    this.patch(vacancyId, (s) => ({
      ...s,
      queue: s.queue.map((e) => (e.localId === localId ? updater(e) : e)),
    }))
  }

  /** Поставить вопрос в очередь вакансии. Не блокирует, даже если агент занят предыдущим обменом —
   * вопрос сразу видно в ленте со статусом "queued" («В ожидании»), отправится, когда до него
   * дойдёт drain(). */
  ask(params: AskParams): void {
    const text = params.text.trim()
    const attachments = params.attachments ?? []
    const ids = attachments.map((a) => a.id)
    // Картинка(и) без текста — законный вопрос (Э2-5, §3 плана): блокируем только пустой запрос.
    if ((!text && ids.length === 0) || !params.vacancyId) return
    const localId = `q${++nextLocalId}`
    this.askParams.set(localId, params)
    this.patch(params.vacancyId, (s) => ({
      ...s,
      queue: [
        ...s.queue,
        {
          localId,
          question: text,
          answer: "",
          status: "queued",
          askedAt: Date.now(),
          attachments,
        },
      ],
    }))
    void this.drain(params.vacancyId)
  }

  /** Строго один обмен в моменте: следующий стартует только когда до него доходит очередь — не
   * когда предыдущий персистится (best-effort персист не блокирует ленту, см. runOne). */
  private async drain(vacancyId: string): Promise<void> {
    if (this.draining.has(vacancyId)) return
    this.draining.add(vacancyId)
    try {
      for (;;) {
        const next = this.getSnapshot(vacancyId).queue.find((e) => e.status === "queued")
        if (!next) break
        await this.runOne(vacancyId, next.localId)
      }
    } finally {
      this.draining.delete(vacancyId)
    }
  }

  private async runOne(vacancyId: string, localId: string): Promise<void> {
    const params = this.askParams.get(localId)
    if (!params) {
      this.clearPending(vacancyId, localId)
      return
    }
    const { job, qc, noteIds, replyToMessageId } = params
    const text = params.text.trim()
    const attachments = params.attachments ?? []
    const ids = attachments.map((a) => a.id)

    this.patchExchange(vacancyId, localId, (e) => ({ ...e, status: "sending" }))
    this.patch(vacancyId, (s) => ({ ...s, isRunning: true }))

    // История строится ЗАНОВО прямо перед отправкой (не в момент постановки в очередь) — так
    // второй-третий вопрос очереди видит ответ на предыдущий, если тот успел персиститься.
    const cachedBefore = qc.getQueryData<ConversationOut>(convKey(vacancyId))
    const history = buildHistory(cachedBefore?.messages ?? [])

    try {
      let final: string | null = null
      let followUps: string[] = []
      let streamFailed = false
      await streamChat(
        {
          message: text,
          history,
          vacancy: vacancyPayload(job),
          tier: "advanced",
          ...(noteIds && noteIds.length > 0 ? { note_ids: noteIds } : {}),
          ...(replyToMessageId != null ? { reply_to_message_id: replyToMessageId } : {}),
          ...(ids.length > 0 ? { attachment_ids: ids } : {}),
        },
        (e: SseEvent) => {
          // A-14: SSE event = part|progress|done|error; подтип в data.type.
          const kind = typeof e.data.type === "string" && e.data.type ? e.data.type : e.event
          switch (kind) {
            case "token": {
              const t = e.data.text as string | undefined
              if (t) {
                this.patchExchange(vacancyId, localId, (ex) => ({
                  ...ex,
                  answer: ex.answer + t,
                }))
              }
              break
            }
            case "result": {
              if (typeof e.data.answer === "string") final = e.data.answer
              const arr = e.data.follow_ups
              if (Array.isArray(arr)) {
                followUps = arr
                  .filter((v): v is string => typeof v === "string" && v.trim().length > 0)
                  .slice(0, 3)
              }
              break
            }
            case "error": {
              streamFailed = true
              const msg = (e.data.message as string) ?? "Ошибка чата"
              this.patchExchange(vacancyId, localId, (ex) => ({
                ...ex,
                error: true,
                answer: ex.answer || msg,
              }))
              break
            }
          }
        },
      )
      if (final && !streamFailed) {
        const finalAnswer: string = final
        this.patchExchange(vacancyId, localId, (ex) => ({
          ...ex,
          answer: finalAnswer,
          error: false,
        }))
      }
      this.patch(vacancyId, (s) => ({ ...s, lastFollowUps: followUps }))
      // Бэкенд обычно уже записал обмен — подтягиваем ленту. Обмен со статусом "done" гасим только
      // когда llm_user/llm_assistant реально в кэше; иначе оставляем в очереди (персист best-effort
      // / пустой рефетч раньше стирал весь ответ) — следующий рефетч (эффект в
      // use-vacancy-conversation) досмотрит и уберёт.
      await qc.invalidateQueries({ queryKey: convKey(vacancyId) })
      void qc.invalidateQueries({ queryKey: conversationsListKey })
      this.patchExchange(vacancyId, localId, (ex) => ({ ...ex, status: "done" }))
      if (streamFailed) return
      const cached = qc.getQueryData<ConversationOut>(convKey(vacancyId))
      if (exchangePersistedInMessages(cached?.messages ?? [], text, final, ids)) {
        this.clearPending(vacancyId, localId)
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Чат по вакансии недоступен"
      this.patchExchange(vacancyId, localId, (ex) => ({
        ...ex,
        status: "done",
        error: true,
        answer: ex.answer || msg,
      }))
      toast.error(msg)
    } finally {
      const stillSending = this.getSnapshot(vacancyId).queue.some((e) => e.status === "sending")
      if (!stillSending) this.patch(vacancyId, (s) => ({ ...s, isRunning: false }))
    }
  }
}

export const vacancyChatStreamStore = new VacancyChatStreamStore()
