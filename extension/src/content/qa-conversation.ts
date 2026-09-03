/** U-14: маппинг единого разговора вакансии ↔ Q&A панели расширения. */

export const QA_HISTORY_LIMIT = 12;

/** `ts` — миллисекунды эпохи, необязательное поле: для реплик из БД — `sent_at`/`created_at`
 *  с бэка, для только что отправленных в эту сессию (до перезагрузки истории) — `Date.now()`
 *  в месте создания (см. `onQaSend` в `main.ts`). Правка 2026-08-20: подпись времени под
 *  пузырём — мини-версия веб-чата вакансии (Bubble в VacancyDialog.tsx). */
export type QaMessage = { role: 'user' | 'assistant'; content: string; ts?: number };

type ConvMessageLike = {
  kind?: string | null;
  body?: string | null;
  sent_at?: string | null;
  created_at?: string | null;
};

/** LLM-реплики из `/api/conversations/{id}` → формат треда панели. */
export function convMessagesToQaHistory(messages: ConvMessageLike[] | null | undefined): QaMessage[] {
  const out: QaMessage[] = [];
  for (const msg of messages || []) {
    const body = String(msg.body || '').trim();
    if (!body) continue;
    const role = msg.kind === 'llm_user' ? 'user' : msg.kind === 'llm_assistant' ? 'assistant' : null;
    if (!role) continue;
    const tsRaw = msg.sent_at || msg.created_at;
    const parsed = tsRaw ? Date.parse(tsRaw) : NaN;
    // Ключ `ts` только когда реально распознан — так объект без времени остаётся `{role, content}`
    // (не `{role, content, ts: undefined}` — разные формы для deepEqual в существующих тестах).
    out.push(Number.isFinite(parsed) ? { role, content: body, ts: parsed } : { role, content: body });
  }
  return out;
}

/** История для POST `/vacancies/{id}/ask` — последние N обменов, как в веб-дровере. */
export function qaHistoryForAsk(history: QaMessage[]): QaMessage[] {
  return history.slice(-QA_HISTORY_LIMIT);
}
