import {
  getHhPageType,
  isResumesPage,
  isResumeHistoryPage,
  parseResumeStatsFromDom,
  parseResumeViewHistoryFromDom,
} from '../dom/selectors'
import { HH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import { waitForCondition } from '../dom/wait-for-condition'
import { iconMarkup } from '../ui/icons'

/**
 * AF-2: тихий сбор статистики резюме на hh (`/applicant/resumes` легаси, `/applicant/profile/me`
 * актуальная вёрстка — hh 2026-07, `/applicant/resumeview/history`). На заходе парсим публичные
 * счётчики/историю и шлём на бэк
 * (AF-1) с таймстемпом — копится динамика отклика рынка. Без кнопки, ненавязчиво: маленькое
 * подтверждение в shadow-панели. Роутинг — из content/main.ts (init на навигации).
 *
 * Дроссель повторов: на бэке дневная идемпотентность снимка + дедуп строк истории; здесь ещё
 * сигнатурный гард, чтобы не слать один и тот же снимок несколько раз за визит.
 */

const RES_BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 13 })}<span>Copilot</span></div>`;

let resShadowRoot = null;
let resPanelEl = null;
let resToastEl = null;
let resToastTimer = null;
let resExpandBtn = null;
/** Свёрнута ли панель (как на странице вакансии) — сбрасывается при каждом mount адаптера. */
let resCollapsed = false;
/** Сигнатуры уже отправленных снимка/истории за визит (анти-спам поверх бэкенд-дедупа). */
let resSentStatsSig = '';
let resSentHistorySig = '';
let resStatsInFlight = false;
let resHistoryInFlight = false;

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id);
  } catch {
    return false;
  }
}

function resDelay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resEscapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function resSendMessage(message): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено - обновите страницу hh.ru (F5)' });
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

// EX-7: точка монтирования в общий док (dock.ts владеет shadow-host/panel/toast/toolbar). Панель
// резюме — снимаем базовый `hidden`, который выставляет dock между переключениями адаптеров;
// сворачивается кнопкой в шапке, как панель на странице вакансии (см. resCollapseBtnHtml).
function ensureResumesUi(slots) {
  resShadowRoot = slots.shadowRoot;
  resPanelEl = slots.panelEl;
  resPanelEl.classList.add('jh-res-panel');
  resPanelEl.classList.remove('hidden');
  resToastEl = slots.toastEl;
  resCollapsed = false;

  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-res-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
  `;
  resExpandBtn = resShadowRoot.getElementById('jh-res-expand-btn');
  resExpandBtn.addEventListener('click', onResExpandClick);

  renderResumePanelLoading();
}

function teardownResumesUi() {
  resShadowRoot = null;
  resPanelEl = null;
  resToastEl = null;
  resExpandBtn = null;
  resCollapsed = false;
  clearTimeout(resToastTimer);
}

function onResCollapseClick() {
  resCollapsed = true;
  resPanelEl.classList.add('hidden');
  if (resExpandBtn) resExpandBtn.classList.remove('hidden');
}

function onResExpandClick() {
  resCollapsed = false;
  resPanelEl.classList.remove('hidden');
  if (resExpandBtn) resExpandBtn.classList.add('hidden');
}

/** Кнопка «Свернуть» в шапке панели — переиспользуется во всех трёх состояниях рендера. */
function resCollapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="res-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`;
}

/** Навешивает клик на кнопку «Свернуть» — вызывается после каждого re-render (innerHTML
 *  полностью пересобирается, старый listener теряется вместе со старым узлом). */
function bindResHeaderActions() {
  const collapseBtn = resPanelEl?.querySelector('[data-action="res-collapse"]');
  if (collapseBtn) collapseBtn.addEventListener('click', onResCollapseClick);
  resPanelEl?.classList.toggle('hidden', resCollapsed);
}

/** Ячейка метрики с опциональной недельной дельтой (стрелка вверх/вниз пастелью). */
function resMetric(icon, label, value, delta) {
  let deltaHtml = '';
  if (typeof delta === 'number' && delta !== 0) {
    const cls = delta > 0 ? 'up' : 'down';
    const sign = delta > 0 ? '+' : '';
    deltaHtml = ` <span class="jh-res-delta ${cls}">${sign}${delta}</span>`;
  }
  const shown = value == null || value === '' ? '—' : resEscapeHtml(String(value));
  return `
    <div class="jh-metric">
      <div class="jh-metric-head">${iconMarkup(icon, { size: 14 })}<span class="jh-metric-label">${resEscapeHtml(label)}</span></div>
      <div class="jh-metric-value">${shown}${deltaHtml}</div>
    </div>`;
}

