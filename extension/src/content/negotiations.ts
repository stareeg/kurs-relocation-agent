import {
  negotiationsPageKey,
  getNegotiationsPageIndex,
} from '../dom/selectors'
import { HH_PAGE_TYPE, getHhPageType, type SiteRoute } from '../dom/site-router'
import { iconMarkup } from '../ui/icons'
import {
  isAutoSyncCandidate,
  negotiationsPayloadItem,
  parseNegotiationsFromRoot,
  fetchNegotiationsPreview,
  applySync,
} from './negotiations-sync'

/** Бренд-строка панели — единый язык с web (Copilot + sparkles, не «JOB HUNTER» капс). */
const NEG_BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 13 })}<span>Copilot</span></div>`;

/**
 * UI на hh.ru/applicant/negotiations — синхронизация откликов с Job Hunter.
 * Пагинация (?page=N) — только перепарсинг DOM, без сброса пайплайна.
 */

/** false после Reload расширения на уже открытых вкладках hh.ru */
function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id);
  } catch {
    return false;
  }
}

let negShadowRoot = null;
let negPanelEl = null;
let negSyncAllBtn = null;
let negExpandBtn = null;
let negParsedItems = [];
let negSyncing = false;
/** Свёрнута ли панель (как на странице вакансии) — сбрасывается при каждом mount адаптера. */
let negCollapsed = false;
/** @type {{ done: number, total: number, message: string } | null} */
let negSyncProgress = null;
let negLastPageKey = negotiationsPageKey(location.href);
let negDomRefreshTimer = null;
let negLastPreviewKey = '';
let negPreviewError = '';
/** Страница, на которой уже отработал авто-перенос (раз на страницу, не на каждый DOM-рефреш). */
let negAutoSyncedKey = '';

function negEscapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function negSendMessage(message): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено — обновите страницу hh.ru (F5)' });
      return;
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        try {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
            return;
          }
          resolve(response);
        } catch (err) {
          resolve({ ok: false, error: String(err.message || err) });
        }
      });
    } catch (err) {
      resolve({ ok: false, error: String(err.message || err) });
    }
  });
}

function negotiationsPageLabel() {
  const pageNum = getNegotiationsPageIndex() + 1;
  const count = negParsedItems.length;
  return `стр. ${pageNum}${count ? ` · ${count} откликов` : ''}`;
}

function sortNegotiationItems(items) {
  return [...items].sort((a, b) => {
    const aSynced = a.sync_state === 'synced' ? 1 : 0;
    const bSynced = b.sync_state === 'synced' ? 1 : 0;
    if (aSynced !== bSynced) return aSynced - bSynced;
    const aDisc = a.is_discrepancy ? 0 : 1;
    const bDisc = b.is_discrepancy ? 0 : 1;
    if (aDisc !== bDisc) return aDisc - bDisc;
    return String(a.vacancy_id).localeCompare(String(b.vacancy_id));
  });
}

/** Один раз на страницу: молча перенести ЛЮБОЕ расхождение (Решение 9 — не только отказы/
 *  приглашения) через LLM-синк, без клика пользователя. force=false → гард бэка защищает от
 *  даунранка активной воронки/оффера; спорные случаи решает LLM (см. negotiations-sync.ts). */
async function maybeAutoSyncDiscrepancies() {
  if (negSyncing || negPreviewError) return; // без надёжного preview не авто-применяем
  const key = negotiationsPageKey();
  if (negAutoSyncedKey === key) return;
  const candidates = negParsedItems.filter(isAutoSyncCandidate);
  negAutoSyncedKey = key;
  if (!candidates.length) return;
  await syncNegotiationItems(candidates, { force: false, auto: true });
}

// EX-7: точка монтирования в общий док (dock.ts владеет shadow-host/panel/toast/toolbar). Панель
// и тулбар — общие узлы, свои классы (`jh-neg-panel`/`jh-neg-toolbar`) добавляем сами, док их снимет
// при переключении на другой адаптер (resetSlots).
function ensureNegotiationsUi(slots) {
  negShadowRoot = slots.shadowRoot;
  negPanelEl = slots.panelEl;
  negPanelEl.classList.add('jh-neg-panel');
  negPanelEl.classList.remove('hidden');
  negCollapsed = false;

  slots.toolbarEl.classList.add('jh-neg-toolbar');
  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-neg-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
    <button type="button" class="jh-btn" id="jh-neg-sync-all-btn">${iconMarkup('refresh-cw', { size: 14 })}<span>Обновить</span></button>
  `;
  negSyncAllBtn = negShadowRoot.getElementById('jh-neg-sync-all-btn');
  negSyncAllBtn.addEventListener('click', onSyncAllDiscrepanciesClick);
  negExpandBtn = negShadowRoot.getElementById('jh-neg-expand-btn');
  negExpandBtn.addEventListener('click', onNegExpandClick);
}

