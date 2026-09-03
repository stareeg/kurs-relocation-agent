import { GETMATCH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import {
  parseGetmatchProfileStatsFromDom,
  type ParsedGetmatchProfileStats,
} from '../dom/selectors-getmatch-profile-stats'
import { waitForCondition } from '../dom/wait-for-condition'
import { iconMarkup } from '../ui/icons'

/**
 * GM-5.3: тихий ingest статистики профиля getmatch (`/profile/statistics`).
 * По образцу resumes.ts (AF-2): парсим DOM → POST /api/resume-stats, панель с цифрами + toast.
 */

const GM_STATS_BRAND = `<div class="jh-brand">${iconMarkup('sparkles', { size: 13 })}<span>Copilot</span></div>`

let gmShadowRoot: ShadowRoot | null = null
let gmPanelEl: HTMLElement | null = null
let gmToastEl: HTMLElement | null = null
let gmToastTimer: ReturnType<typeof setTimeout> | null = null
let gmExpandBtn: HTMLButtonElement | null = null
let gmCollapsed = false
let gmSentSig = ''
let gmInFlight = false

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id)
  } catch {
    return false
  }
}

function gmEscapeHtml(text: string) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function gmSendMessage(message: Record<string, unknown>) {
  return new Promise<{ ok?: boolean; error?: string; data?: { persisted?: boolean; inserted?: boolean } }>(
    (resolve) => {
      if (!isExtensionAlive()) {
        resolve({ ok: false, error: 'Расширение обновлено — обновите страницу getmatch.ru (F5)' })
        return
      }
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message })
            return
          }
          resolve(response)
        })
      } catch (err) {
        const e = err as Error
        resolve({ ok: false, error: String(e.message || err) })
      }
    },
  )
}

function gmCollapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="gm-stats-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`
}

