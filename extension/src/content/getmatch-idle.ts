import { GETMATCH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'

import { iconMarkup } from '../ui/icons'

import { loadConfig, DEFAULT_WEB_BASE_URL } from '../config'



/**

 * GM-4/GM-5: catch-all getmatch.ru (profile/other) — не vacancy/applications/catalog/stats.

 */



let cachedConfig: Awaited<ReturnType<typeof loadConfig>> | null = null



async function ensureConfig() {

  if (!cachedConfig) cachedConfig = await loadConfig()

  return cachedConfig

}



function mount(slots: {

  shadowRoot: ShadowRoot

  toolbarEl: HTMLElement

}) {

  slots.toolbarEl.innerHTML = `

    <button type="button" class="jh-btn-expand" id="jh-gm-idle-btn" title="Открыть Copilot">

      ${iconMarkup('sparkles', { size: 14 })}<span>Copilot</span>

    </button>

  `

  const btn = slots.shadowRoot.getElementById('jh-gm-idle-btn')

  btn?.addEventListener('click', async () => {

    const cfg = await ensureConfig()

    window.open(cfg.webBaseUrl || DEFAULT_WEB_BASE_URL, '_blank', 'noopener')

  })

}



function matchesGetmatchIdle(route: SiteRoute): boolean {

  if (route.site !== 'getmatch' || !route.pageType) return false

  const t = route.pageType

  // PROFILE теперь у getmatch-profile-page.ts (GM-12/GM-13) — здесь только catch-all OTHER.
  return t === GETMATCH_PAGE_TYPE.OTHER

}



const getmatchIdleAdapter = {

  key: 'getmatch-idle',

  matches: matchesGetmatchIdle,

  mount,

}



export { getmatchIdleAdapter }

