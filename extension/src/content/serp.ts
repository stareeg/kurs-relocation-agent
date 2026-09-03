import { HH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import { parseSerpDemandFromDom } from '../dom/selectors'
import { parseSerpListingFromDom } from '../dom/serp-json'
import { iconMarkup } from '../ui/icons'
import { loadConfig, DEFAULT_WEB_BASE_URL } from '../config'
import { reportParseHealth } from '../parse-health'
import { getSelectors } from '../dom/selectors-config'
import { getScoreRecords, applyRecommendationFlags } from './vacancy-flags'

/**
 * EX-7: SERP/рекомендованное — раньше расширения тут не было вообще, хотя парсер карточек
 * (`parseSerpCardsFromDom`) был написан ещё при портировании legacy autosend-проекта и просто
 * нигде не подключался. Счётчик — локальный кэш `chrome.storage.local` (ключи
 * `score:{vacancy_id}`), без нового backend-вызова. Список id: embedded JSON из уже
 * загруженного документа → DOM по конфигу → DOM по дефолтам. Новый запрос к hh не делаем.
 *
 * E-01: тем же заходом на выдачу тихо шлём показание спроса (`parseSerpDemandFromDom` →
 * POST /api/market/demand через background) — план market_redesign_v3 п.2.6.1. Идемпотентность
 * дневная на бэке (upsert по день+запрос+источник); здесь только сигнатурный гард поверх неё,
 * чтобы не слать одно и то же показание на каждый дебаунс-ререндер за визит (по образцу
 * resumes.ts).
 */

let cachedConfig = null;
let debounceTimer = null;
let demandSentSig = '';

async function ensureConfig() {
  if (!cachedConfig) cachedConfig = await loadConfig();
  return cachedConfig;
}

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id);
  } catch {
    return false;
  }
}

/** Тихая отправка показания спроса — не блокирует и не портит счётчик карточек при ошибке. */
async function sendDemandSignal() {
  if (!isExtensionAlive()) return;
  const demand = parseSerpDemandFromDom(document);
  if (!demand) return;
  const sig = `${demand.query}|${demand.count}`;
  if (sig === demandSentSig) return;
  demandSentSig = sig; // до ответа бэка — повторный дебаунс-ререндер не должен слать дубль

  try {
    await new Promise((resolve) => {
      chrome.runtime.sendMessage({ action: 'marketDemand', payload: demand }, (response: any) => {
        if (chrome.runtime.lastError || !response?.ok) {
          demandSentSig = ''; // не отправилось — дать следующему рендеру повторить попытку
        }
        resolve(undefined);
      });
    });
  } catch {
    demandSentSig = '';
  }
}

async function renderCounter(slots) {
  void sendDemandSignal();

  const { items, method } = parseSerpListingFromDom(document);
  const ids = items.map((i) => i.vacancy_id).filter(Boolean);

  if (!ids.length) {
    // После debounce (onNavigate) — либо пустая выдача, либо умерли селекторы (FR2-71).
    const pack = getSelectors();
    reportParseHealth({
      site: 'hh',
      page: 'serp',
      reason: 'zero_cards',
      method: method ?? undefined,
      config_version: pack.version,
      config_origin: pack.origin,
    });
    slots.toolbarEl.innerHTML = '';
    return;
  }

  const records = await getScoreRecords(ids);
  applyRecommendationFlags(items, records);
  const known = Object.keys(records).length;
  const label = known ? `${ids.length} вакансий · ${known} в системе` : `${ids.length} вакансий`;

  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand" id="jh-serp-btn" title="Открыть доску вакансий в вебе">
      ${iconMarkup('sparkles', { size: 14 })}<span>${label}</span>
    </button>
  `;
  const btn = slots.shadowRoot.getElementById('jh-serp-btn');
  btn?.addEventListener('click', async () => {
    const cfg = await ensureConfig();
    window.open(`${cfg.webBaseUrl || DEFAULT_WEB_BASE_URL}/jobs`, '_blank', 'noopener');
  });
}

function scheduleRender(slots) {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void renderCounter(slots), 1200);
}

function mount(slots) {
  void renderCounter(slots);
}

/** SERP мутирует DOM часто (ленивая подгрузка, чипы) — на «просто мутацию» дебаунсим переразбор,
 *  на реальную смену URL (пагинация/новый запрос) перечитываем сразу. */
function onNavigate(slots, ctx) {
  if (ctx.urlChanged) {
    void renderCounter(slots);
    return;
  }
  scheduleRender(slots);
}

function teardown() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
}

const serpAdapter = {
  key: 'serp',
  matches: (route: SiteRoute) =>
    route.site === 'hh' &&
    (route.pageType === HH_PAGE_TYPE.SEARCH ||
      route.pageType === HH_PAGE_TYPE.VACANCIES),
  mount,
  onNavigate,
  teardown,
}

export { serpAdapter };