function teardownNegotiationsUi() {
  clearTimeout(negDomRefreshTimer);
  negDomRefreshTimer = null;
  negShadowRoot = null;
  negPanelEl = null;
  negSyncAllBtn = null;
  negExpandBtn = null;
  negParsedItems = [];
  negLastPreviewKey = '';
  negPreviewError = '';
  negAutoSyncedKey = '';
  negCollapsed = false;
}

/** Свернуть панель (как «Свернуть» на странице вакансии) — тулбар остаётся с кнопкой «Развернуть». */
function onNegCollapseClick() {
  negCollapsed = true;
  negPanelEl.classList.add('hidden');
  if (negExpandBtn) negExpandBtn.classList.remove('hidden');
}

function onNegExpandClick() {
  negCollapsed = false;
  negPanelEl.classList.remove('hidden');
  if (negExpandBtn) negExpandBtn.classList.add('hidden');
}

/** Кнопка «Свернуть» в шапке панели — переиспользуется в обоих состояниях рендера. */
function negCollapseBtnHtml() {
  return `<button type="button" class="jh-collapse" data-action="neg-collapse">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>`;
}

function renderSyncProgress(event) {
  if (!event || !negPanelEl) return;
  negSyncProgress = {
    done: event.done ?? 0,
    total: event.total ?? 0,
    message: event.message || '',
    synced: event.synced ?? 0,
    skipped: event.skipped ?? 0,
    phase: event.type,
  };
  let wrap = negShadowRoot.getElementById('jh-neg-progress-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'jh-neg-progress-wrap';
    wrap.className = 'jh-neg-progress-wrap';
    const body = negPanelEl.querySelector('.jh-body');
    if (body) body.prepend(wrap);
  }
  const total = negSyncProgress.total || 1;
  const pct = Math.min(100, Math.round((negSyncProgress.done / total) * 100));
  const quota = event.quota;
  let quotaHint = '';
  if (quota && (quota.cooldown_sec > 0 || quota.writes_used >= quota.writes_limit - 5)) {
    quotaHint = `<span class="jh-neg-quota">Sheets: ${quota.writes_used}/${quota.writes_limit} write</span>`;
  }
  wrap.innerHTML = `
    <div class="jh-neg-progress-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
      <div class="jh-neg-progress-fill" style="width:${pct}%"></div>
    </div>
    <div class="jh-neg-progress-label">
      ${negEscapeHtml(negSyncProgress.message || `${negSyncProgress.done} / ${negSyncProgress.total}`)}
      ${quotaHint}
    </div>
  `;
}

function clearSyncProgress() {
  negSyncProgress = null;
  const wrap = negShadowRoot?.getElementById('jh-neg-progress-wrap');
  if (wrap) wrap.remove();
}

function rowActionHtml(item) {
  if (item.sync_state === 'synced') {
    return '<span class="jh-neg-synced-label">Синхронизировано</span>';
  }
  return `<button type="button" class="jh-neg-row-sync" data-vacancy-id="${negEscapeHtml(item.vacancy_id)}">Применить</button>`;
}

/** Карточка отклика (вместо строки таблицы) — контент переносится, страница листается
 *  только вниз, без горизонтальной прокрутки. */