function renderResumePanelLoading() {
  if (!resPanelEl) return;
  resPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${RES_BRAND_HTML}<strong>Статистика резюме</strong></div>
      ${resCollapseBtnHtml()}
    </div>
    <div class="jh-body"><p class="jh-funnel-hint">Читаю статистику резюме…</p></div>
  `;
  bindResHeaderActions();
}

/** Панель статистики резюме: показы/просмотры/приглашения + дельты + строка статуса записи. */
function renderResumePanel(stats, statusHtml) {
  if (!resPanelEl) return;
  if (!stats) {
    resPanelEl.innerHTML = `
      <div class="jh-header">
        <div class="jh-header-main">${RES_BRAND_HTML}<strong>Статистика резюме</strong></div>
        ${resCollapseBtnHtml()}
      </div>
      <div class="jh-body"><p class="jh-funnel-hint">Блок статистики на странице не найден. Обновите (F5) или откройте резюме со счётчиками.</p></div>
    `;
    bindResHeaderActions();
    return;
  }
  resPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">
        ${RES_BRAND_HTML}<strong>Статистика резюме</strong>
        <span class="jh-neg-page-badge">за неделю</span>
      </div>
      ${resCollapseBtnHtml()}
    </div>
    <div class="jh-body">
      <div class="jh-metrics" style="grid-template-columns:repeat(2,1fr)">
        ${resMetric('target', 'Показы', stats.impressions, null)}
        ${resMetric('users', 'Просмотры', stats.views, stats.views_delta)}
        ${resMetric('mail', 'Приглашения', stats.invitations, stats.invitations_delta)}
        ${resMetric('clipboard-list', 'Рекомендовано', stats.recommended_vacancies, null)}
      </div>
      ${statusHtml ? `<p class="jh-funnel-hint jh-res-status">${statusHtml}</p>` : ''}
    </div>
  `;
  bindResHeaderActions();
}

