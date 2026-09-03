/**
 * S13: синк откликов career.habr.com/profile/responses → Postgres (+ Sheets).
 * Аналог getmatch-applications.ts, но источник данных — не DOM, а перехваченный JSON
 * `/api/frontend/responses` (см. habr-xhr-interceptor.ts в MAIN world). Изолированный мир читает
 * буфер <script id="__jh_habr_responses__"> и слушает window.postMessage для live-обновлений.
 */

import {
  habrResponsesFingerprint,
  habrResponsesPageKey,
} from '../dom/selectors-habr-applications'

import { HABR_PAGE_TYPE, getPageType, getSite, type SiteRoute } from '../dom/site-router'

import { iconMarkup } from '../ui/icons'

import {
  isAutoSyncCandidate,
  applicationsPayloadItem,
  parseApplicationsFromJson,
  fetchApplicationsPreview,
  applySync,
  countHabrStatuses,
  habrStatusDisplayLabel,
} from './habr-applications-sync'

import { ensureWebConfig, openExternal, webJobUrl } from './web-links'

const BUFFER_ID = '__jh_habr_responses__'

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id)
  } catch {
    return false
  }
}

let habrShadowRoot: ShadowRoot | null = null
let habrPanelEl: HTMLElement | null = null
let habrSyncAllBtn: HTMLButtonElement | null = null
let habrExpandBtn: HTMLButtonElement | null = null
let habrParsedItems: ReturnType<typeof parseApplicationsFromJson> = []
let habrSyncing = false
let habrPreviewLoading = false
let habrCollapsed = false
let habrLastPageKey = habrResponsesPageKey(location.href)
let habrDomRefreshTimer: ReturnType<typeof setTimeout> | null = null
let habrLastPreviewKey = ''
let habrPreviewError = ''
let habrAutoSyncedKey = ''
let habrStatusMessage = ''
let habrLastSyncAt: Date | null = null
let habrLastFingerprint = ''
let habrRefreshInFlight = false
let habrLastPayload: unknown = null
const HABR_DOM_REFRESH_MS = 4000

function habrEscapeHtml(text: string) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function habrSendMessage(message: unknown): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено — обновите страницу Хабр Карьеры (F5)' })
      return
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        try {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message })
            return
          }
          resolve(response)
        } catch (err) {
          resolve({ ok: false, error: String((err as Error).message || err) })
        }
      })
    } catch (err) {
      resolve({ ok: false, error: String((err as Error).message || err) })
    }
  })
}

function sortApplicationItems(items: typeof habrParsedItems) {
  return [...items].sort((a, b) => {
    const aSynced = a.sync_state === 'synced' ? 1 : 0
    const bSynced = b.sync_state === 'synced' ? 1 : 0
    if (aSynced !== bSynced) return aSynced - bSynced
    const aDisc = a.is_discrepancy ? 0 : 1
    const bDisc = b.is_discrepancy ? 0 : 1
    if (aDisc !== bDisc) return aDisc - bDisc
    return String(a.company || a.title).localeCompare(String(b.company || b.title), 'ru')
  })
}

function pendingItems() {
  return habrParsedItems.filter((x) => x.is_discrepancy && x.sync_state !== 'synced')
}

function syncedCount() {
  return habrParsedItems.filter((x) => x.sync_state === 'synced').length
}

async function maybeAutoSyncApplications() {
  if (habrSyncing || habrPreviewLoading || habrPreviewError) return
  const key = habrResponsesPageKey()
  if (habrAutoSyncedKey === key) return
  const candidates = habrParsedItems.filter(isAutoSyncCandidate)
  habrAutoSyncedKey = key
  if (!candidates.length) return
  await syncApplicationItems(candidates, { force: false, auto: true })
}