function negCardHtml(item) {
  const hhLabel = negEscapeHtml(item.hh_status_raw || item.hh_status);
  const jhCurrent = negEscapeHtml(item.current_status || '-');
  const jhProposed = negEscapeHtml(item.funnel_status_preview || '-');
  const cardCls = item.sync_state === 'synced' ? 'jh-neg-card-synced' : item.is_discrepancy ? 'jh-neg-card-disc' : '';
  const tbd = item.needs_interview_tracking
    ? '<span class="jh-neg-tbd" title="Лист «Собеседования» — дата не задана">без даты</span>'
    : '';
  const discBadge = item.is_discrepancy && item.sync_state !== 'synced'
    ? '<span class="jh-neg-disc-badge">расхождение</span>'
    : '';
  const needsText = item.needs_vacancy_text
    ? `<span class="jh-neg-needs-text" title="Нет текста вакансии — откройте страницу вакансии, чтобы расширение считало текст. Если не открыть за 6 часов, карточка исчезнет.">${iconMarkup('triangle-alert', { size: 13 })} нужен текст</span>`
    : '';
  const vacUrl = negEscapeHtml(item.url || `https://hh.ru/vacancy/${item.vacancy_id}`);
  return `
    <div class="jh-neg-card ${cardCls}" data-vacancy-id="${negEscapeHtml(item.vacancy_id)}">
      <div class="jh-neg-card-top">
        <span class="jh-neg-id">${negEscapeHtml(item.vacancy_id)}</span>
        <span class="jh-neg-company">${negEscapeHtml(item.company || '-')}</span>
        ${needsText}
      </div>
      <div class="jh-neg-card-title" title="${negEscapeHtml(item.title || '')}">${
        item.needs_vacancy_text
          ? `<a class="jh-neg-vac-link" href="${vacUrl}" target="_blank" rel="noreferrer">${negEscapeHtml(item.title || '-')}</a>`
          : negEscapeHtml(item.title || '-')
      }</div>
      <div class="jh-neg-card-bottom">
        <span class="jh-neg-hh">${hhLabel}</span>
        <span class="jh-neg-jh-cur" title="Текущий статус в Copilot">${jhCurrent}</span>
        ${item.is_discrepancy ? `${iconMarkup('arrow-right', { size: 13, className: 'jh-neg-arrow' })}<span class="jh-neg-jh">${jhProposed}</span>` : ''}
        ${tbd}${discBadge}
        <span class="jh-neg-card-action">${rowActionHtml(item)}</span>
      </div>
    </div>`;
}

/** Навешивает клик на кнопку «Свернуть» в шапке — вызывается после каждого re-render (innerHTML
 *  полностью пересобирается, старый listener теряется вместе со старым узлом). */
function bindNegHeaderActions() {
  const collapseBtn = negPanelEl?.querySelector('[data-action="neg-collapse"]');
  if (collapseBtn) collapseBtn.addEventListener('click', onNegCollapseClick);
}

/** Единая разметка кнопки «Обновить» в тулбаре — иконка+подпись, тот же язык, что у остальных
 *  кнопок панели (была голым текстом без иконки — «кривая» кнопка из фидбека). Пока идёт синх —
 *  крутящийся loader вместо статичной иконки, как у остальных async-кнопок панели. */
function negSyncAllBtnHtml(label, pending = false) {
  const icon = pending
    ? iconMarkup('loader', { size: 14, className: 'jh-spin' })
    : iconMarkup('refresh-cw', { size: 14 });
  return `${icon}<span>${negEscapeHtml(label)}</span>`;
}

function renderNegotiationsPanel(message = '') {
  if (!negPanelEl) return;

  const sorted = sortNegotiationItems(negParsedItems);
  const pendingCount = sorted.filter((x) => x.is_discrepancy && x.sync_state !== 'synced').length;
  const needsTextCount = sorted.filter((x) => x.needs_vacancy_text).length;
  const pageLabel = negotiationsPageLabel();

  if (!sorted.length) {
    negPanelEl.innerHTML = `
      <div class="jh-header">
        <div class="jh-header-main">
          ${NEG_BRAND_HTML}
          <strong>Мои отклики</strong>
          <span class="jh-neg-page-badge">${negEscapeHtml(pageLabel)}</span>
        </div>
        ${negCollapseBtnHtml()}
      </div>
      <div class="jh-body">
        <p class="jh-funnel-hint">Карточки откликов не найдены на этой странице. Перейдите на другую страницу списка или обновите (F5).</p>
        ${message ? `<div class="jh-error">${negEscapeHtml(message)}</div>` : ''}
      </div>
    `;
    if (negSyncAllBtn) {
      negSyncAllBtn.disabled = true;
      negSyncAllBtn.innerHTML = negSyncAllBtnHtml('Обновить');
    }
    bindNegHeaderActions();
    negPanelEl.classList.toggle('hidden', negCollapsed);
    return;
  }

  const cards = sorted.map(negCardHtml).join('');
  const needsTextHint = needsTextCount
    ? `<p class="jh-funnel-hint jh-neg-needs-hint">${iconMarkup('triangle-alert', { size: 13 })} У ${needsTextCount} ${
        needsTextCount === 1 ? 'вакансии' : needsTextCount < 5 ? 'вакансий' : 'вакансий'
      } нет текста вакансии — откройте страницу вакансии, чтобы расширение считало текст. Если не открыть за 6 часов, карточка исчезнет.</p>`
    : '';

  negPanelEl.innerHTML = `
    <div class="jh-header">
      <div class="jh-header-main">
        ${NEG_BRAND_HTML}
        <strong>Отклики</strong>
        <span class="jh-neg-page-badge" title="Текущая страница HH">${negEscapeHtml(pageLabel)}</span>
        ${pendingCount ? `<span class="jh-neg-pending-count">${pendingCount} ожидают</span>` : ''}
      </div>
      ${negCollapseBtnHtml()}
    </div>
    <div class="jh-body">
      <p class="jh-funnel-hint">Статусы переносятся в Copilot автоматически. Если что-то разошлось — нажмите «Обновить» или на карточку ниже.</p>
      ${needsTextHint}
      ${negPreviewError ? `<div class="jh-error">${negEscapeHtml(negPreviewError)}</div>` : ''}
      ${message ? `<div class="jh-neg-msg">${negEscapeHtml(message)}</div>` : ''}
      <div class="jh-neg-cards">${cards}</div>
    </div>
  `;

  if (negSyncAllBtn) {
    negSyncAllBtn.disabled = negSyncing || pendingCount === 0;
    negSyncAllBtn.innerHTML = negSyncAllBtnHtml(
      pendingCount > 0 ? `Обновить (${pendingCount})` : 'Обновить',
    );
  }
  bindNegHeaderActions();
  negPanelEl.classList.toggle('hidden', negCollapsed);

  negPanelEl.querySelectorAll('.jh-neg-row-sync').forEach((btn) => {
    btn.addEventListener('click', () => {
      const vid = btn.getAttribute('data-vacancy-id');
      // force:false — гард бэка (+ LLM-разбор спорных случаев) не даёт откатить
      // Скрининг/Техничку/Финал/Оффер обратно в Отклик по устаревшему статусу HH (R-3).
      syncNegotiationItems(
        negParsedItems.filter((x) => String(x.vacancy_id) === vid),
        { force: false }
      );
    });
  });
}

