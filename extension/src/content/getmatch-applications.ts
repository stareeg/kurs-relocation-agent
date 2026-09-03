import { getmatchApplicationsPageKey, getmatchApplicationsDomFingerprint } from '../dom/selectors-getmatch-applications'
import { GETMATCH_PAGE_TYPE, getPageType, getSite, type SiteRoute } from '../dom/site-router'
import { iconMarkup } from '../ui/icons'
import {
  isAutoSyncCandidate,
  applicationsPayloadItem,
  parseApplicationsFromRoot,
  fetchApplicationsPreview,
  applySync,
  countGmStatuses,
  gmStatusDisplayLabel,
} from './getmatch-applications-sync'
import { ensureWebConfig, openExternal, webJobUrl } from './web-links'
/** GM-5.1: синк откликов getmatch.ru/applications → Postgres (+ Sheets). */
function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id)
  } catch {
    return false
  }
}
let gmShadowRoot: ShadowRoot | null = null
let gmPanelEl: HTMLElement | null = null
let gmSyncAllBtn: HTMLButtonElement | null = null
let gmExpandBtn: HTMLButtonElement | null = null
let gmParsedItems: ReturnType<typeof parseApplicationsFromRoot> = []
let gmSyncing = false
let gmPreviewLoading = false
let gmCollapsed = false
let gmLastPageKey = getmatchApplicationsPageKey(location.href)
let gmDomRefreshTimer: ReturnType<typeof setTimeout> | null = null
let gmLastPreviewKey = ''
let gmPreviewError = ''
let gmAutoSyncedKey = ''
let gmStatusMessage = ''
let gmLastSyncAt: Date | null = null
let gmLastDomFingerprint = ''
let gmRefreshInFlight = false
const GM_DOM_REFRESH_MS = 4000
/** Показывать ли архивные (>90 дней) отклики. По умолчанию скрыты. localStorage-ключ. */
let gmShowArchive: boolean
const GM_SHOW_ARCHIVE_KEY = 'jc_gm_show_archive'
function loadGmShowArchive(): boolean {
  try {
    return localStorage.getItem(GM_SHOW_ARCHIVE_KEY) === '1'
  } catch {
    return false
  }
}
function saveGmShowArchive(v: boolean) {
  try {
    localStorage.setItem(GM_SHOW_ARCHIVE_KEY, v ? '1' : '0')
  } catch {
    /* localStorage недоступен — не критично */
  }
}
gmShowArchive = loadGmShowArchive()
function gmEscapeHtml(text: string) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
function gmSendMessage(message: unknown): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено — обновите страницу getmatch.ru (F5)' })
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
function sortApplicationItems(items: typeof gmParsedItems) {
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
/** Карточки, видимые с учётом фильтра архива. */
function visibleItems() {
  if (gmShowArchive) return gmParsedItems
  return gmParsedItems.filter((x) => !x.is_stale)
}
/** Карточки, скрытые фильтром (только архивные). */
function hiddenStaleItems() {
  return gmParsedItems.filter((x) => x.is_stale)
}
function pendingItems() {
  return visibleItems().filter((x) => x.is_discrepancy && x.sync_state !== 'synced')
}
function syncedCount() {
  return visibleItems().filter((x) => x.sync_state === 'synced').length
}
async function maybeAutoSyncApplications() {
  if (gmSyncing || gmPreviewLoading || gmPreviewError) return
  const key = getmatchApplicationsPageKey()
  if (gmAutoSyncedKey === key) return
  const candidates = gmParsedItems.filter(isAutoSyncCandidate)
  gmAutoSyncedKey = key
  if (!candidates.length) return
  await syncApplicationItems(candidates, { force: false, auto: true })
}
function ensureApplicationsUi(slots: {
  shadowRoot: ShadowRoot
  panelEl: HTMLElement
  toolbarEl: HTMLElement
}) {
  gmShadowRoot = slots.shadowRoot
  gmPanelEl = slots.panelEl
  gmPanelEl.classList.add('jh-neg-panel', 'jh-gm-apps-panel')
  gmPanelEl.classList.remove('hidden')
  gmCollapsed = false
  slots.toolbarEl.classList.add('jh-neg-toolbar', 'jh-gm-apps-toolbar')
  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-gm-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
    <button type="button" class="jh-btn" id="jh-gm-sync-all-btn">${iconMarkup('refresh-cw', { size: 14 })}<span>Обновить</span></button>
  `
  gmSyncAllBtn = gmShadowRoot.getElementById('jh-gm-sync-all-btn') as HTMLButtonElement
  gmSyncAllBtn.addEventListener('click', onSyncAllDiscrepanciesClick)
  gmExpandBtn = gmShadowRoot.getElementById('jh-gm-expand-btn') as HTMLButtonElement
  gmExpandBtn.addEventListener('click', onGmExpandClick)
}
function teardownApplicationsUi() {
  if (gmDomRefreshTimer) clearTimeout(gmDomRefreshTimer)
  gmDomRefreshTimer = null
  gmShadowRoot = null
  gmPanelEl = null
  gmSyncAllBtn = null
  gmExpandBtn = null
  gmParsedItems = []
  gmLastPreviewKey = ''
  gmPreviewError = ''
  gmAutoSyncedKey = ''
  gmStatusMessage = ''
  gmLastSyncAt = null
  gmLastDomFingerprint = ''
  gmRefreshInFlight = false
  gmCollapsed = false
  gmSyncing = false
  gmPreviewLoading = false
}
function onGmCollapseClick() {
  gmCollapsed = true
  gmPanelEl?.classList.add('hidden')
  gmExpandBtn?.classList.remove('hidden')
}
function onGmExpandClick() {
  gmCollapsed = false
  gmPanelEl?.classList.remove('hidden')
  gmExpandBtn?.classList.add('hidden')
}
function gmCollapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="gm-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`
}
function formatSyncTime(d: Date | null) {
  if (!d) return ''
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}
/** Единая разметка кнопки «Обновить» в тулбаре — иконка+подпись. Иконка зависит от состояния:
 *  спиннер во время синка/загрузки (как у negotiations.ts), галочка в состоянии «всё синхронизировано». */
function gmSyncAllBtnHtml(label: string, state: 'idle' | 'loading' | 'synced' = 'idle') {
  const icon =
    state === 'loading'
      ? iconMarkup('loader', { size: 14, className: 'jh-spin' })
      : state === 'synced'
        ? iconMarkup('circle-check', { size: 14 })
        : iconMarkup('refresh-cw', { size: 14 })
  return `${icon}<span>${label}</span>`
}
function updateSyncToolbar() {
  if (!gmSyncAllBtn) return
  const pending = pendingItems().length
  const total = visibleItems().length
  const synced = syncedCount()
  if (gmSyncing || gmPreviewLoading) {
    gmSyncAllBtn.disabled = true
    gmSyncAllBtn.classList.add('jh-btn-loading')
    gmSyncAllBtn.innerHTML = gmSyncAllBtnHtml(
      gmSyncing ? 'Синхронизация…' : 'Загрузка…',
      'loading',
    )
    return
  }
  gmSyncAllBtn.classList.remove('jh-btn-loading')
  gmSyncAllBtn.disabled = !total || Boolean(gmPreviewError)
  if (gmPreviewError) {
    gmSyncAllBtn.innerHTML = gmSyncAllBtnHtml('Обновить', 'idle')
  } else if (total > 0 && pending === 0) {
    gmSyncAllBtn.innerHTML = gmSyncAllBtnHtml('Всё синхронизировано', 'synced')
    // Не disabled — можно нажать, чтобы перепроверить статусы на бэке
    gmSyncAllBtn.disabled = false
  } else if (pending > 0) {
    gmSyncAllBtn.innerHTML = gmSyncAllBtnHtml(`Обновить (${pending})`, 'idle')
  } else {
    gmSyncAllBtn.innerHTML = gmSyncAllBtnHtml('Обновить', 'idle')
  }
  gmSyncAllBtn.title =
    total > 0
      ? `${synced}/${total} синхронизировано${gmLastSyncAt ? ` · ${formatSyncTime(gmLastSyncAt)}` : ''}`
      : ''
}
function gmHeaderHtml() {
  const items = visibleItems()
  const total = items.length
  const synced = syncedCount()
  const counts = countGmStatuses(items)
  const hiddenStale = hiddenStaleItems().length
  const plural = total === 1 ? 'отклик' : total >= 2 && total <= 4 ? 'отклика' : 'откликов'
  const showArchiveBtn = hiddenStale > 0
    ? `<button type="button" class="jh-gm-archive-toggle" data-action="toggle-archive">${gmShowArchive ? 'Скрыть архив' : `Показать архив (${hiddenStale})`}</button>`
    : ''
  const statusDots = [
    counts.approved ? `<span class="jh-gm-dotstat" title="${counts.approved} одобрено"><span class="jh-gm-dot jh-gm-dot-approved"></span>${counts.approved}</span>` : '',
    counts.waiting ? `<span class="jh-gm-dotstat" title="${counts.waiting} ожидание"><span class="jh-gm-dot jh-gm-dot-waiting"></span>${counts.waiting}</span>` : '',
    counts.rejected ? `<span class="jh-gm-dotstat" title="${counts.rejected} отказ"><span class="jh-gm-dot jh-gm-dot-rejected"></span>${counts.rejected}</span>` : '',
  ].filter(Boolean)
  const syncHint =
    gmSyncing || gmPreviewLoading
      ? gmSyncing
        ? 'Синхронизация с Copilot…'
        : 'Загрузка статусов…'
      : gmLastSyncAt
        ? `Обновлено ${formatSyncTime(gmLastSyncAt)}`
        : ''
  return `
    <div class="jh-header jh-gm-apps-header">
      <div class="jh-header-main jh-gm-apps-header-main">
        <div class="jh-gm-summary">
          ${iconMarkup('clipboard-list', { size: 14, className: 'jh-gm-summary-icon' })}
          <span class="jh-gm-summary-text"><strong>${total}</strong> ${plural} · ${synced}/${total} в Copilot</span>
          ${statusDots.length ? `<span class="jh-gm-dots">${statusDots.join('')}</span>` : ''}
        </div>
        ${syncHint ? `<div class="jh-gm-sync-hint">${gmEscapeHtml(syncHint)}</div>` : ''}
        ${showArchiveBtn}
      </div>
      ${gmCollapseBtnHtml()}
    </div>`
}
function gmStatusDotClass(gmStatus: string) {
  if (gmStatus === 'rejected') return 'jh-gm-dot-rejected'
  if (gmStatus === 'approved') return 'jh-gm-dot-approved'
  if (gmStatus === 'waiting') return 'jh-gm-dot-waiting'
  return 'jh-gm-dot-unknown'
}
function gmCardHtml(item: (typeof gmParsedItems)[number]) {
  const gmLabel = gmEscapeHtml(gmStatusDisplayLabel(item.gm_status))
  const meta = gmEscapeHtml(item.gm_meta_status || '')
  const jhCurrent = gmEscapeHtml(item.current_status || '—')
  const jhProposed = gmEscapeHtml(item.funnel_status_preview || '—')
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
    item.is_archived
      ? `<span class="jh-gm-badge jh-gm-badge-archived" title="Вакансия снята с публикации">${iconMarkup('archive', { size: 12 })}</span>`
      : '',
    item.is_stale
      ? `<span class="jh-gm-badge jh-gm-badge-stale" title="Старше 90 дней — уходит в архив">${iconMarkup('archive', { size: 12 })}</span>`
      : '',
    item.needs_vacancy_text
      ? `<span class="jh-gm-badge jh-gm-badge-needs-text" title="Нет текста вакансии — откройте страницу на getmatch. Без скора карточка удалится через 6 ч.">${iconMarkup('triangle-alert', { size: 12 })}</span>`
      : '',
    item.is_discrepancy && item.sync_state !== 'synced'
      ? `<span class="jh-gm-badge jh-gm-badge-disc" title="Расхождение с Copilot">${iconMarkup('circle-x', { size: 12 })}</span>`
      : '',
  ]
    .filter(Boolean)
    .join('')
  return `
    <article class="jh-gm-app-card ${cardCls}" data-vacancy-id="${gmEscapeHtml(item.vacancy_id)}">
      <div class="jh-gm-app-card-head">
        <span class="jh-gm-status-dot ${gmStatusDotClass(item.gm_status)}" title="${gmLabel}${meta ? ` · ${meta}` : ''}"></span>
        <div class="jh-gm-app-card-titles">
          <span class="jh-gm-app-company">${gmEscapeHtml(item.company || '—')}</span>
          <span class="jh-gm-app-title" title="${gmEscapeHtml(item.title || '')}">${gmEscapeHtml(item.title || '—')}</span>
        </div>
        <div class="jh-gm-card-head-actions">
          <button type="button" class="jh-gm-icon-btn" data-action="open-web" data-vacancy-id="${gmEscapeHtml(item.vacancy_id)}" title="Открыть в вебе">${iconMarkup('external-link', { size: 13 })}</button>
          <button type="button" class="jh-gm-icon-btn" data-action="open-gm" data-url="${gmEscapeHtml(item.url || '')}" title="Открыть на getmatch">${iconMarkup('globe', { size: 13 })}</button>
        </div>
      </div>
      ${funnelRow}
      ${badges ? `<div class="jh-gm-badges">${badges}</div>` : ''}
    </article>`
}
function renderSyncProgress(event: Record<string, unknown>) {
  if (!event || !gmPanelEl || !gmShadowRoot) return
  let wrap = gmShadowRoot.getElementById('jh-gm-progress-wrap')
  if (!wrap) {
    wrap = document.createElement('div')
    wrap.id = 'jh-gm-progress-wrap'
    wrap.className = 'jh-neg-progress-wrap'
    const body = gmPanelEl.querySelector('.jh-body')
    body?.prepend(wrap)
  }
  const done = Number(event.done ?? 0)
  const total = Number(event.total ?? 1) || 1
  const pct = Math.min(100, Math.round((done / total) * 100))
  wrap.innerHTML = `
    <div class="jh-neg-progress-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
      <div class="jh-neg-progress-fill" style="width:${pct}%"></div>
    </div>
    <div class="jh-neg-progress-label">${gmEscapeHtml(String(event.message || `${done} / ${total}`))}</div>
  `
}
function clearSyncProgress() {
  gmShadowRoot?.getElementById('jh-gm-progress-wrap')?.remove()
}
function bindGmPanelActions() {
  gmPanelEl?.querySelector('[data-action="gm-collapse"]')?.addEventListener('click', onGmCollapseClick)
  gmPanelEl?.querySelector('[data-action="toggle-archive"]')?.addEventListener('click', () => {
    gmShowArchive = !gmShowArchive
    saveGmShowArchive(gmShowArchive)
    renderApplicationsPanel()
  })
  gmPanelEl?.querySelectorAll('[data-action="open-web"]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const vid = btn.getAttribute('data-vacancy-id')
      if (!vid) return
      const cfg = await ensureWebConfig()
      openExternal(webJobUrl(vid, cfg.webBaseUrl))
    })
  })
  gmPanelEl?.querySelectorAll('[data-action="open-gm"]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const url = btn.getAttribute('data-url')
      if (url) openExternal(url)
    })
  })
}
function renderApplicationsPanel(message = '') {
  if (!gmPanelEl) return
  if (message) gmStatusMessage = message
  const sorted = sortApplicationItems(visibleItems())
  if (!sorted.length) {
    const emptyHint = gmParsedItems.length
      ? 'Все отклики старше 90 дней и скрыты. Нажмите «Показать архив», чтобы увидеть их.'
      : 'Карточки откликов не найдены. Дождитесь загрузки списка или обновите страницу (F5).'
    gmPanelEl.innerHTML = `
      ${gmHeaderHtml()}
      <div class="jh-body">
        <p class="jh-funnel-hint">${gmEscapeHtml(emptyHint)}</p>
        ${gmPreviewError ? `<div class="jh-error">${gmEscapeHtml(gmPreviewError)}</div>` : ''}
        ${gmStatusMessage ? `<div class="jh-neg-msg">${gmEscapeHtml(gmStatusMessage)}</div>` : ''}
      </div>
    `
    bindGmPanelActions()
    updateSyncToolbar()
    gmPanelEl.classList.toggle('hidden', gmCollapsed)
    return
  }
  gmPanelEl.innerHTML = `
    ${gmHeaderHtml()}
    <div class="jh-body">
      ${gmPreviewError ? `<div class="jh-error">${gmEscapeHtml(gmPreviewError)}</div>` : ''}
      ${gmStatusMessage ? `<div class="jh-neg-msg">${gmEscapeHtml(gmStatusMessage)}</div>` : ''}
      <div class="jh-neg-cards jh-gm-app-cards">${sorted.map(gmCardHtml).join('')}</div>
    </div>
  `
  bindGmPanelActions()
  updateSyncToolbar()
  gmPanelEl.classList.toggle('hidden', gmCollapsed)
}
function applySyncResultsToItems(results: Array<Record<string, unknown>>) {
  if (!results?.length) return
  const byId = Object.fromEntries(results.map((r) => [String(r.vacancy_id), r]))
  for (const item of gmParsedItems) {
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
  gmParsedItems = sortApplicationItems(gmParsedItems)
  gmLastPreviewKey = ''
  gmLastSyncAt = new Date()
}
async function waitForApplicationCards(maxMs = 10000): Promise<void> {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    const n = document.querySelectorAll('article[class*="applicationCard_card"]').length
    if (n > 0) return
    await new Promise((r) => setTimeout(r, 250))
  }
}
async function enrichItemsWithBackendStatus({ force = false } = {}) {
  if (gmSyncing || !gmParsedItems.length) return null
  const previewKey = [
    getmatchApplicationsPageKey(),
    ...gmParsedItems.map((i) => i.vacancy_id).sort(),
  ].join('|')
  if (!force && previewKey === gmLastPreviewKey) return gmPreviewError
  gmPreviewLoading = true
  updateSyncToolbar()
  const { error } = await fetchApplicationsPreview(gmParsedItems, gmSendMessage)
  gmPreviewLoading = false
  gmPreviewError = error || ''
  if (!error) gmLastPreviewKey = previewKey
  return gmPreviewError || null
}
function syncApplicationsStream(payload: Record<string, unknown>) {
  return new Promise((resolve, reject) => {
    if (!isExtensionAlive()) {
      reject(new Error('Расширение обновлено — обновите страницу getmatch.ru (F5)'))
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
  items: typeof gmParsedItems,
  options: { force?: boolean; dryRun?: boolean; auto?: boolean } = {},
) {
  const { force = false, dryRun = false, auto = false } = options
  if (!items.length) return
  gmSyncing = true
  gmStatusMessage = ''
  clearSyncProgress()
  updateSyncToolbar()
  renderSyncProgress({
    type: 'start',
    done: 0,
    total: items.length,
    message: dryRun ? 'Проверка…' : 'Синхронизация getmatch…',
  })
  try {
    let data: Record<string, unknown>
    if (dryRun) {
      data = (await applySync(items, { force, dryRun: true }, gmSendMessage)) as Record<
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
    gmStatusMessage = msg
    renderApplicationsPanel()
    await enrichItemsWithBackendStatus({ force: true })
    renderApplicationsPanel()
  } catch (err) {
    clearSyncProgress()
    gmStatusMessage = String((err as Error).message || err)
    renderApplicationsPanel()
  } finally {
    gmSyncing = false
    updateSyncToolbar()
  }
}
async function onSyncAllDiscrepanciesClick() {
  await refreshApplicationsParse({ forcePreview: true })
  const toSync = pendingItems()
  if (!toSync.length) {
    gmStatusMessage = 'Все отклики синхронизированы с Copilot.'
    renderApplicationsPanel()
    return
  }
  await syncApplicationItems(toSync, { force: false })
}
async function refreshApplicationsParse({ forcePreview = false } = {}) {
  if (gmRefreshInFlight) return
  const fingerprint = getmatchApplicationsDomFingerprint(document)
  if (!forcePreview && fingerprint === gmLastDomFingerprint && gmParsedItems.length > 0) {
    updateSyncToolbar()
    return
  }
  gmRefreshInFlight = true
  try {
    gmParsedItems = parseApplicationsFromRoot(document)
    gmLastDomFingerprint = fingerprint
    if (!gmParsedItems.length) {
      gmPreviewLoading = false
      gmPreviewError = ''
      renderApplicationsPanel('')
      updateSyncToolbar()
      return
    }
    const previewErr = await enrichItemsWithBackendStatus({ force: forcePreview })
    gmParsedItems = sortApplicationItems(gmParsedItems)
    renderApplicationsPanel(previewErr || '')
    updateSyncToolbar()
    await maybeAutoSyncApplications()
  } finally {
    gmRefreshInFlight = false
    gmPreviewLoading = false
    updateSyncToolbar()
  }
}
async function initApplicationsPage(slots: Parameters<typeof ensureApplicationsUi>[0]) {
  ensureApplicationsUi(slots)
  void ensureWebConfig()
  gmStatusMessage = ''
  renderApplicationsPanel()
  gmPreviewLoading = true
  updateSyncToolbar()
  try {
    await waitForApplicationCards()
    await refreshApplicationsParse({ forcePreview: true })
  } catch (err) {
    console.warn('Job Hunter: parse getmatch applications', err)
    gmStatusMessage = String((err as Error).message || err)
    renderApplicationsPanel()
  } finally {
    gmPreviewLoading = false
    updateSyncToolbar()
  }
}
function onApplicationsNavigate(
  _slots: unknown,
  ctx: { urlChanged: boolean; route: SiteRoute },
) {
  const pageKey = getmatchApplicationsPageKey()
  const pageChanged = pageKey !== gmLastPageKey || ctx.urlChanged
  gmLastPageKey = pageKey
  if (pageChanged && !gmSyncing && !gmRefreshInFlight) {
    gmLastPreviewKey = ''
    gmLastDomFingerprint = ''
    gmAutoSyncedKey = ''
    gmStatusMessage = ''
    void refreshApplicationsParse({ forcePreview: true })
    return
  }
  if (!gmSyncing && !gmPreviewLoading && !gmRefreshInFlight) {
    scheduleApplicationsDomRefresh()
  }
}
function scheduleApplicationsDomRefresh() {
  if (gmSyncing || gmPreviewLoading || gmRefreshInFlight) return
  if (gmDomRefreshTimer) clearTimeout(gmDomRefreshTimer)
  gmDomRefreshTimer = setTimeout(() => {
    if (
      gmSyncing ||
      gmPreviewLoading ||
      gmRefreshInFlight ||
      !isExtensionAlive() ||
      getSite() !== 'getmatch' ||
      getPageType() !== GETMATCH_PAGE_TYPE.APPLICATIONS
    ) {
      return
    }
    const fp = getmatchApplicationsDomFingerprint(document)
    if (fp === gmLastDomFingerprint && gmParsedItems.length > 0) return
    void refreshApplicationsParse()
  }, GM_DOM_REFRESH_MS)
}
function mountApplicationsAdapter(slots: Parameters<typeof ensureApplicationsUi>[0]) {
  gmLastPageKey = getmatchApplicationsPageKey()
  void initApplicationsPage(slots)
}
const getmatchApplicationsAdapter = {
  key: 'getmatch-applications',
  matches: (route: SiteRoute) =>
    route.site === 'getmatch' && route.pageType === GETMATCH_PAGE_TYPE.APPLICATIONS,
  mount: mountApplicationsAdapter,
  onNavigate: onApplicationsNavigate,
  teardown: teardownApplicationsUi,
}
export { getmatchApplicationsAdapter }
