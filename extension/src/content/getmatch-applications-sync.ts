/**
 * GM-5.1: общий пайплайн синка getmatch /applications → Postgres (через negotiations API).
 */

import {
  parseGetmatchApplicationCardsFromDom,
  parseGetmatchApplicationsFromJson,
  gmStatusDisplayLabel,
  type ParsedGetmatchApplication,
} from '../dom/selectors-getmatch-applications'
import { fetchNegotiationsPreview, applySync } from './negotiations-sync'

/** Любое расхождение переносим АВТОМАТОМ без клика (как «Решение 9» на hh) — защита от
 *  даунранка активной воронки/оффера живёт на бэке (`should_apply_funnel_update` при force=false),
 *  а не в узком клиентском allowlist. Раньше здесь был фильтр `!is_stale` + `skip_stage_update` —
 *  тот самый узкий фильтр, что на hh убрали как источник «надо нажимать самому»: часть расхождений
 *  getmatch молча ждала ручного клика вместо авто-переноса. */
function isAutoSyncCandidate(item: ParsedGetmatchApplication): boolean {
  return Boolean(item.is_discrepancy) && item.sync_state !== 'synced'
}

function applicationsPayloadItem(item: ParsedGetmatchApplication) {
  return {
    vacancy_id: item.vacancy_id,
    hh_status_raw: item.hh_status_raw || item.gm_status_raw || '',
    hh_status: item.hh_status,
    company: item.company || '',
    title: item.title || '',
    url: item.url || '',
    applied_at: item.applied_at || null,
    last_message: null,
    employer_viewed: item.employer_viewed ?? null,
    negotiation_id: null,
    employer_state_id: null,
  }
}

function parseApplicationsFromRoot(root: Document | Element): ParsedGetmatchApplication[] {
  const items = parseGetmatchApplicationCardsFromDom(root)
  for (const item of items) {
    item.sync_state = 'pending'
    item.is_discrepancy = false
  }
  return items
}

/** Список откликов из JSON-ответа `/api/applications/candidate` (для фонового heartbeat) —
 *  тот же контракт items, что и из DOM. */
function parseApplicationsFromJson(payload: unknown): ParsedGetmatchApplication[] {
  const items = parseGetmatchApplicationsFromJson(payload)
  for (const item of items) {
    item.sync_state = 'pending'
    item.is_discrepancy = false
  }
  return items
}

function countGmStatuses(items: ParsedGetmatchApplication[]): {
  approved: number
  waiting: number
  rejected: number
} {
  let approved = 0
  let waiting = 0
  let rejected = 0
  for (const item of items) {
    if (item.gm_status === 'approved') approved += 1
    else if (item.gm_status === 'waiting') waiting += 1
    else if (item.gm_status === 'rejected') rejected += 1
  }
  return { approved, waiting, rejected }
}

async function fetchApplicationsPreview(
  items: ParsedGetmatchApplication[],
  sendMessage: (msg: unknown) => Promise<unknown>,
) {
  if (!items.length) return { error: null as string | null }

  const response = (await sendMessage({
    action: 'negotiations_preview',
    payload: { items: items.map(applicationsPayloadItem) },
  })) as { ok?: boolean; data?: { items?: Array<Record<string, unknown>> }; error?: string }

  if (!response?.ok || !response.data?.items) {
    const error =
      response?.error ||
      'Не удалось загрузить статусы Copilot — проверьте backend (localhost:8000)'
    for (const item of items) {
      item.sync_state = 'pending'
      item.is_discrepancy = item.is_discrepancy ?? true
    }
    return { error }
  }

  const byId = Object.fromEntries(
    response.data.items.map((p) => [String(p.vacancy_id), p]),
  )
  for (const item of items) {
    const p = byId[String(item.vacancy_id)]
    if (p) {
      item.current_status = (p.current_status as string) || null
      item.funnel_status_preview =
        (p.funnel_status_proposed as string) || item.funnel_status_preview
      item.is_discrepancy = Boolean(p.is_discrepancy)
      item.needs_vacancy_text = Boolean(p.needs_vacancy_text)
    }
    item.sync_state = item.is_discrepancy ? 'pending' : 'synced'
  }
  return { error: null }
}

export {
  isAutoSyncCandidate,
  applicationsPayloadItem,
  parseApplicationsFromRoot,
  parseApplicationsFromJson,
  fetchApplicationsPreview,
  applySync,
  countGmStatuses,
  gmStatusDisplayLabel,
}