function ensureApplicationsUi(slots: {
  shadowRoot: ShadowRoot
  panelEl: HTMLElement
  toolbarEl: HTMLElement
}) {
  habrShadowRoot = slots.shadowRoot
  habrPanelEl = slots.panelEl
  habrPanelEl.classList.add('jh-neg-panel', 'jh-gm-apps-panel', 'jh-habr-apps-panel')
  habrPanelEl.classList.remove('hidden')
  habrCollapsed = false

  slots.toolbarEl.classList.add('jh-neg-toolbar', 'jh-gm-apps-toolbar')
  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-habr-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
    <button type="button" class="jh-btn" id="jh-habr-sync-all-btn">${iconMarkup('refresh-cw', { size: 14 })}<span>Обновить</span></button>
  `

  habrSyncAllBtn = habrShadowRoot.getElementById('jh-habr-sync-all-btn') as HTMLButtonElement
  habrSyncAllBtn.addEventListener('click', onSyncAllDiscrepanciesClick)
  habrExpandBtn = habrShadowRoot.getElementById('jh-habr-expand-btn') as HTMLButtonElement
  habrExpandBtn.addEventListener('click', onExpandClick)
}

function teardownApplicationsUi() {
  stopInterceptor()
  if (habrDomRefreshTimer) clearTimeout(habrDomRefreshTimer)
  habrDomRefreshTimer = null
  habrShadowRoot = null
  habrPanelEl = null
  habrSyncAllBtn = null
  habrExpandBtn = null
  habrParsedItems = []
  habrLastPreviewKey = ''
  habrPreviewError = ''
  habrAutoSyncedKey = ''
  habrStatusMessage = ''
  habrLastSyncAt = null
  habrLastFingerprint = ''
  habrRefreshInFlight = false
  habrLastPayload = null
  habrCollapsed = false
  habrSyncing = false
  habrPreviewLoading = false
}

function onCollapseClick() {
  habrCollapsed = true
  habrPanelEl?.classList.add('hidden')
  habrExpandBtn?.classList.remove('hidden')
}

function onExpandClick() {
  habrCollapsed = false
  habrPanelEl?.classList.remove('hidden')
  habrExpandBtn?.classList.add('hidden')
}

function collapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="habr-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`
}

