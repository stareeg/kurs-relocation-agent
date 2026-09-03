import { parseNegotiationCardsFromDom, mapHhStatusToFunnel } from '../dom/selectors'

/**
 * EX-8: общий пайплайн «распарсить → preview → решить авто/ожидание → применить», вынесенный из
 * `negotiations.ts`, чтобы им пользовались и видимая панель списка (клик «Синхронизировать»/по
 * строке), и тихий `negotiations-heartbeat.ts` (фон, без открытой страницы `/applicant/negotiations`).
 * Ничего не рендерит и не хранит состояние панели — только чистые функции над списком items.
 */

/** Любое расхождение переносим АВТОМАТОМ без клика (Решение 9) — пользователь не должен вручную
 * подтверждать каждую карточку. Раньше здесь был allowlist из 2 статусов (отказ/скрининг) — узкий
 * фильтр и был причиной «надо нажимать самому»: остальные расхождения молча ждали клика. Теперь
 * страховка одна — на бэке: гард `should_apply_funnel_update` (force=false) не даёт даунранкнуть
 * активную воронку/оффер, а спорные случаи решает LLM (`use_llm: true` в applySync ниже), а не
 * клиентский allowlist. */
function isAutoSyncCandidate(item) {
  return item.is_discrepancy && item.sync_state !== 'synced';
}

function negotiationsPayloadItem(item) {
  return {
    vacancy_id: item.vacancy_id,
    hh_status_raw: item.hh_status_raw || item.hh_status || '',
    hh_status: item.hh_status,
    company: item.company || '',
    title: item.title || '',
    url: item.url || `https://hh.ru/vacancy/${item.vacancy_id}`,
    applied_at: item.applied_at || null,
    last_message: item.last_message || null,
    employer_viewed: item.employer_viewed ?? null,
    negotiation_id: item.negotiation_id || null,
    employer_state_id: item.employer_state_id || null,
  };
}

/** Карточки из произвольного документа (живой `document` ИЛИ распарсенный fetch+DOMParser) →
 *  items с предварительным (клиентским, без бэкенда) `funnel_status_preview`. */
function parseNegotiationsFromRoot(root) {
  const items = parseNegotiationCardsFromDom(root);
  for (const item of items) {
    const mapped = mapHhStatusToFunnel(
      item.hh_status,
      Boolean(item.last_message && item.last_message.length > 3)
    );
    item.funnel_status_preview = mapped.funnel_status;
    item.needs_interview_tracking = mapped.needs_interview_tracking;
    item.sync_state = 'pending';
    item.is_discrepancy = false;
  }
  return items;
}

/** Дотягивает текущий (Postgres) статус + признак расхождения с бэка. Мутирует items на месте
 *  (как и раньше делал `enrichItemsWithBackendStatus` в negotiations.ts) — так оба потребителя
 *  (панель списка, heartbeat) получают один и тот же контракт без лишнего копирования массива. */
async function fetchNegotiationsPreview(items, sendMessage) {
  if (!items.length) return { error: null };

  const response = await sendMessage({
    action: 'negotiations_preview',
    payload: { items: items.map(negotiationsPayloadItem) },
  });

  if (!response?.ok || !response.data?.items) {
    const error =
      response?.error || 'Не удалось загрузить статусы Copilot — проверьте backend (localhost:8000)';
    for (const item of items) {
      item.sync_state = 'pending';
      item.is_discrepancy = item.is_discrepancy ?? true;
    }
    return { error };
  }

  const byId = Object.fromEntries(response.data.items.map((p) => [String(p.vacancy_id), p]));
  for (const item of items) {
    const p = byId[String(item.vacancy_id)];
    if (p) {
      item.current_status = p.current_status || null;
      item.funnel_status_preview = p.funnel_status_proposed || item.funnel_status_preview;
      item.is_discrepancy = p.is_discrepancy;
      item.needs_vacancy_text = Boolean(p.needs_vacancy_text);
    }
    item.sync_state = item.is_discrepancy ? 'pending' : 'synced';
  }
  return { error: null };
}

/** Применить статусы (Postgres + Sheets), без стрима — для heartbeat и dry-run панели списка.
 *  Живая панель для реального клика «Синхронизировать» использует стрим-порт напрямую (прогресс-бар,
 *  UI-специфика, вне этого модуля). */
async function applySync(items, options, sendMessage) {
  const { force = false, dryRun = false } = options || {};
  if (!items.length) return { results: [], synced_count: 0, skipped_count: 0 };
  const response = await sendMessage({
    action: 'sync_negotiations',
    payload: {
      items: items.map(negotiationsPayloadItem),
      dry_run: dryRun,
      use_llm: true,
      force,
    },
  });
  if (!response?.ok) throw new Error(response?.error || 'Ошибка синхронизации');
  return response.data;
}

export {
  isAutoSyncCandidate,
  negotiationsPayloadItem,
  parseNegotiationsFromRoot,
  fetchNegotiationsPreview,
  applySync,
}
