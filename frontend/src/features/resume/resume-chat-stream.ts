import { toast } from "sonner"
import { ApiError } from "@/api/client"
import { streamChat } from "@/api/chat"
import type { SseEvent } from "@/api/sse"
import type { AttachmentOut } from "@/api/attachments"
import { type ResumeChatHistory } from "@/api/resume"
import { queryClient } from "@/lib/query"

// Стрим ответа агента чата по резюме живёт ЗДЕСЬ, а не в состоянии компонента (баг «ответ
// пропадает при переключении вкладки»): ResumeChat монтируется только на вкладке «Резюме», и
// уход с неё размонтировал компонент, а стрим продолжал качать токены в setMessages
// размонтированного компонента (React-warnings), либо, если стрим обрывался, ответ не был виден
// при возвращении, пока бэкенд не допишет его в БД и фронт не перетянет историю. Здесь стрим
// не привязан к жизненному циклу React-компонента — вкладка может уйти в фон и вернуться,
// ответ доедет и будет виден сразу (оптимистичный пузырь + финальный персист бэкенда).
//
// История чата по резюме одна на аккаунт (без vacancy-ключа), поэтому стор — одиночный слот
// (не Map по vacancyId, как vacancy-chat-stream). Поставленные в очередь обмены обрабатываются
// строго по одному (drain), второй вопрос не стирает первый.
//
// Паритет с чатом по рынку (2026-08-14, миграция 0120): reply_to_message_id + attachment_ids
// прокидываются в streamChat; ответ на конкретную реплику и вложения сохраняются на бэке.

export type ResumeChatMsg = { role: "user" | "assistant"; text: string; error?: boolean }

export const resumeChatHistoryKey = ["resume-chat-history"] as const

export type ResumePendingStatus = "queued" | "sending" | "done"

export interface ResumePendingExchange {
  /** Локальный id обмена (не id сообщения в БД — тот появляется только после персиста). */
  localId: string
  question: string
  answer: string
  status: ResumePendingStatus
  error?: boolean
  /** Момент отправки вопроса — пузырь пока не персистирован, но время уже показываем. */
  askedAt: number
  /** id реплики-источника цитаты (Ответить) — прокидывается в бэкенд как reply_to_message_id. */
  replyToMessageId?: number
  /** Вложения текущей реплики (картинки/документы) — показываются в пузыре и линкуются на бэке. */
  attachments?: AttachmentOut[]
}

export interface ResumeChatStreamSnapshot {
  /** Обмены в порядке отправки (FIFO), а не единственный слот. */
  queue: ResumePendingExchange[]
  isRunning: boolean
}

const EMPTY_SNAPSHOT: ResumeChatStreamSnapshot = { queue: [], isRunning: false }

function buildHistory(messages: ResumeChatMsg[]): { role: "user" | "assistant"; text: string }[] {
  return messages
    .filter((m) => m.text.trim())
    .slice(-12)
    .map((m) => ({ role: m.role, text: m.text }))
}

type Listener = () => void

let nextLocalId = 0

class ResumeChatStreamStore {
  private snapshot: ResumeChatStreamSnapshot = EMPTY_SNAPSHOT
  private listeners = new Set<Listener>()
  /** Параметры отправки по localId — история строится перед самым стримом, не в момент очереди. */
  private askParams = new Map<
    string,
    { question: string; replyToMessageId?: number; attachments?: AttachmentOut[] }
  >()
  private draining = false

  getSnapshot = (): ResumeChatStreamSnapshot => this.snapshot

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  /** Убрать конкретный обмен из очереди (по его localId) — не «весь pending разом». */
  clearPending(localId?: string) {
    const target = localId ?? this.snapshot.queue[0]?.localId
    if (!target) return
    this.askParams.delete(target)
    this.patch((s) => ({ ...s, queue: s.queue.filter((e) => e.localId !== target) }))
  }

  /** Сбросить очередь (например, перед перезагрузкой истории после «Очистить»). */
  reset() {
    this.askParams.clear()
    this.patch(() => ({ queue: [], isRunning: false }))
  }

  private patch(updater: (prev: ResumeChatStreamSnapshot) => ResumeChatStreamSnapshot) {
    const prev = this.snapshot
    const next = updater(prev)
    if (next === prev) return
    this.snapshot = next
    this.listeners.forEach((l) => l())
  }

  private patchExchange(
    localId: string,
    updater: (e: ResumePendingExchange) => ResumePendingExchange,
  ) {
    this.patch((s) => ({
      ...s,
      queue: s.queue.map((e) => (e.localId === localId ? updater(e) : e)),
    }))
  }