/** Компактная панель страницы истории просмотров (число строк + статус записи). */
function renderHistoryPanel(rowsCount, statusHtml) {
  if (!resPanelEl) return;
  resPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">${RES_BRAND_HTML}<strong>Просмотры резюме</strong></div>
      ${resCollapseBtnHtml()}
    </div>
    <div class="jh-body">
      <div class="jh-metrics" style="grid-template-columns:repeat(1,1fr)">
        ${resMetric('users', 'Строк истории', rowsCount, null)}
      </div>
      ${statusHtml ? `<p class="jh-funnel-hint jh-res-status">${statusHtml}</p>` : ''}
    </div>
  `;
  bindResHeaderActions();
}

function resStatusLine(message) {
  return `${iconMarkup('circle-check', { size: 13 })} ${resEscapeHtml(message)}`;
}

/** Деликатное подтверждение «снимок записан» (auto-hide). */
function showResumeToast(message) {
  if (!resToastEl) return;
  resToastEl.innerHTML =
    `<span class="jh-toast-msg">${iconMarkup('circle-check', { size: 14 })}<span>${resEscapeHtml(message)}</span></span>`;
  resToastEl.classList.remove('hidden');
  clearTimeout(resToastTimer);
  resToastTimer = setTimeout(() => {
    if (resToastEl) {
      resToastEl.classList.add('hidden');
      resToastEl.innerHTML = '';
    }
  }, 4000);
}

/**
 * Ждём, пока SPA дорисует блок статистики (после document_idle). null — не дождались.
 *
 * Блок «Статистика за неделю» и кнопка рекомендаций рендерятся НЕ одновременно (рекомендации —
 * отдельный персонализированный виджет, догружается позже, текст в кнопке появляется не сразу
 * после её монтирования). Раньше цикл выходил, как только находил ЛЮБОЕ из полей
 * (`parseResumeStatsFromDom` возвращает объект уже при первом совпадении) — статистика успевала
 * отрисоваться раньше рекомендаций, и `recommended_vacancies` навсегда улетал в БД нулём. Теперь
 * ждём, пока число рекомендаций реально распарсится (> 0) — либо до дедлайна, тогда отдаём
 * последний известный снимок как есть (честный 0, если блока правда нет).
 *
 * EXT-F3: ожидание — через MutationObserver (`waitForCondition`), не fixed-interval poll —
 * резолвится на реальном DOM-изменении, дедлайн остаётся safety net'ом.
 */
async function waitForResumeStats() {
  return waitForCondition(() => parseResumeStatsFromDom(document), {
    timeoutMs: 6000,
    shouldCancel: () => !isExtensionAlive() || !isResumesPage(),
    isAcceptable: (stats) => !!stats && stats.recommended_vacancies > 0,
  });
}

async function waitForResumeHistory() {
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    if (!isExtensionAlive() || !isResumeHistoryPage()) return null;
    const data = parseResumeViewHistoryFromDom(document);
    if (data.rows.length) return data;
    await resDelay(300);
  }
  return parseResumeViewHistoryFromDom(document);
}

async function initResumesPage() {
  if (resStatsInFlight) return;
  resStatsInFlight = true;
  try {
    const stats = await waitForResumeStats();
    if (!stats) {
      renderResumePanel(null, ''); // нет блока статистики — видимая подсказка в панели
      return;
    }
    renderResumePanel(stats, ''); // показываем цифры сразу, до ответа бэка
    const sig = `${stats.resume_id}|${stats.impressions}|${stats.views}|${stats.invitations}|${stats.recommended_vacancies}`;
    if (sig === resSentStatsSig) {
      renderResumePanel(stats, resStatusLine('Уже отправлено в этот визит'));
      return;
    }

    const response = await resSendMessage({ action: 'resumeStats', payload: stats });
    if (!response?.ok) {
      console.warn('Job Hunter: resume-stats не отправлены:', response?.error);
      renderResumePanel(
        stats,
        `<span class="jh-res-delta down">Не сохранено: ${resEscapeHtml(response?.error || 'нет связи с бэкендом')}</span>`
      );
      return;
    }
    resSentStatsSig = sig;
    if (response.data?.persisted === false) {
      renderResumePanel(stats, 'Бэкенд без БД - снимок не сохранён');
      return;
    }
    const written = Boolean(response.data?.inserted);
    renderResumePanel(stats, resStatusLine(written ? 'Снимок записан' : 'Уже зафиксировано сегодня'));
    showResumeToast(
      written
        ? 'Снимок статистики резюме записан'
        : 'Статистика резюме уже зафиксирована сегодня'
    );
  } catch (err) {
    console.warn('Job Hunter: resume-stats', err);
  } finally {
    resStatsInFlight = false;
  }
}

async function initResumeHistoryPage() {
  if (resHistoryInFlight) return;
  resHistoryInFlight = true;
  try {
    const data = await waitForResumeHistory();
    if (!data || !data.rows.length) {
      renderHistoryPanel(0, 'Строк истории не найдено');
      return;
    }
    renderHistoryPanel(data.rows.length, '');
    const last = data.rows[data.rows.length - 1];
    const sig = `${data.resume_id}|${data.rows.length}|${data.rows[0]?.viewed_at || ''}|${last?.viewed_at || ''}`;
    if (sig === resSentHistorySig) {
      renderHistoryPanel(data.rows.length, resStatusLine('Уже отправлено в этот визит'));
      return;
    }

    const response = await resSendMessage({ action: 'resumeViews', payload: data });
    if (!response?.ok) {
      console.warn('Job Hunter: resume-views не отправлены:', response?.error);
      renderHistoryPanel(
        data.rows.length,
        `<span class="jh-res-delta down">Не сохранено: ${resEscapeHtml(response?.error || 'нет связи с бэкендом')}</span>`
      );
      return;
    }
    resSentHistorySig = sig;
    if (response.data?.persisted === false) {
      renderHistoryPanel(data.rows.length, 'Бэкенд без БД - не сохранено');
      return;
    }
    const inserted = response.data?.inserted ?? 0;
    renderHistoryPanel(
      data.rows.length,
      resStatusLine(inserted > 0 ? `+${inserted} новых строк` : 'Без новых строк')
    );
    showResumeToast(
      inserted > 0
        ? `История просмотров: +${inserted} ${inserted === 1 ? 'строка' : 'строк'}`
        : 'История просмотров без новых строк'
    );
  } catch (err) {
    console.warn('Job Hunter: resume-views', err);
  } finally {
    resHistoryInFlight = false;
  }
}

/** Запускает нужную ветку (счётчики/история) по актуальному под-типу страницы. */
function runForCurrentSubtype() {
  const pageType = getHhPageType();
  if (pageType === HH_PAGE_TYPE.RESUMES) void initResumesPage();
  else if (pageType === HH_PAGE_TYPE.RESUME_HISTORY) void initResumeHistoryPage();
}

function mountResumesAdapter(slots) {
  ensureResumesUi(slots);
  runForCurrentSubtype();
}

/** Оба под-типа (счётчики/история) матчит один адаптер — переключение между ними внутри dock не
 *  считается сменой адаптера (mount не перевызывается), поэтому на смену URL перепроверяем сами. */
function onResumesNavigate(_slots, ctx) {
  if (!ctx.urlChanged) return;
  runForCurrentSubtype();
}

const resumesAdapter = {
  key: 'resumes',
  matches: (route: SiteRoute) =>
    route.site === 'hh' &&
    (route.pageType === HH_PAGE_TYPE.RESUMES ||
      route.pageType === HH_PAGE_TYPE.RESUME_HISTORY),
  mount: mountResumesAdapter,
  onNavigate: onResumesNavigate,
  teardown: teardownResumesUi,
  liftForHhChat: true,
}

export { resumesAdapter }
