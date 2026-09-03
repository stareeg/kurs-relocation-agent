import { GETMATCH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import {
  parseGetmatchCatalogCardsFromDom,
  waitForCatalogCards,
} from '../dom/selectors-getmatch-catalog'
import { iconMarkup } from '../ui/icons'
import { loadConfig, DEFAULT_WEB_BASE_URL } from '../config'
import { reportParseHealth } from '../parse-health'
import { getScoreRecords, applyRecommendationFlags } from './vacancy-flags'

/**
 * GM-5.2: каталог getmatch.ru/vacancies — счётчик «N вакансий · M в системе» + ссылка на доску.
 * Без массового автоскоринга (как hh serp.ts). Клик по вакансии → страница GM-5 (vacancy adapter).
 */

let cachedConfig: Awaited<ReturnType<typeof loadConfig>> | null = null
let debounceTimer: ReturnType<typeof setTimeout> | null = null

async function ensureConfig() {
  if (!cachedConfig) cachedConfig = await loadConfig()
  return cachedConfig
}

async function parseWithRetry(): Promise<ReturnType<typeof parseGetmatchCatalogCardsFromDom>> {
  let items = parseGetmatchCatalogCardsFromDom(document)
  if (items.length > 0) return items

  // Повторная попытка через ожидание DOM — страница могла ещё не загрузить карточки.
  await waitForCatalogCards(5000)
  return parseGetmatchCatalogCardsFromDom(document)
}

function buildToolbarHtml(label: string, recBadge: string): string {
  return `
    <button type="button" class="jh-btn-expand" id="jh-gm-catalog-btn" title="Открыть доску вакансий в вебе">
      ${iconMarkup('sparkles', { size: 14 })}<span>${label}</span>${recBadge}
    </button>
  `
}

function openJobs(url: string) {
  window.open(url, '_blank', 'noopener')
}

function bindCatalogButton(slots: { shadowRoot: ShadowRoot }) {
  const btn = slots.shadowRoot.getElementById('jh-gm-catalog-btn')
  btn?.addEventListener('click', async () => {
    const cfg = await ensureConfig()
    openJobs(`${cfg.webBaseUrl || DEFAULT_WEB_BASE_URL}/jobs?period=all`)
  })
  const badge = slots.shadowRoot.getElementById('jh-gm-catalog-rec-badge')
  badge?.addEventListener('click', async (e) => {
    e.stopPropagation()
    const cfg = await ensureConfig()
    openJobs(`${cfg.webBaseUrl || DEFAULT_WEB_BASE_URL}/jobs?recommended=1&period=all`)
  })
}

async function renderCounter(slots: {
  shadowRoot: ShadowRoot
  toolbarEl: HTMLElement
}) {
  const items = await parseWithRetry()
  const ids = items.map((i) => i.vacancy_id).filter(Boolean)

  if (!ids.length) {
    reportParseHealth({ site: 'getmatch', page: 'catalog', reason: 'zero_cards' })
    slots.toolbarEl.innerHTML = buildToolbarHtml('getmatch · каталог', '')
    bindCatalogButton(slots)
    return
  }

  const records = await getScoreRecords(ids)
  applyRecommendationFlags(items, records)
  const known = Object.keys(records).length

  // Подсчёт рекомендованных (strong_apply / apply).
  const recommended = Object.values(records).filter(
    (r: any) => r?.score?.recommendation === 'strong_apply' || r?.score?.recommendation === 'apply',
  ).length

  const catalogLabel = known
    ? `${ids.length} вакансий · ${known} в системе`
    : `${ids.length} вакансий`

  const recBadge = recommended > 0
    ? ` <span class="jh-gm-catalog-rec-badge" id="jh-gm-catalog-rec-badge">${recommended} рекомендовано</span>`
    : ''

  slots.toolbarEl.innerHTML = buildToolbarHtml(catalogLabel, recBadge)
  bindCatalogButton(slots)
}

function scheduleRender(slots: Parameters<typeof renderCounter>[0]) {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => void renderCounter(slots), 1200)
}

function mount(slots: Parameters<typeof renderCounter>[0]) {
  void renderCounter(slots)
}

function onNavigate(
  slots: Parameters<typeof renderCounter>[0],
  ctx: { urlChanged: boolean },
) {
  if (ctx.urlChanged) {
    void renderCounter(slots)
    return
  }
  scheduleRender(slots)
}

function teardown() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = null
}

const getmatchCatalogAdapter = {
  key: 'getmatch-catalog',
  matches: (route: SiteRoute) =>
    route.site === 'getmatch' && route.pageType === GETMATCH_PAGE_TYPE.CATALOG,
  mount,
  onNavigate,
  teardown,
}

export { getmatchCatalogAdapter }