function formatSyncTime(d: Date | null) {
  if (!d) return ''
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function habrSyncAllBtnHtml(label: string) {
  return `${iconMarkup('refresh-cw', { size: 14 })}<span>${label}</span>`
}

function updateSyncToolbar() {
  if (!habrSyncAllBtn) return

  const pending = pendingItems().length
  const total = habrParsedItems.length
  const synced = syncedCount()

  if (habrSyncing) {
    habrSyncAllBtn.disabled = true
    habrSyncAllBtn.classList.add('jh-btn-loading')
    habrSyncAllBtn.innerHTML = habrSyncAllBtnHtml(
      pending > 0 ? `Синхронизация… (${pending})` : 'Синхронизация…',
    )
    return
  }

  if (habrPreviewLoading) {
    habrSyncAllBtn.disabled = true
    habrSyncAllBtn.classList.add('jh-btn-loading')
    habrSyncAllBtn.innerHTML = habrSyncAllBtnHtml('Загрузка…')
    return
  }

  habrSyncAllBtn.classList.remove('jh-btn-loading')
  habrSyncAllBtn.disabled = !total || Boolean(habrPreviewError)

  if (pending > 0) {
    habrSyncAllBtn.innerHTML = habrSyncAllBtnHtml(`Обновить (${pending})`)
  } else if (total > 0) {
    habrSyncAllBtn.innerHTML = habrSyncAllBtnHtml('Обновить статусы')
  } else {
    habrSyncAllBtn.innerHTML = habrSyncAllBtnHtml('Обновить')
  }

  habrSyncAllBtn.title =
    total > 0
      ? `${synced}/${total} синхронизировано${habrLastSyncAt ? ` · ${formatSyncTime(habrLastSyncAt)}` : ''}`
      : ''
}

function headerHtml() {
  const total = habrParsedItems.length
  const synced = syncedCount()
  const counts = countHabrStatuses(habrParsedItems)
  const plural = total === 1 ? 'отклик' : total >= 2 && total <= 4 ? 'отклика' : 'откликов'

  const statusDots = [
    counts.invitation
      ? `<span class="jh-gm-dotstat" title="${counts.invitation} приглашение"><span class="jh-gm-dot jh-gm-dot-approved"></span>${counts.invitation}</span>`
      : '',
    counts.viewed
      ? `<span class="jh-gm-dotstat" title="${counts.viewed} просмотр"><span class="jh-gm-dot jh-gm-dot-waiting"></span>${counts.viewed}</span>`
      : '',
    counts.rejected
      ? `<span class="jh-gm-dotstat" title="${counts.rejected} отказ"><span class="jh-gm-dot jh-gm-dot-rejected"></span>${counts.rejected}</span>`
      : '',
    counts.archived
      ? `<span class="jh-gm-dotstat" title="${counts.archived} архив"><span class="jh-gm-dot jh-gm-dot-unknown"></span>${counts.archived}</span>`
      : '',
  ].filter(Boolean)

  const syncHint =
    habrSyncing || habrPreviewLoading
      ? habrSyncing
        ? 'Синхронизация с Copilot…'
        : 'Загрузка статусов…'
      : habrLastSyncAt
        ? `Обновлено ${formatSyncTime(habrLastSyncAt)}`
        : ''

  return `
    <div class="jh-header jh-gm-apps-header">
      <div class="jh-header-main jh-gm-apps-header-main">
        <div class="jh-gm-summary">
          ${iconMarkup('clipboard-list', { size: 14, className: 'jh-gm-summary-icon' })}
          <span class="jh-gm-summary-text"><strong>${total}</strong> ${plural} · ${synced}/${total} в Copilot</span>
          ${statusDots.length ? `<span class="jh-gm-dots">${statusDots.join('')}</span>` : ''}
        </div>
        ${syncHint ? `<div class="jh-gm-sync-hint">${habrEscapeHtml(syncHint)}</div>` : ''}
      </div>
      ${collapseBtnHtml()}
    </div>`
}

function statusDotClass(status: string) {
  if (status === 'rejected') return 'jh-gm-dot-rejected'
  if (status === 'invitation') return 'jh-gm-dot-approved'
  if (status === 'viewed') return 'jh-gm-dot-waiting'
  if (status === 'archived') return 'jh-gm-dot-unknown'
  if (status === 'new') return 'jh-gm-dot-unknown'
  return 'jh-gm-dot-unknown'
}

function cardHtml(item: (typeof habrParsedItems)[number]) {
  const habrLabel = habrEscapeHtml(habrStatusDisplayLabel(item.habr_status))
  const jhCurrent = habrEscapeHtml(item.current_status || '—')
  const jhProposed = habrEscapeHtml(item.funnel_status_preview || '—')
  const cardCls = [
    item.sync_state === 'synced' ? 'jh-neg-card-synced' : '',
    item.is_discrepancy ? 'jh-neg-card-disc' : '',
    item.is_stale ? 'jh-gm-card-stale' : '',
    item.is_archived ? 'jh-gm-card-archived' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const funnelRow =
    item.is_discrepancy && item.sync_state !== 'synced'
      ? `<div class="jh-gm-funnel-row">
          ${iconMarkup('sparkles', { size: 12, className: 'jh-gm-funnel-icon' })}
          <span class="jh-neg-jh-cur">${jhCurrent}</span>
          ${iconMarkup('arrow-right', { size: 13, className: 'jh-neg-arrow' })}
          <span class="jh-neg-jh">${jhProposed}</span>
        </div>`
      : `<div class="jh-gm-funnel-row">
          ${iconMarkup('sparkles', { size: 12, className: 'jh-gm-funnel-icon' })}
          <span class="jh-neg-jh">${jhCurrent}</span>
          ${item.sync_state === 'synced' ? `<span class="jh-gm-inline-ok">${iconMarkup('circle-check', { size: 12 })}</span>` : ''}
        </div>`

  const badges = [
    item.is_archived && !item.is_stale
      ? `<span class="jh-gm-badge jh-gm-badge-archived" title="В архиве">${iconMarkup('archive', { size: 12 })}</span>`
      : '',
    item.is_stale
      ? `<span class="jh-gm-badge jh-gm-badge-stale" title="Старше 90 дней — уходит в архив">${iconMarkup('archive', { size: 12 })}</span>`
      : '',
    item.needs_vacancy_text
      ? `<span class="jh-gm-badge jh-gm-badge-needs-text" title="Нет текста вакансии — откройте страницу на Хабр. Без скора карточка удалится через 6 ч.">${iconMarkup('triangle-alert', { size: 12 })}</span>`
      : '',
    item.is_discrepancy && item.sync_state !== 'synced'
      ? `<span class="jh-gm-badge jh-gm-badge-disc" title="Расхождение с Copilot">${iconMarkup('circle-x', { size: 12 })}</span>`
      : '',
  ]
    .filter(Boolean)
    .join('')

  return `
    <article class="jh-gm-app-card ${cardCls}" data-vacancy-id="${habrEscapeHtml(item.vacancy_id)}">
      <div class="jh-gm-app-card-head">
        <span class="jh-gm-status-dot ${statusDotClass(item.habr_status)}" title="${habrLabel}"></span>
        <div class="jh-gm-app-card-titles">
          <span class="jh-gm-app-company">${habrEscapeHtml(item.company || '—')}</span>
          <span class="jh-gm-app-title" title="${habrEscapeHtml(item.title || '')}">${habrEscapeHtml(item.title || '—')}</span>
        </div>
        <div class="jh-gm-card-head-actions">
          <button type="button" class="jh-gm-icon-btn" data-action="open-web" data-vacancy-id="${habrEscapeHtml(item.vacancy_id)}" title="Открыть в вебе">${iconMarkup('external-link', { size: 13 })}</button>
          <button type="button" class="jh-gm-icon-btn" data-action="open-habr" data-url="${habrEscapeHtml(item.url || '')}" title="Открыть на Хабр">${iconMarkup('globe', { size: 13 })}</button>
        </div>
      </div>
      ${funnelRow}
      ${badges ? `<div class="jh-gm-badges">${badges}</div>` : ''}
    </article>`
}

function renderSyncProgress(event: Record<string, unknown>) {
  if (!event || !habrPanelEl || !habrShadowRoot) return
  let wrap = habrShadowRoot.getElementById('jh-habr-progress-wrap')
  if (!wrap) {
    wrap = document.createElement('div')
    wrap.id = 'jh-habr-progress-wrap'
    wrap.className = 'jh-neg-progress-wrap'
    const body = habrPanelEl.querySelector('.jh-body')
    body?.prepend(wrap)
  }
  const done = Number(event.done ?? 0)
  const total = Number(event.total ?? 1) || 1
  const pct = Math.min(100, Math.round((done / total) * 100))
  wrap.innerHTML = `
    <div class="jh-neg-progress-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
      <div class="jh-neg-progress-fill" style="width:${pct}%"></div>
    </div>
    <div class="jh-neg-progress-label">${habrEscapeHtml(String(event.message || `${done} / ${total}`))}</div>
  `
}

function clearSyncProgress() {
  habrShadowRoot?.getElementById('jh-habr-progress-wrap')?.remove()
}

function bindPanelActions() {
  habrPanelEl?.querySelector('[data-action="habr-collapse"]')?.addEventListener('click', onCollapseClick)

  habrPanelEl?.querySelectorAll('[data-action="open-web"]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const vid = btn.getAttribute('data-vacancy-id')
      if (!vid) return
      const cfg = await ensureWebConfig()
      openExternal(webJobUrl(vid, cfg.webBaseUrl))
    })
  })

  habrPanelEl?.querySelectorAll('[data-action="open-habr"]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const url = btn.getAttribute('data-url')
      if (url) openExternal(url)
    })
  })
}

