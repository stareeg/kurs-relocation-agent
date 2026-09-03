import { GETMATCH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import { parseGetmatchProfileFromJson, type GmProfile } from '../dom/selectors-getmatch-profile-sync'
import { parseGetmatchTrustFromJson, type GmTrust } from '../dom/selectors-getmatch-trust'
import { iconMarkup } from '../ui/icons'

/**
 * GM-13 + GM-12: адаптер страницы /profile на getmatch — фетчит /api/profiles и /api/trust при
 * заходе пользователя на свою страницу профиля, показывает панель с расхождениями резюме и
 * статусом заполненности. ТОЛЬКО когда пользователь сам зашёл на /profile — без авто-хертбита
 * без его ведома.
 *
 * Заменяет старый `getmatch-profile-sync.ts` (который синчил профиль втихаря при любом заходе на
 * getmatch). Теперь синк запускается только в этом адаптере, когда страница = PROFILE.
 */

const BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 13 })}<span>Copilot</span></div>`

let gppShadowRoot: ShadowRoot | null = null
let gppPanelEl: HTMLElement | null = null
let gppToastEl: HTMLElement | null = null
let gppExpandBtn: HTMLButtonElement | null = null
let gppCollapsed = false
let gppInFlight = false
let gppProfileSent = false
let gppTrustSent = false
let gppToastTimer: ReturnType<typeof setTimeout> | null = null

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id)
  } catch { return false }
}

function gppSendMessage(message: Record<string, unknown>) {
  return new Promise<{ ok?: boolean; error?: string; data?: unknown }>((resolve) => {
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
      resolve({ ok: false, error: String((err as Error).message || err) })
    }
  })
}

function gppEscapeHtml(text: string) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function gppCollapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="gpp-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`
}

function bindGppHeaderActions() {
  const collapseBtn = gppPanelEl?.querySelector('[data-action="gpp-collapse"]')
  collapseBtn?.addEventListener('click', () => {
    gppCollapsed = true
    gppPanelEl?.classList.add('hidden')
    gppExpandBtn?.classList.remove('hidden')
  })
  gppPanelEl?.classList.toggle('hidden', gppCollapsed)
}

function onGppExpandClick() {
  gppCollapsed = false
  gppPanelEl?.classList.remove('hidden')
  gppExpandBtn?.classList.add('hidden')
}

function ensureGppUi(slots: { shadowRoot: ShadowRoot; panelEl: HTMLElement; toastEl: HTMLElement; toolbarEl: HTMLElement }) {
  gppShadowRoot = slots.shadowRoot
  gppPanelEl = slots.panelEl
  gppPanelEl.classList.add('jh-res-panel')
  gppPanelEl.classList.remove('hidden')
  gppToastEl = slots.toastEl
  gppCollapsed = false
  gppProfileSent = false
  gppTrustSent = false

  slots.toolbarEl.innerHTML = `<button type="button" class="jh-btn-expand hidden" id="jh-gpp-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>`
  gppExpandBtn = gppShadowRoot.getElementById('jh-gpp-expand-btn') as HTMLButtonElement | null
  gppExpandBtn?.addEventListener('click', onGppExpandClick)

  renderGppLoading()
}

function teardownGppUi() {
  gppShadowRoot = null
  gppPanelEl = null
  gppToastEl = null
  gppExpandBtn = null
  gppCollapsed = false
  if (gppToastTimer) clearTimeout(gppToastTimer)
}

