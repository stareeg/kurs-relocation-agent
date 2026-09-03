/**
 * S13: общий пайплайн синка «Ваши отклики» career.habr.com → Postgres (через negotiations API).
 * Аналог getmatch-applications-sync.ts, но данные приходят не из DOM, а из перехваченного XHR
 * `/api/frontend/responses` (адаптер habr-applications.ts держит перехватчик и зовёт сюда).
 */

import {
  habrStatusDisplayLabel,
  parseHabrResponsesFromJson,
  type ParsedHabrApplication,
} from '../dom/selectors-habr-applications'
import { fetchNegotiationsPreview, applySync } from './negotiations-sync'

function isAutoSyncCandidate(item: ParsedHabrApplication): boolean {
  if (!item.is_discrepancy || item.sync_state === 'synced') return false
  if (item.is_stale) return true
  if (item.skip_stage_update && item.funnel_status_preview !== 'Отказ') return false
  return true
}

function applicationsPayloadItem(item: ParsedHabrApplication) {
  return {
    vacancy_id: item.vacancy_id,
    hh_status_raw: item.hh_status_raw || item.habr_status_raw || '',
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

function parseApplicationsFromJson(payload: unknown): ParsedHabrApplication[] {
  const items = parseHabrResponsesFromJson(payload)
  for (const item of items) {
    item.sync_state = 'pending'
    item.is_discrepancy = false
  }
  return items
}

function countHabrStatuses(items: ParsedHabrApplication[]): {
  invitation: number
  viewed: number
  rejected: number
  archived: number
} {
  let invitation = 0
  let viewed = 0
  let rejected = 0
  let archived = 0
  for (const item of items) {
    if (item.is_stale || item.is_archived) archived += 1
    else if (item.habr_status === 'invitation') invitation += 1
    else if (item.habr_status === 'rejected') rejected += 1
    else if (item.habr_status === 'viewed') viewed += 1
  }
  return { invitation, viewed, rejected, archived }
}

async function fetchApplicationsPreview(
  items: ParsedHabrApplication[],
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
  parseApplicationsFromJson,
  fetchApplicationsPreview,
  applySync,
  countHabrStatuses,
  habrStatusDisplayLabel,
}
