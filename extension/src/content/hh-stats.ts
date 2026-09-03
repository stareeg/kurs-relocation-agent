import { isStatsPage, parseMarketIndexFromDom } from '../dom/selectors'
import { HH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import { waitForCondition } from '../dom/wait-for-condition'
import { iconMarkup } from '../ui/icons'

/**
 * E-03: индекс рынка «резюме на вакансию» со страницы stats.hh.ru — тихий съём, если владелец её
 * открыл (план market_redesign_v3, п.2.6.3): без единого серверного запроса к hh, читаем только
 * то, что уже отрисовано в его браузере. Единственный путь получения индекса (правка 2026-08-04
 * убрала ручной ввод из «Параметров» — поле легко читается со страницы, дублировать его руками
 * незачем); нет визита на stats.hh.ru — индекс просто пуст на «Рынке».
 *
 * Идемпотентность — upsert по месяцу на бэке; здесь только сигнатурный гард, чтобы не слать одно
 * и то же значение на каждый ререндер SPA за визит (тот же приём, что serp.ts/resumes.ts).
 */

const STATS_BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 13 })}<span>Copilot</span></div>`;

let statsPanelEl = null;
let statsExpandBtn = null;
let statsCollapsed = false;
let statsSentSig = '';
let statsInFlight = false;

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id);
  } catch {
    return false;
  }
}

function statsEscapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function statsSendMessage(message): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено - обновите страницу (F5)' });
      return;
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response);
      });
    } catch (err) {
      resolve({ ok: false, error: String(err.message || err) });
    }
  });
}

function statsCollapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="stats-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`;
}

function bindStatsHeaderActions() {
  const collapseBtn = statsPanelEl?.querySelector('[data-action="stats-collapse"]');
  if (collapseBtn) collapseBtn.addEventListener('click', onStatsCollapseClick);
  statsPanelEl?.classList.toggle('hidden', statsCollapsed);
}

function onStatsCollapseClick() {
  statsCollapsed = true;
  statsPanelEl.classList.add('hidden');
  if (statsExpandBtn) statsExpandBtn.classList.remove('hidden');
}

function onStatsExpandClick() {
  statsCollapsed = false;
  statsPanelEl.classList.remove('hidden');
  if (statsExpandBtn) statsExpandBtn.classList.add('hidden');
}

function statsStatusLine(message) {
  return `${iconMarkup('circle-check', { size: 13 })} ${statsEscapeHtml(message)}`;
}

function ensureStatsUi(slots) {
  statsPanelEl = slots.panelEl;
  statsPanelEl.classList.add('jh-res-panel');
  statsPanelEl.classList.remove('hidden');
  statsCollapsed = false;

  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-stats-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
  `;
  statsExpandBtn = slots.shadowRoot.getElementById('jh-stats-expand-btn');
  statsExpandBtn.addEventListener('click', onStatsExpandClick);

  renderStatsPanelLoading();
}

function teardownStatsUi() {
  statsPanelEl = null;
  statsExpandBtn = null;
  statsCollapsed = false;
}

function renderStatsPanelLoading() {
  if (!statsPanelEl) return;
  statsPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${STATS_BRAND_HTML}<strong>Индекс рынка</strong></div>
    </div>
    <div class="jh-body"><p class="jh-funnel-hint">Читаю hh.индекс…</p></div>
  `;
  bindStatsHeaderActions();
}

function renderStatsPanel(value, statusHtml) {
  if (!statsPanelEl) return;
  if (value == null) {
    statsPanelEl.innerHTML = `
      <div class="jh-header">
        <div class="jh-header-main">${STATS_BRAND_HTML}<strong>Индекс рынка</strong></div>
        ${statsCollapseBtnHtml()}
      </div>
      <div class="jh-body"><p class="jh-funnel-hint">Блок «hh.индекс» на странице не найден.</p></div>
    `;
    bindStatsHeaderActions();
    return;
  }
  statsPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${STATS_BRAND_HTML}<strong>Индекс рынка</strong></div>
      ${statsCollapseBtnHtml()}
    </div>
    <div class="jh-body">
      <div class="jh-metrics" style="grid-template-columns:repeat(1,1fr)">
        <div class="jh-metric">
          <div class="jh-metric-head">${iconMarkup('target', { size: 14 })}<span class="jh-metric-label">Резюме на вакансию</span></div>
          <div class="jh-metric-value">${statsEscapeHtml(String(value))}</div>
        </div>
      </div>
      ${statusHtml ? `<p class="jh-funnel-hint jh-res-status">${statusHtml}</p>` : ''}
    </div>
  `;
  bindStatsHeaderActions();
}

/** Ждём, пока SPA дорисует бейдж «hh.индекс» (после document_idle). null — не дождались. */
async function waitForMarketIndex() {
  return waitForCondition(() => parseMarketIndexFromDom(document), {
    timeoutMs: 8000,
    shouldCancel: () => !isExtensionAlive() || !isStatsPage(),
  });
}

async function initStatsPage() {
  if (statsInFlight) return;
  statsInFlight = true;
  try {
    const parsed = await waitForMarketIndex();
    if (!parsed) {
      renderStatsPanel(null, '');
      return;
    }
    renderStatsPanel(parsed.value, '');
    const sig = String(parsed.value);
    if (sig === statsSentSig) {
      renderStatsPanel(parsed.value, statsStatusLine('Уже отправлено в этот визит'));
      return;
    }

    const response = await statsSendMessage({
      action: 'marketIndex',
      payload: { value: parsed.value, source: 'hh_stats' },
    });
    if (!response?.ok) {
      console.warn('Job Hunter: market-index не отправлен:', response?.error);
      renderStatsPanel(
        parsed.value,
        `<span class="jh-res-delta down">Не сохранено: ${statsEscapeHtml(response?.error || 'нет связи с бэкендом')}</span>`,
      );
      return;
    }
    statsSentSig = sig;
    if (response.data?.persisted === false) {
      renderStatsPanel(parsed.value, 'Бэкенд без БД - не сохранено');
      return;
    }
    renderStatsPanel(parsed.value, statsStatusLine(`Зона: ${response.data?.zone || '—'}`));
  } catch (err) {
    console.warn('Job Hunter: market-index', err);
  } finally {
    statsInFlight = false;
  }
}

function mountStatsAdapter(slots) {
  ensureStatsUi(slots);
  void initStatsPage();
}

function onStatsNavigate(_slots, ctx) {
  if (!ctx.urlChanged) return;
  void initStatsPage();
}

const hhStatsAdapter = {
  key: 'hh-stats',
  matches: (route: SiteRoute) => route.site === 'hh' && route.pageType === HH_PAGE_TYPE.STATS_INDEX,
  mount: mountStatsAdapter,
  onNavigate: onStatsNavigate,
  teardown: teardownStatsUi,
}

export { hhStatsAdapter };