function renderApplicationsPanel(message = '') {
  if (!habrPanelEl) return
  if (message) habrStatusMessage = message

  const sorted = sortApplicationItems(habrParsedItems)

  if (!sorted.length) {
    habrPanelEl.innerHTML = `
      ${headerHtml()}
      <div class="jh-body">
        <p class="jh-funnel-hint">Список откликов не загружен. Дождитесь загрузки страницы «Ваши отклики» или обновите её (F5).</p>
        ${habrPreviewError ? `<div class="jh-error">${habrEscapeHtml(habrPreviewError)}</div>` : ''}
        ${habrStatusMessage ? `<div class="jh-neg-msg">${habrEscapeHtml(habrStatusMessage)}</div>` : ''}
      </div>
    `
    bindPanelActions()
    updateSyncToolbar()
    habrPanelEl.classList.toggle('hidden', habrCollapsed)
    return
  }

  habrPanelEl.innerHTML = `
    ${headerHtml()}
    <div class="jh-body">
      ${habrPreviewError ? `<div class="jh-error">${habrEscapeHtml(habrPreviewError)}</div>` : ''}
      ${habrStatusMessage ? `<div class="jh-neg-msg">${habrEscapeHtml(habrStatusMessage)}</div>` : ''}
      <div class="jh-neg-cards jh-gm-app-cards">${sorted.map(cardHtml).join('')}</div>
    </div>
  `

  bindPanelActions()
  updateSyncToolbar()
  habrPanelEl.classList.toggle('hidden', habrCollapsed)
}