  /** Поставить вопрос в очередь. Не блокирует, даже если агент занят предыдущим обменом —
   * вопрос сразу видно в ленте со статусом "queued" («В ожидании»), отправится, когда до него
   * дойдёт drain(). replyToMessageId/attachments — паритет с чатом по рынку. */
  ask(
    question: string,
    replyToMessageId?: number,
    attachments?: AttachmentOut[],
  ): void {
    const text = question.trim()
    if (!text) return
    const localId = `r${++nextLocalId}`
    this.askParams.set(localId, { question: text, replyToMessageId, attachments })
    this.patch((s) => ({
      ...s,
      queue: [
        ...s.queue,
        {
          localId,
          question: text,
          answer: "",
          status: "queued",
          askedAt: Date.now(),
          replyToMessageId,
          attachments,
        },
      ],
    }))
    void this.drain()
  }

  /** Строго один обмен в моменте: следующий стартует только когда до него доходит очередь. */
  private async drain(): Promise<void> {
    if (this.draining) return
    this.draining = true
    try {
      for (;;) {
        const next = this.snapshot.queue.find((e) => e.status === "queued")
        if (!next) break
        await this.runOne(next.localId)
      }
    } finally {
      this.draining = false
    }
  }

  private async runOne(localId: string): Promise<void> {
    const params = this.askParams.get(localId)
    if (!params) {
      this.clearPending(localId)
      return
    }
    const question = params.question
    const replyToMessageId = params.replyToMessageId
    const attachmentIds = (params.attachments ?? []).map((a) => a.id)

    this.patchExchange(localId, (e) => ({ ...e, status: "sending" }))
    this.patch((s) => ({ ...s, isRunning: true }))

    // История строится ЗАНОВО перед отправкой из актуального кэша resume-chat-history —
    // так второй вопрос очереди видит ответ на первый, если тот успел персиститься.
    const cached = queryClient.getQueryData<ResumeChatHistory>(resumeChatHistoryKey)
    const history = buildHistory(
      (cached?.items ?? []).map((m) => ({ role: m.role, text: m.content })),
    )

    try {
      let final: string | null = null
      let streamFailed = false
      let streamError: string | null = null
      await streamChat(
        {
          message: question,
          history,
          resume_gap: true,
          reply_to_message_id: replyToMessageId,
          attachment_ids: attachmentIds,
        },
        (e: SseEvent) => {
          const kind = typeof e.data.type === "string" && e.data.type ? e.data.type : e.event
          if (kind === "token" || kind === "part") {
            const piece = (typeof e.data.text === "string" ? e.data.text : e.data.content) ?? ""
            this.patchExchange(localId, (ex) => ({ ...ex, answer: ex.answer + piece }))
            return
          }
          if (kind === "result") {
            // Финальный ответ бэкенд шлёт в data.answer (для resume_gap follow_ups пуст).
            const answer = typeof e.data.answer === "string" ? e.data.answer : null
            if (answer) {
              final = answer
              this.patchExchange(localId, (ex) => ({ ...ex, answer, error: false }))
            }
            return
          }
          if (kind === "error") {
            streamFailed = true
            streamError =
              (typeof e.data.detail === "string" && e.data.detail) ||
              (typeof e.data.message === "string" && e.data.message) ||
              "Ошибка"
            this.patchExchange(localId, (ex) => ({
              ...ex,
              error: true,
              answer: ex.answer || streamError!,
            }))
          }
        },
      )
      if (final && !streamFailed) {
        const finalAnswer: string = final
        this.patchExchange(localId, (ex) => ({ ...ex, answer: finalAnswer, error: false }))
      }
      this.patchExchange(localId, (ex) => ({ ...ex, status: "done" }))
      // Бэкенд персистит обмен в resume_chat_messages по завершении стрима. Инвалидируем кэш
      // истории — useQuery перетянет свежую ленту. Обмен со статусом "done" НЕ удаляем из очереди
      // здесь — эффект в useResumeConversation досмотрит, когда реплики реально появятся в
      // сохранённой истории, и только тогда уберёт обмен. Зеркало use-vacancy-conversation.
      await queryClient.invalidateQueries({ queryKey: resumeChatHistoryKey })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Чат по резюме недоступен"
      this.patchExchange(localId, (ex) => ({
        ...ex,
        status: "done",
        error: true,
        answer: ex.answer || msg,
      }))
      toast.error(msg)
    } finally {
      const stillSending = this.snapshot.queue.some((e) => e.status === "sending")
      if (!stillSending) this.patch((s) => ({ ...s, isRunning: false }))
    }
  }
}

export const resumeChatStreamStore = new ResumeChatStreamStore()