function renderGppLoading() {
  if (!gppPanelEl) return
  gppPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${BRAND_HTML}<strong>Профиль getmatch</strong></div>
      ${gppCollapseBtnHtml()}
    </div>
    <div class="jh-body"><p class="jh-funnel-hint">Сравниваю с Copilot-резюме…</p></div>
  `
  bindGppHeaderActions()
}

function gppShowToast(message: string) {
  if (!gppToastEl) return
  gppToastEl.innerHTML = `<span class="jh-toast-msg">${iconMarkup('circle-check', { size: 14 })}<span>${gppEscapeHtml(message)}</span></span>`
  gppToastEl.classList.remove('hidden')
  if (gppToastTimer) clearTimeout(gppToastTimer)
  gppToastTimer = setTimeout(() => { gppToastEl?.classList.add('hidden'); if (gppToastEl) gppToastEl.innerHTML = '' }, 4000)
}


// ── fetching /api/profiles and /api/trust ──

async function fetchGetmatchProfilePayload(): Promise<unknown> {
  const response = await fetch('/api/profiles', {
    credentials: 'same-origin',
    headers: { 'content-type': 'application/json', 'x-client-platform': 'web' },
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

async function fetchGetmatchTrustPayload(): Promise<unknown> {
  const response = await fetch('/api/trust', {
    credentials: 'same-origin',
    headers: { 'content-type': 'application/json', 'x-client-platform': 'web' },
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

// ── rendering ──

type GppState = {
  profile: GmProfile | null
  trust: GmTrust | null
  profileErr: string | null
  trustErr: string | null
  // ответы от бэка (уже обработанные)
  diffDiscrepancies: number
  trustFilled: number
  trustTotal: number
  trustTrusted: boolean
  trustMissingChecks: string[]
  trustMissingConnections: string[]
}

function renderGppState(state: GppState) {
  if (!gppPanelEl) return
  const rows: string[] = []

  // ── секция 1: расхождения резюме ──
  if (state.profileErr) {
    rows.push(`<p class="jh-funnel-hint" style="color:var(--jh-red, #d92d20)">${gppEscapeHtml(state.profileErr)}</p>`)
  } else if (state.profile) {
    if (state.diffDiscrepancies === 0) {
      rows.push('<p class="jh-funnel-hint" style="color:var(--jh-green, #12b76a)">&#10003; Профиль getmatch совпадает с Copilot-резюме</p>')
    } else {
      rows.push(`<p class="jh-funnel-hint" style="color:var(--jh-amber, #f79009)">${iconMarkup('triangle-alert', { size: 13 })} Расходится ${state.diffDiscrepancies} ${state.diffDiscrepancies === 1 ? 'блок' : state.diffDiscrepancies < 5 ? 'блока' : 'блоков'} — см. вкладку «Резюме»</p>`)
    }
  }

  // ── секция 2: заполненность ──
  if (state.trustErr) {
    rows.push(`<p class="jh-funnel-hint" style="color:var(--jh-red, #d92d20)">${gppEscapeHtml(state.trustErr)}</p>`)
  } else if (state.trust) {
    const pct = Math.round((state.trustFilled / state.trustTotal) * 100)
    const color = state.trustTrusted ? 'color:var(--jh-green, #12b76a)' : pct >= 67 ? 'color:var(--jh-amber, #f79009)' : 'color:var(--jh-red, #d92d20)'
    rows.push(`<p class="jh-funnel-hint" style="${color}">Заполненность профиля: ${state.trustFilled}/${state.trustTotal} (${pct}%)${state.trustTrusted ? ' — доверенный' : ''}</p>`)

    if (state.trustMissingChecks.length) {
      rows.push(`<p class="jh-funnel-hint">Не заполнено: ${state.trustMissingChecks.map(s => gppEscapeHtml(s)).join(', ')}</p>`)
    }
    if (state.trustMissingConnections.length) {
      rows.push(`<p class="jh-funnel-hint">Не подключено: ${state.trustMissingConnections.map(s => gppEscapeHtml(s)).join(', ')}</p>`)
    }
  } else if (!state.trustErr) {
    rows.push('<p class="jh-funnel-hint">Заполненность профиля: загружаю…</p>')
  }

  if (!rows.length) {
    rows.push('<p class="jh-funnel-hint">Не удалось загрузить данные профиля</p>')
  }

  gppPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${BRAND_HTML}<strong>Профиль getmatch</strong></div>
      ${gppCollapseBtnHtml()}
    </div>
    <div class="jh-body">
      ${rows.join('\n')}
    </div>
  `
  bindGppHeaderActions()
}

// ── init ──