function applySyncResultsToItems(results: Array<Record<string, unknown>>) {
  if (!results?.length) return

  const byId = Object.fromEntries(results.map((r) => [String(r.vacancy_id), r]))
  for (const item of habrParsedItems) {
    const r = byId[String(item.vacancy_id)]
    if (!r) continue

    if (r.applied && !r.skipped) {
      item.sync_state = 'synced'
      item.current_status = r.funnel_status as string
      item.is_discrepancy = false
    } else if (r.current_status) {
      item.current_status = r.current_status as string
      item.is_discrepancy = (r.is_discrepancy as boolean) ?? item.is_discrepancy
      if (!r.skipped && r.applied) item.sync_state = 'synced'
    }
  }

  habrParsedItems = sortApplicationItems(habrParsedItems)
  habrLastPreviewKey = ''
  habrLastSyncAt = new Date()
}

async function enrichItemsWithBackendStatus({ force = false } = {}) {
  if (habrSyncing || !habrParsedItems.length) return null

  const previewKey = [
    habrResponsesPageKey(),
    ...habrParsedItems.map((i) => i.vacancy_id).sort(),
  ].join('|')
  if (!force && previewKey === habrLastPreviewKey) return habrPreviewError

  habrPreviewLoading = true
  updateSyncToolbar()

  const { error } = await fetchApplicationsPreview(habrParsedItems, habrSendMessage)
  habrPreviewLoading = false
  habrPreviewError = error || ''
  if (!error) habrLastPreviewKey = previewKey

  return habrPreviewError || null
}

function syncApplicationsStream(payload: Record<string, unknown>) {
  return new Promise((resolve, reject) => {
    if (!isExtensionAlive()) {
      reject(new Error('Расширение обновлено — обновите страницу Хабр Карьеры (F5)'))
      return
    }

    let settled = false
    let port: chrome.runtime.Port

    const timeout = window.setTimeout(() => {
      if (settled) return
      settled = true
      try {
        port?.disconnect()
      } catch {
        /* ignore */
      }
      reject(new Error('Таймаут синхронизации — проверьте backend (localhost:8000)'))
    }, 120_000)

    try {
      port = chrome.runtime.connect({ name: 'sync_negotiations_stream' })
    } catch (err) {
      clearTimeout(timeout)
      reject(err)
      return
    }

    port.onMessage.addListener((msg) => {
      if (msg.type === 'progress' && msg.event) renderSyncProgress(msg.event)
      if (msg.type === 'done') {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        port.disconnect()
        resolve(msg.data)
      }
      if (msg.type === 'error') {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        port.disconnect()
        reject(new Error(msg.error || 'Ошибка синхронизации'))
      }
    })

    port.onDisconnect.addListener(() => {
      if (settled) return
      if (chrome.runtime.lastError) {
        settled = true
        clearTimeout(timeout)
        reject(new Error(chrome.runtime.lastError.message))
      }
    })

    port.postMessage({ action: 'start', payload })
  })
}