function applySyncResultsToItems(results) {
  if (!results?.length) return;
  const byId = Object.fromEntries(results.map((r) => [String(r.vacancy_id), r]));
  for (const item of negParsedItems) {
    const r = byId[String(item.vacancy_id)];
    if (!r) continue;
    if (r.applied && !r.skipped) {
      item.sync_state = 'synced';
      item.current_status = r.funnel_status;
      item.is_discrepancy = false;
    } else if (r.current_status) {
      item.current_status = r.current_status;
      item.is_discrepancy = r.is_discrepancy ?? item.is_discrepancy;
    }
  }
  negParsedItems = sortNegotiationItems(negParsedItems);
  negLastPreviewKey = '';
}

async function enrichItemsWithBackendStatus({ force = false } = {}) {
  if (negSyncing || !negParsedItems.length) return null;

  const previewKey = [
    negotiationsPageKey(),
    ...negParsedItems.map((i) => i.vacancy_id).sort(),
  ].join('|');
  if (!force && previewKey === negLastPreviewKey) return negPreviewError;

  const { error } = await fetchNegotiationsPreview(negParsedItems, negSendMessage);
  negPreviewError = error || '';
  if (!error) negLastPreviewKey = previewKey;
  return negPreviewError || null;
}

function syncNegotiationItemsStream(payload) {
  return new Promise((resolve, reject) => {
    if (!isExtensionAlive()) {
      reject(new Error('Расширение обновлено — обновите страницу hh.ru (F5)'));
      return;
    }
    let port;
    try {
      port = chrome.runtime.connect({ name: 'sync_negotiations_stream' });
    } catch (err) {
      reject(err);
      return;
    }
    port.onMessage.addListener((msg) => {
      if (msg.type === 'progress' && msg.event) {
        renderSyncProgress(msg.event);
      }
      if (msg.type === 'done') {
        port.disconnect();
        resolve(msg.data);
      }
      if (msg.type === 'error') {
        port.disconnect();
        reject(new Error(msg.error || 'Ошибка синхронизации'));
      }
    });
    port.onDisconnect.addListener(() => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      }
    });
    port.postMessage({ action: 'start', payload });
  });
}

