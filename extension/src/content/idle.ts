import { HH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import { iconMarkup } from '../ui/icons'
import { loadConfig, DEFAULT_WEB_BASE_URL } from '../config'

/**
 * Idle-адаптер — employer/other страницы hh.ru, где раньше расширения не было вообще
 * (init() в main.ts просто сносил все виджеты и выходил). Ничего не парсит и не собирает —
 * только бренд-присутствие дока + ссылка «Открыть в вебе»: канбан/чат/метрики — это web,
 * расширение на них только ссылается.
 */

let cachedConfig = null;

async function ensureConfig() {
  if (!cachedConfig) cachedConfig = await loadConfig();
  return cachedConfig;
}

function mount(slots) {
  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand" id="jh-idle-btn" title="Открыть Copilot">
      ${iconMarkup('sparkles', { size: 14 })}<span>Copilot</span>
    </button>
  `;
  const btn = slots.shadowRoot.getElementById('jh-idle-btn');
  btn?.addEventListener('click', async () => {
    const cfg = await ensureConfig();
    window.open(cfg.webBaseUrl || DEFAULT_WEB_BASE_URL, '_blank', 'noopener');
  });
}

const idleAdapter = {
  key: 'idle',
  matches: (route: SiteRoute) =>
    route.site === 'hh' &&
    (route.pageType === HH_PAGE_TYPE.EMPLOYER || route.pageType === HH_PAGE_TYPE.OTHER),
  mount,
}

export { idleAdapter };