async function syncApplicationItems(
  items: typeof habrParsedItems,
  options: { force?: boolean; dryRun?: boolean; auto?: boolean } = {},
) {
  const { force = false, dryRun = false, auto = false } = options
  if (!items.length) return

  habrSyncing = true
  habrStatusMessage = ''
  clearSyncProgress()
  updateSyncToolbar()
  renderSyncProgress({
    type: 'start',
    done: 0,
    total: items.length,
    message: dryRun ? 'Проверка…' : 'Синхронизация Хабр…',
  })

  try {
    let data: Record<string, unknown>
    if (dryRun) {
      data = (await applySync(items, { force, dryRun: true }, habrSendMessage)) as Record<
        string,
        unknown
      >
    } else {
      data = (await syncApplicationsStream({
        items: items.map(applicationsPayloadItem),
        dry_run: false,
        use_llm: true,
        force,
      })) as Record<string, unknown>
    }

    if (!data?.results) throw new Error('Пустой ответ синхронизации')
    applySyncResultsToItems(data.results as Array<Record<string, unknown>>)

    const synced = Number(data.synced_count ?? 0)
    const skipped = Number(data.skipped_count ?? 0)
    const msg = dryRun
      ? `Проверка: ${items.length} карточек`
      : auto
        ? `Авто-синх: ${synced} обновлено, ${skipped} без изменений`
        : `Готово: ${synced} обновлено, ${skipped} без изменений`

    clearSyncProgress()
    habrStatusMessage = msg
    renderApplicationsPanel()

    await enrichItemsWithBackendStatus({ force: true })
    renderApplicationsPanel()
  } catch (err) {
    clearSyncProgress()
    habrStatusMessage = String((err as Error).message || err)
    renderApplicationsPanel()
  } finally {
    habrSyncing = false
    updateSyncToolbar()
  }
}

async function onSyncAllDiscrepanciesClick() {
  await refreshApplicationsParse({ forcePreview: true })
  const toSync = pendingItems()
  if (!toSync.length) {
    habrStatusMessage = 'Все отклики синхронизированы с Copilot.'
    renderApplicationsPanel()
    return
  }
  await syncApplicationItems(toSync, { force: false })
}

async function refreshApplicationsParse({ forcePreview = false } = {}) {
  if (habrRefreshInFlight) return
  const payload = habrLastPayload
  const fingerprint = payload != null ? habrResponsesFingerprint(payload) : ''
  if (!forcePreview && fingerprint === habrLastFingerprint && habrParsedItems.length > 0) {
    updateSyncToolbar()
    return
  }

  habrRefreshInFlight = true
  try {
    habrParsedItems = parseApplicationsFromJson(payload)
    habrLastFingerprint = fingerprint

    if (!habrParsedItems.length) {
      habrPreviewLoading = false
      habrPreviewError = ''
      renderApplicationsPanel('')
      updateSyncToolbar()
      return
    }

    const previewErr = await enrichItemsWithBackendStatus({ force: forcePreview })
    habrParsedItems = sortApplicationItems(habrParsedItems)
    renderApplicationsPanel(previewErr || '')
    updateSyncToolbar()
    await maybeAutoSyncApplications()
  } finally {
    habrRefreshInFlight = false
    habrPreviewLoading = false
    updateSyncToolbar()
  }
}

// ── Источник данных: буфер + postMessage от MAIN-world перехватчика ──

function onPayload(payload: unknown): void {
  habrLastPayload = payload
  if (!habrParsedItems.length) {
    void refreshApplicationsParse({ forcePreview: true })
    return
  }
  const fp = habrResponsesFingerprint(payload)
  if (fp !== habrLastFingerprint) {
    void refreshApplicationsParse()
  }
}