function bindGmHeaderActions() {
  const collapseBtn = gmPanelEl?.querySelector('[data-action="gm-stats-collapse"]')
  collapseBtn?.addEventListener('click', onGmCollapseClick)
  gmPanelEl?.classList.toggle('hidden', gmCollapsed)
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

function ensureGmStatsUi(slots: {
  shadowRoot: ShadowRoot
  panelEl: HTMLElement
  toastEl: HTMLElement
  toolbarEl: HTMLElement
}) {
  gmShadowRoot = slots.shadowRoot
  gmPanelEl = slots.panelEl
  gmPanelEl.classList.add('jh-res-panel')
  gmPanelEl.classList.remove('hidden')
  gmToastEl = slots.toastEl
  gmCollapsed = false

  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-gm-stats-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
  `
  gmExpandBtn = gmShadowRoot.getElementById('jh-gm-stats-expand-btn') as HTMLButtonElement | null
  gmExpandBtn?.addEventListener('click', onGmExpandClick)

  renderGmStatsLoading()
}

function teardownGmStatsUi() {
  gmShadowRoot = null
  gmPanelEl = null
  gmToastEl = null
  gmExpandBtn = null
  gmCollapsed = false
  if (gmToastTimer) clearTimeout(gmToastTimer)
}

function renderGmStatsLoading() {
  if (!gmPanelEl) return
  gmPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${GM_STATS_BRAND}<strong>Статистика профиля</strong></div>
      ${gmCollapseBtnHtml()}
    </div>
    <div class="jh-body"><p class="jh-funnel-hint">Читаю просмотры профиля…</p></div>
  `
  bindGmHeaderActions()
}

function renderGmStatsPanel(stats: ParsedGetmatchProfileStats | null, statusHtml: string) {
  if (!gmPanelEl) return
  if (!stats) {
    gmPanelEl.innerHTML = `
      <div class="jh-header">
        <div class="jh-header-main">${GM_STATS_BRAND}<strong>Статистика профиля</strong></div>
        ${gmCollapseBtnHtml()}
      </div>
      <div class="jh-body"><p class="jh-funnel-hint">Блок «Кто смотрел ваш профиль» не найден. Обновите (F5).</p></div>
    `
    bindGmHeaderActions()
    return
  }

  const viewerHint =
    stats.raw.viewer_count > 0
      ? `${stats.raw.viewer_count} ${stats.raw.viewer_count === 1 ? 'компания' : 'компаний'} в списке`
      : 'Пока без просмотров за 30 дней'

  gmPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">
        ${GM_STATS_BRAND}<strong>Статистика профиля</strong>
        <span class="jh-neg-page-badge">getmatch · 30 дней</span>
      </div>
      ${gmCollapseBtnHtml()}
    </div>
    <div class="jh-body">
      <div class="jh-metrics" style="grid-template-columns:repeat(1,1fr)">
        <div class="jh-metric">
          <div class="jh-metric-head">${iconMarkup('users', { size: 14 })}<span class="jh-metric-label">Просмотры профиля</span></div>
          <div class="jh-metric-value">${gmEscapeHtml(String(stats.views))}</div>
        </div>
      </div>
      <p class="jh-funnel-hint">${gmEscapeHtml(viewerHint)}</p>
      ${statusHtml ? `<p class="jh-funnel-hint jh-res-status">${statusHtml}</p>` : ''}
    </div>
  `
  bindGmHeaderActions()
}

function gmStatusLine(message: string) {
  return `${iconMarkup('circle-check', { size: 13 })} ${gmEscapeHtml(message)}`
}

function showGmStatsToast(message: string) {
  if (!gmToastEl) return
  gmToastEl.innerHTML = `<span class="jh-toast-msg">${iconMarkup('circle-check', { size: 14 })}<span>${gmEscapeHtml(message)}</span></span>`
  gmToastEl.classList.remove('hidden')
  if (gmToastTimer) clearTimeout(gmToastTimer)
  gmToastTimer = setTimeout(() => {
    gmToastEl?.classList.add('hidden')
    if (gmToastEl) gmToastEl.innerHTML = ''
  }, 4000)
}

/** EXT-F3: MutationObserver вместо fixed-interval poll — резолвится на реальном DOM-изменении,
 *  дедлайн (6с) остаётся safety net'ом на случай, если виджет вообще не появится. */
async function waitForGetmatchProfileStats() {
  return waitForCondition(() => parseGetmatchProfileStatsFromDom(document), {
    timeoutMs: 6000,
    shouldCancel: () => !isExtensionAlive(),
  })
}

async function initGetmatchProfileStats() {
  if (gmInFlight) return
  gmInFlight = true
  try {
    const stats = await waitForGetmatchProfileStats()
    if (!stats) {
      renderGmStatsPanel(null, '')
      return
    }
    renderGmStatsPanel(stats, '')

    const sig = `${stats.resume_id}|${stats.views}|${stats.raw.viewer_count}`
    if (sig === gmSentSig) {
      renderGmStatsPanel(stats, gmStatusLine('Уже отправлено в этот визит'))
      return
    }

    const response = await gmSendMessage({ action: 'resumeStats', payload: stats })
    if (!response?.ok) {
      console.warn('Job Hunter: getmatch profile-stats не отправлены:', response?.error)
      renderGmStatsPanel(
        stats,
        `<span class="jh-res-delta down">Не сохранено: ${gmEscapeHtml(response?.error || 'нет связи с бэкендом')}</span>`,
      )
      return
    }
    gmSentSig = sig
    if (response.data?.persisted === false) {
      renderGmStatsPanel(stats, 'Бэкенд без БД — снимок не сохранён')
      return
    }
    const written = Boolean(response.data?.inserted)
    renderGmStatsPanel(stats, gmStatusLine(written ? 'Снимок записан' : 'Уже зафиксировано сегодня'))
    showGmStatsToast(
      written ? 'Просмотры getmatch записаны' : 'Просмотры getmatch уже зафиксированы сегодня',
    )
  } catch (err) {
    console.warn('Job Hunter: getmatch profile-stats', err)
  } finally {
    gmInFlight = false
  }
}

function mountGetmatchProfileStatsAdapter(slots: Parameters<typeof ensureGmStatsUi>[0]) {
  ensureGmStatsUi(slots)
  void initGetmatchProfileStats()
}

function onGetmatchProfileStatsNavigate(
  _slots: Parameters<typeof ensureGmStatsUi>[0],
  ctx: { urlChanged: boolean },
) {
  if (ctx.urlChanged) void initGetmatchProfileStats()
}

const getmatchProfileStatsAdapter = {
  key: 'getmatch-profile-stats',
  matches: (route: SiteRoute) =>
    route.site === 'getmatch' && route.pageType === GETMATCH_PAGE_TYPE.STATS,
  mount: mountGetmatchProfileStatsAdapter,
  onNavigate: onGetmatchProfileStatsNavigate,
  teardown: teardownGmStatsUi,
}

export { getmatchProfileStatsAdapter }
