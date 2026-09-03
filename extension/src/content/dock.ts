import { resolveRoute, type SiteRoute } from '../dom/site-router'
import { iconMarkup } from '../ui/icons'
import { fetchAuthStatusViaBackground, loginWithTokenViaBackground } from '../auth/api'
import { isAuthActive, renderAuthSection, type AuthSectionState } from '../auth/render'
import {
  clearAccountScopedStorage,
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from '../auth/token'

/**
 * EX-7 / GM-4: единый «док» — persistent shadow-host на hh.ru и getmatch.ru.
 * Роутинг по { site, pageType } через site-router; адаптеры site-aware.
 * EX-18: весь док — ОДНО окно (.jh-window): бар (тулбар адаптера + кнопка «Аккаунт») и панель
 * делят одну рамку/тень/скругления, а не плавают тремя независимыми блоками. Вход по токену
 * гейтит вообще всё — ни один адаптер не монтируется (и ни один запрос к бэку не уходит), пока
 * пользователь не вставит токен прямо в этой панели (не в отдельной вкладке options.html).
 */

/**
 * @typedef {Object} DockSlots
 * @property {ShadowRoot} shadowRoot
 * @property {HTMLElement} panelEl
 * @property {HTMLElement} toastEl
 * @property {HTMLElement} toolbarEl
 * @property {HTMLElement} barActionsEl
 * @property {boolean} accountOpen
 * @property {() => void} closeAccount
 */

/**
 * @typedef {Object} DockAdapter
 * @property {string} key
 * @property {(route: SiteRoute) => boolean} matches
 * @property {(slots: DockSlots) => void} mount
 * @property {(slots: DockSlots, ctx: { urlChanged: boolean, route: SiteRoute }) => void} [onNavigate]
 * @property {(slots: DockSlots) => void} [teardown]
 * @property {boolean} [liftForHhChat]
 */

let shadowHost: HTMLElement | null = null
let shadowRoot: ShadowRoot | null = null
let rootEl: HTMLElement | null = null
let windowEl: HTMLElement | null = null
let panelEl: HTMLElement | null = null
let toastEl: HTMLElement | null = null
let toolbarEl: HTMLElement | null = null
let barActionsEl: HTMLElement | null = null
let settingsBtn: HTMLElement | null = null
let settingsDotEl: HTMLElement | null = null
let accountEl: HTMLElement | null = null
/** @type {DockAdapter[]} */
let registeredAdapters: DockAdapter[] = []
/** @type {DockAdapter | null} */
let currentAdapter: DockAdapter | null = null
let lastUrl = ''

type DockAdapter = {
  key: string
  matches: (route: SiteRoute) => boolean
  mount: (slots: DockSlots) => void
  onNavigate?: (
    slots: DockSlots,
    ctx: { urlChanged: boolean; route: SiteRoute },
  ) => void
  teardown?: (slots: DockSlots) => void
  liftForHhChat?: boolean
}

type DockSlots = {
  shadowRoot: ShadowRoot
  panelEl: HTMLElement
  toastEl: HTMLElement
  toolbarEl: HTMLElement
  /** Слот действий в баре слева от «Аккаунт» (Свернуть / Обновить / Вернуть в воронку). */
  barActionsEl: HTMLElement
  /** true, пока открыт экран «Аккаунт» — панель адаптера скрыта, действия в баре гаснут. */
  accountOpen: boolean
  /** Вернуться с экрана «Аккаунт» на интерфейс адаптера. */
  closeAccount: () => void
}

// ── EX-18: гейт входа — общий для всех адаптеров ──

/** true как только известно, что вход активен; пока false, ни один адаптер не монтируется. */
let authed = false
let authCheckStarted = false
let authSectionState: AuthSectionState = { status: null, checking: false, error: null, pending: false }
let accountPanelOpen = false

const GATE_BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 14 })}<span>Copilot</span></div>`

async function loadPanelStyles() {
  const url = chrome.runtime.getURL('dist/panel.css')
  const response = await fetch(url)
  return response.text()
}

function ensureShell() {
  if (shadowHost) return

  shadowHost = document.createElement('div')
  shadowHost.id = 'job-hunter-copilot-root'
  document.documentElement.appendChild(shadowHost)
  shadowRoot = shadowHost.attachShadow({ mode: 'closed' })

  loadPanelStyles()
    .then((css) => {
      const style = document.createElement('style')
      style.textContent = css
      shadowRoot!.appendChild(style)
    })
    .catch((err) => console.warn('[Job Hunter] panel.css:', err))

  rootEl = document.createElement('div')
  rootEl.className = 'jh-root'
  rootEl.innerHTML = `
    <div class="jh-window jh-window-gated" id="jh-dock-window">
      <div class="jh-bar" id="jh-dock-bar">
        <div class="jh-bar-actions" id="jh-dock-bar-actions"></div>
        <div class="jh-toolbar" id="jh-dock-toolbar"></div>
        <button class="jh-settings-btn hidden" id="jh-dock-settings" type="button" title="Аккаунт" aria-label="Аккаунт">
          ${iconMarkup('user', { size: 14 })}<span>Аккаунт</span>
          <span class="jh-settings-dot ok" id="jh-dock-settings-dot"></span>
        </button>
      </div>
      <div class="jh-panel hidden" id="jh-dock-panel"></div>
      <div class="jh-account-panel hidden" id="jh-dock-account"></div>
    </div>
    <div class="jh-toast hidden" id="jh-dock-toast"></div>
  `
  shadowRoot.appendChild(rootEl)

  windowEl = shadowRoot.getElementById('jh-dock-window')!
  panelEl = shadowRoot.getElementById('jh-dock-panel')!
  toastEl = shadowRoot.getElementById('jh-dock-toast')!
  toolbarEl = shadowRoot.getElementById('jh-dock-toolbar')!
  barActionsEl = shadowRoot.getElementById('jh-dock-bar-actions')!
  settingsBtn = shadowRoot.getElementById('jh-dock-settings')!
  settingsDotEl = shadowRoot.getElementById('jh-dock-settings-dot')!
  accountEl = shadowRoot.getElementById('jh-dock-account')!

  settingsBtn.addEventListener('click', () => {
    if (!authed) return
    accountPanelOpen = !accountPanelOpen
    renderAccountPanel()
  })
}

/** Экран «Аккаунт» открыт — адаптер прячет свои действия из бара и свою панель. */
function isAccountOpen(): boolean {
  return accountPanelOpen
}

function closeAccountPanel(): void {
  if (!accountPanelOpen) return
  accountPanelOpen = false
  renderAccountPanel()
}

// ── Вход: пока не authed=true, route() не подпускает ни один адаптер к mount() ──

async function checkAuthGate(): Promise<void> {
  const token = await getStoredAuthToken()
  if (!token) {
    // Токена нет вовсе — единственный случай, где стоит держать полный гейт: без него
    // адаптеры не монтируются, к бэку не уходит ни одного запроса (сам баг, который чиним).
    authed = false
    authSectionState = { status: null, checking: false, error: null, pending: false }
    renderGate()
    return
  }
  // Токен в сторадже есть — пускаем адаптеры сразу, не дожидаясь сети: иначе каждая загрузка
  // страницы уже вошедшего пользователя тормозится на /auth/status. Статус уточняем в фоне —
  // если окажется, что токен отозван, гасим текущий адаптер и возвращаем форму входа.
  // checking=true (а не status=null сразу) — иначе клик по «Аккаунту» в этом коротком окне
  // ошибочно показал бы форму входа вместо «вход активен» (renderAuthSection трактует
  // status=null+checking=false как «не вошёл»).
  authed = true
  authSectionState = { status: null, checking: true, error: null, pending: false }
  renderGate()
  route()
  try {
    const status = await fetchAuthStatusViaBackground(token)
    authSectionState = { status, checking: false, error: null, pending: false }
    if (!isAuthActive(status)) {
      authed = false
      if (currentAdapter?.teardown) {
        try {
          currentAdapter.teardown(getSlots())
        } catch (err) {
          console.warn('[Job Hunter] dock teardown (auth revoked):', err)
        }
      }
      currentAdapter = null
      resetSlots()
    }
    renderGate()
    renderAccountPanel()
  } catch {
    /* бэк недоступен/сеть моргнула — статус в панели «Аккаунт» останется пустым, конкретное
       действие (скоринг и т.п.) само покажет ошибку, если она реальна */
  }
}

function ensureAuthGateStarted() {
  if (authCheckStarted) return
  authCheckStarted = true
  void checkAuthGate()
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return
    if (changes.authToken) void checkAuthGate()
  })
}

async function handleGateLogin(token: string): Promise<void> {
  authSectionState = { ...authSectionState, pending: true, error: null }
  renderGate()
  try {
    const status = await loginWithTokenViaBackground(token)
    await clearAccountScopedStorage()
    await setStoredAuthToken(token)
    authSectionState = { status, checking: false, error: null, pending: false }
    authed = isAuthActive(status)
  } catch (err) {
    authSectionState = { status: null, checking: false, error: (err as Error).message, pending: false }
  }
  renderGate()
  if (authed) route()
}

/** Рисует форму входа в panelEl, пока не authed; ничего не делает, когда вход уже активен —
 *  тогда panelEl полностью в распоряжении текущего адаптера. */
function renderGate() {
  if (!windowEl || !toolbarEl || !settingsBtn || !panelEl) return
  windowEl.classList.toggle('jh-window-gated', !authed)
  settingsBtn.classList.toggle('hidden', !authed)
  syncSettingsDot()
  if (authed) return

  panelEl.classList.remove('hidden')
  panelEl.setAttribute('role', 'dialog')
  panelEl.setAttribute('aria-label', 'Copilot — вход')
  if (!shadowRoot!.getElementById('jh-gate-auth')) {
    panelEl.innerHTML = `
      <div class="jh-header">
        <div class="jh-header-main">${GATE_BRAND_HTML}</div>
      </div>
      <div class="jh-body">
        <p class="jh-gate-lead">Войдите, чтобы оценивать вакансии</p>
        <div id="jh-gate-auth"></div>
      </div>
    `
  }
  const authEl = shadowRoot!.getElementById('jh-gate-auth')
  if (authEl) {
    renderAuthSection(authEl, authSectionState, { onLogin: handleGateLogin, onLogout: () => {} })
  }
}

/** Зелёная точка — токен сохранён и активен; жёлтая — входа нет. */
function syncSettingsDot() {
  settingsDotEl?.classList.toggle('ok', authed)
}

// ── Кнопка «Аккаунт» в баре: статус + «Выйти», не трогая панель текущего адаптера ──

function renderAccountPanel() {
  if (!accountEl || !settingsBtn || !panelEl || !barActionsEl) return
  settingsBtn.classList.toggle('active', accountPanelOpen)
  accountEl.classList.toggle('hidden', !accountPanelOpen)
  // «Аккаунт» заменяет интерфейс панели, а не растёт отдельной карточкой под ней —
  // иначе окно вытягивалось вверх за пределы экрана. Панель и действия адаптера
  // прячем на время, по «Вернуться» показываем обратно.
  panelEl.classList.toggle('jh-panel-suspended', accountPanelOpen)
  barActionsEl.classList.toggle('jh-bar-actions-suspended', accountPanelOpen)
  // Адаптеры слушают это событие, чтобы обновить видимость своих кнопок в баре.
  try {
    document.dispatchEvent(new CustomEvent('jh-account-toggle'))
  } catch {
    /* вне DOM-окружения (тесты) — не критично */
  }
  if (!accountPanelOpen) {
    accountEl.innerHTML = ''
    return
  }
  accountEl.innerHTML = `
    <div class="jh-account-head">
      <div class="jh-account-title">${iconMarkup('user', { size: 14 })}<span>Аккаунт</span></div>
      <button type="button" class="jh-account-back" id="jh-account-back">
        ${iconMarkup('arrow-left', { size: 14 })}<span>Вернуться</span>
      </button>
    </div>
    <div class="jh-account-body" id="jh-account-body"></div>
  `
  const body = accountEl.querySelector('#jh-account-body') as HTMLElement | null
  if (body) {
    renderAuthSection(body, authSectionState, { onLogin: () => {}, onLogout: handleAccountLogout })
  }
  accountEl.querySelector('#jh-account-back')?.addEventListener('click', closeAccountPanel)
}

async function handleAccountLogout(): Promise<void> {
  await clearStoredAuthToken()
  await clearAccountScopedStorage()
  accountPanelOpen = false
  authed = false
  authSectionState = { status: null, checking: false, error: null, pending: false }
  if (currentAdapter?.teardown) {
    try {
      currentAdapter.teardown(getSlots())
    } catch (err) {
      console.warn('[Job Hunter] dock teardown (logout):', err)
    }
  }
  currentAdapter = null
  resetSlots()
  renderAccountPanel()
  renderGate()
}

function getSlots(): DockSlots {
  return {
    shadowRoot: shadowRoot!,
    panelEl: panelEl!,
    toastEl: toastEl!,
    toolbarEl: toolbarEl!,
    barActionsEl: barActionsEl!,
    get accountOpen() {
      return isAccountOpen()
    },
    closeAccount: closeAccountPanel,
  }
}

function showToast(_message: string, _durationMs = 6000) {
  // Тосты под доком отключены — не перекрывают тулбар и не дублируют статус в панели.
  if (!toastEl) return
  toastEl.classList.add('hidden')
  toastEl.innerHTML = ''
}

function resetSlots() {
  panelEl!.className = 'jh-panel hidden'
  panelEl!.innerHTML = ''
  panelEl!.removeAttribute('aria-label')
  panelEl!.removeAttribute('role')
  panelEl!.removeAttribute('tabindex')
  toastEl!.className = 'jh-toast hidden'
  toastEl!.innerHTML = ''
  toolbarEl!.className = 'jh-toolbar'
  toolbarEl!.innerHTML = ''
  barActionsEl!.className = 'jh-bar-actions'
  barActionsEl!.innerHTML = ''
}

function pickAdapter(route: SiteRoute) {
  if (!route.site) return null
  for (const adapter of registeredAdapters) {
    if (adapter.matches(route)) return adapter
  }
  return null
}

function route() {
  const siteRoute = resolveRoute()
  if (!siteRoute.site) return

  ensureShell()
  ensureAuthGateStarted()
  if (!authed) return

  const urlChanged = location.href !== lastUrl
  lastUrl = location.href

  const next = pickAdapter(siteRoute)

  if (next !== currentAdapter) {
    if (currentAdapter?.teardown) {
      try {
        currentAdapter.teardown(getSlots())
      } catch (err) {
        console.warn('[Job Hunter] dock teardown:', err)
      }
    }
    resetSlots()
    rootEl!.classList.toggle('jh-lifted', Boolean(next?.liftForHhChat))
    currentAdapter = next
    if (next) {
      try {
        next.mount(getSlots())
      } catch (err) {
        console.warn('[Job Hunter] dock mount:', err)
      }
    }
    return
  }

  if (currentAdapter?.onNavigate) {
    try {
      currentAdapter.onNavigate(getSlots(), { urlChanged, route: siteRoute })
    } catch (err) {
      console.warn('[Job Hunter] dock onNavigate:', err)
    }
  }
}

function bootDock(adapters: DockAdapter[]) {
  registeredAdapters = adapters
  route()

  const observer = new MutationObserver(() => route())
  observer.observe(document.documentElement, { childList: true, subtree: true })

  window.addEventListener('popstate', route)
}

export { bootDock, showToast }
export type { DockAdapter, DockSlots, SiteRoute }