function readBufferPayload(): unknown {
  try {
    const el = document.getElementById(BUFFER_ID) as HTMLScriptElement | null
    if (!el?.textContent) return null
    return JSON.parse(el.textContent)
  } catch {
    return null
  }
}

let interceptorInstalled = false

function installPostMessageListener(): void {
  if (interceptorInstalled) return
  interceptorInstalled = true
  window.addEventListener('message', (event) => {
    const data = event.data
    if (data && typeof data === 'object' && (data as Record<string, unknown>).__jh_habr_responses) {
      onPayload((data as Record<string, unknown>).payload)
    }
  })
}

function stopInterceptor(): void {
  // Слушатель window лёгкий и безопасный (проверяет флаг) — оставляем до размонтирования вкладки;
  // тут лишь сбрасываем признак, чтобы повторный mount не навесил дубль в этой же вкладке.
  interceptorInstalled = false
}

async function initApplicationsPage(slots: Parameters<typeof ensureApplicationsUi>[0]) {
  ensureApplicationsUi(slots)
  void ensureWebConfig()
  habrStatusMessage = ''
  renderApplicationsPanel()
  habrPreviewLoading = true
  updateSyncToolbar()

  installPostMessageListener()
  const buffered = readBufferPayload()
  if (buffered != null) {
    habrLastPayload = buffered
  }

  try {
    await refreshApplicationsParse({ forcePreview: true })
  } catch (err) {
    console.warn('Job Hunter: parse habr responses', err)
    habrStatusMessage = String((err as Error).message || err)
    renderApplicationsPanel()
  } finally {
    habrPreviewLoading = false
    updateSyncToolbar()
  }
}

function onApplicationsNavigate(
  _slots: unknown,
  ctx: { urlChanged: boolean; route: SiteRoute },
) {
  const pageKey = habrResponsesPageKey()
  const pageChanged = pageKey !== habrLastPageKey || ctx.urlChanged
  habrLastPageKey = pageKey

  if (pageChanged && !habrSyncing && !habrRefreshInFlight) {
    habrLastPreviewKey = ''
    habrLastFingerprint = ''
    habrAutoSyncedKey = ''
    habrStatusMessage = ''
    void refreshApplicationsParse({ forcePreview: true })
    return
  }

  if (!habrSyncing && !habrPreviewLoading && !habrRefreshInFlight) {
    scheduleDomRefresh()
  }
}

function scheduleDomRefresh() {
  if (habrSyncing || habrPreviewLoading || habrRefreshInFlight) return
  if (habrDomRefreshTimer) clearTimeout(habrDomRefreshTimer)
  habrDomRefreshTimer = setTimeout(() => {
    if (
      habrSyncing ||
      habrPreviewLoading ||
      habrRefreshInFlight ||
      !isExtensionAlive() ||
      getSite() !== 'habr' ||
      getPageType() !== HABR_PAGE_TYPE.RESPONSES
    ) {
      return
    }
    const payload = readBufferPayload() ?? habrLastPayload
    if (payload == null) return
    const fp = habrResponsesFingerprint(payload)
    if (fp === habrLastFingerprint && habrParsedItems.length > 0) return
    void refreshApplicationsParse()
  }, HABR_DOM_REFRESH_MS)
}

function mountApplicationsAdapter(slots: Parameters<typeof ensureApplicationsUi>[0]) {
  habrLastPageKey = habrResponsesPageKey()
  void initApplicationsPage(slots)
}

const habrApplicationsAdapter = {
  key: 'habr-applications',
  matches: (route: SiteRoute) =>
    route.site === 'habr' && route.pageType === HABR_PAGE_TYPE.RESPONSES,
  mount: mountApplicationsAdapter,
  onNavigate: onApplicationsNavigate,
  teardown: teardownApplicationsUi,
}

export { habrApplicationsAdapter }