async function syncNegotiationItems(items, options: { force?: boolean; dryRun?: boolean; auto?: boolean } = {}) {
  const { force = false, dryRun = false, auto = false } = options;
  if (!items.length) return;
  negSyncing = true;
  clearSyncProgress();
  renderSyncProgress({
    type: 'start',
    done: 0,
    total: items.length,
    message: dryRun ? 'Проверка…' : 'Синхронизация статусов…',
  });
  if (negSyncAllBtn) {
    negSyncAllBtn.disabled = true;
    negSyncAllBtn.innerHTML = negSyncAllBtnHtml(dryRun ? 'Проверка…' : 'Синхронизация…', true);
  }

  try {
    let data;
    if (dryRun) {
      data = await applySync(items, { force, dryRun: true }, negSendMessage);
    } else {
      data = await syncNegotiationItemsStream({
        items: items.map(negotiationsPayloadItem),
        dry_run: false,
        use_llm: true,
        force,
      });
    }

    if (!data?.results) {
      throw new Error('Пустой ответ синхронизации');
    }
    applySyncResultsToItems(data.results);
    const synced = data.synced_count ?? 0;
    const skipped = data.skipped_count ?? 0;
    const msg = dryRun
      ? `Проверка: ${items.length} карточек`
      : auto
        ? `Авто-перенос: ${synced} перенесено, ${skipped} без изменений`
        : `Готово: обновлено ${synced}, без изменений ${skipped}`;
    clearSyncProgress();
    renderNegotiationsPanel(msg);
  } catch (err) {
    clearSyncProgress();
    renderNegotiationsPanel(String(err.message || err));
  } finally {
    negSyncing = false;
  }
}

async function onSyncAllDiscrepanciesClick() {
  await refreshNegotiationsParse({ forcePreview: true });
  const toSync = negParsedItems.filter(
    (x) => x.is_discrepancy && x.sync_state !== 'synced'
  );
  if (!toSync.length) {
    renderNegotiationsPanel('Нет расхождений на этой странице — всё синхронизировано.');
    return;
  }
  // force:false — массовая синхронизация не должна откатывать Скрининг/Техничку/Финал/Оффер
  // обратно в Отклик по устаревшему статусу HH; бэк сам решает спорные случаи через LLM (R-3).
  await syncNegotiationItems(toSync, { force: false });
}

async function refreshNegotiationsParse({ forcePreview = false } = {}) {
  negParsedItems = parseNegotiationsFromRoot(document);
  const previewErr = await enrichItemsWithBackendStatus({ force: forcePreview });
  negParsedItems = sortNegotiationItems(negParsedItems);
  renderNegotiationsPanel(previewErr || '');
  // Решение 9: все расхождения переносим сами (раз на страницу) — «Обновить» ниже только
  // на случай, если бэк что-то отклонил гардом или статус изменился уже после авто-переноса.
  await maybeAutoSyncDiscrepancies();
}

async function initNegotiationsPage(slots) {
  ensureNegotiationsUi(slots);
  renderNegotiationsPanel('Загрузка откликов…');
  try {
    await refreshNegotiationsParse({ forcePreview: true });
  } catch (err) {
    console.warn('Job Hunter: parse negotiations', err);
    renderNegotiationsPanel(String(err.message || err));
  }
}

/** EX-7: dock зовёт на каждый тик MutationObserver/popstate, пока адаптер негоциаций активен —
 *  ровно та же развилка, что раньше делал handleNegotiationsNavigation() в собственном observer'е
 *  (только ветка «не на странице негоциаций» ушла — этим теперь занят роутинг dock.ts). */
function onNegotiationsNavigate() {
  const pageKey = negotiationsPageKey();
  const pageChanged = pageKey !== negLastPageKey;
  negLastPageKey = pageKey;

  if (pageChanged && !negSyncing) {
    negLastPreviewKey = '';
    void refreshNegotiationsParse({ forcePreview: true });
    return;
  }

  if (!negSyncing) {
    scheduleNegotiationsDomRefresh();
  }
}

function scheduleNegotiationsDomRefresh() {
  if (negSyncing) return;
  clearTimeout(negDomRefreshTimer);
  negDomRefreshTimer = setTimeout(() => {
    if (negSyncing || !isExtensionAlive() || getHhPageType() !== HH_PAGE_TYPE.NEGOTIATIONS) return;
    void refreshNegotiationsParse();
  }, 2500);
}

function mountNegotiationsAdapter(slots) {
  negLastPageKey = negotiationsPageKey();
  void initNegotiationsPage(slots);
}

const negotiationsAdapter = {
  key: 'negotiations',
  matches: (route: SiteRoute) =>
    route.site === 'hh' && route.pageType === HH_PAGE_TYPE.NEGOTIATIONS,
  mount: mountNegotiationsAdapter,
  onNavigate: onNegotiationsNavigate,
  teardown: teardownNegotiationsUi,
  liftForHhChat: true,
}

export { negotiationsAdapter }