async function initGetmatchProfilePage() {
  if (gppInFlight) return
  gppInFlight = true
  const state: GppState = {
    profile: null, trust: null, profileErr: null, trustErr: null,
    diffDiscrepancies: 0, trustFilled: 0, trustTotal: 6, trustTrusted: false,
    trustMissingChecks: [], trustMissingConnections: [],
  }

  // Параллельно: профиль (для расхождений) + trust (для заполненности).
  const [profileResult, trustResult] = await Promise.allSettled([
    (async () => {
      const raw = await fetchGetmatchProfilePayload()
      const profile = parseGetmatchProfileFromJson(raw as Record<string, unknown>)
      if (!profile) throw new Error('Не удалось распарсить профиль')
      const resp = await gppSendMessage({ action: 'gm_profile_sync', payload: profile })
      if (!resp?.ok) throw new Error(resp?.error || 'Бэкенд не ответил')
      const data = resp.data as { discrepancies?: unknown[] } | undefined
      return { profile, discrepancies: (data?.discrepancies || []).length }
    })(),
    (async () => {
      const raw = await fetchGetmatchTrustPayload()
      const trust = parseGetmatchTrustFromJson(raw as Record<string, unknown>)
      if (!trust) throw new Error('Не удалось распарсить /api/trust')
      const resp = await gppSendMessage({ action: 'gm_trust_sync', payload: trust })
      if (!resp?.ok) throw new Error(resp?.error || 'Бэкенд не ответил')
      const data = resp.data as { status?: { filled_count?: number; total_checks?: number; trusted?: boolean; missing_checks?: string[]; missing_connections?: string[] } } | undefined
      const s = data?.status
      return {
        trust,
        filled: s?.filled_count ?? 0,
        total: s?.total_checks ?? 6,
        trusted: s?.trusted ?? false,
        missingChecks: s?.missing_checks ?? [],
        missingConnections: s?.missing_connections ?? [],
      }
    })(),
  ])

  if (profileResult.status === 'fulfilled') {
    state.profile = profileResult.value.profile
    state.diffDiscrepancies = profileResult.value.discrepancies
  } else {
    state.profileErr = String((profileResult.reason as Error)?.message || profileResult.reason)
    console.warn('[Job Hunter] getmatch profile-page profile:', profileResult.reason)
  }

  if (trustResult.status === 'fulfilled') {
    state.trust = trustResult.value.trust
    state.trustFilled = trustResult.value.filled
    state.trustTotal = trustResult.value.total
    state.trustTrusted = trustResult.value.trusted
    state.trustMissingChecks = trustResult.value.missingChecks
    state.trustMissingConnections = trustResult.value.missingConnections
  } else {
    state.trustErr = String((trustResult.reason as Error)?.message || trustResult.reason)
    console.warn('[Job Hunter] getmatch profile-page trust:', trustResult.reason)
  }

  renderGppState(state)
  if (!state.profileErr && !state.trustErr) {
    gppShowToast(
      state.diffDiscrepancies > 0
        ? `Расхождения с резюме: ${state.diffDiscrepancies}. Заполненность: ${state.trustFilled}/${state.trustTotal}`
        : `Профиль синхронизирован. Заполненность: ${state.trustFilled}/${state.trustTotal}`
    )
  }
  gppInFlight = false
}

// ── dock adapter ──

function mount(slots: { shadowRoot: ShadowRoot; panelEl: HTMLElement; toastEl: HTMLElement; toolbarEl: HTMLElement }) {
  ensureGppUi(slots)
  void initGetmatchProfilePage()
}

function onNavigate(_slots: unknown, ctx: { urlChanged: boolean }) {
  if (ctx.urlChanged) void initGetmatchProfilePage()
}

const getmatchProfilePageAdapter = {
  key: 'getmatch-profile-page',
  matches: (route: SiteRoute) =>
    route.site === 'getmatch' && route.pageType === GETMATCH_PAGE_TYPE.PROFILE,
  mount,
  onNavigate,
  teardown: teardownGppUi,
}

export { getmatchProfilePageAdapter }