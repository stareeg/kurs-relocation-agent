import { HH_PAGE_TYPE, type SiteRoute } from '../dom/site-router'
import { parseHrThreadFromDom } from '../dom/selectors'
import { iconMarkup } from '../ui/icons'
import { loadConfig, DEFAULT_WEB_BASE_URL } from '../config'

/**
 * EX-9: тихий импорт переписки с HR из индивидуального треда `/applicant/negotiations/<id>` в
 * `hr_threads` (AF-5). Никакого чата в расширении — только статус-строка + ссылка «Открыть в
 * Чатах» (DoD плана). Селекторы реплик — эмпирика (`dom/selectors.ts` HR_THREAD_SELECTORS),
 * требуют подтверждения на живой странице; при несовпадении вёрстки адаптер молча не синкает
 * (не корёжим hr_threads угадыванием), панель показывает подсказку без AI-slop.
 */

const HR_BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 13 })}<span>Copilot</span></div>`;

let hrPanelEl = null;
let hrConfig = null;
let hrSyncInFlight = false;
/** URL, для которого уже отработал синк в этом визите — не дублируем на каждый DOM-тик. */
let hrSyncedPageKey = '';

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id);
  } catch {
    return false;
  }
}

function hrDelay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function hrEscapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function hrSendMessage(message): Promise<any> {
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

async function ensureHrConfig() {
  if (!hrConfig) hrConfig = await loadConfig();
  return hrConfig;
}

function webChatUrl(vacancyId) {
  const base = hrConfig?.webBaseUrl || DEFAULT_WEB_BASE_URL;
  return `${base}/chat?vacancy=${encodeURIComponent(vacancyId)}`;
}

function renderHrPanel(html) {
  if (!hrPanelEl) return;
  hrPanelEl.innerHTML = html;
}

function renderLoading() {
  renderHrPanel(`
    <div class="jh-header">
      <div class="jh-header-main">${HR_BRAND_HTML}<strong>Переписка с HR</strong></div>
    </div>
    <div class="jh-body"><p class="jh-funnel-hint">Читаю переписку…</p></div>
  `);
}

/** Единственный видимый результат работы адаптера - строка статуса + линк в веб (без своего чата). */
function renderStatus(vacancyId, message) {
  const linkHtml = vacancyId
    ? `<div class="jh-act-row"><button type="button" class="jh-act-btn" data-action="open-chat">${iconMarkup('external-link', { size: 14 })}<span>Открыть в Чатах</span></button></div>`
    : '';
  renderHrPanel(`
    <div class="jh-header">
      <div class="jh-header-main">${HR_BRAND_HTML}<strong>Переписка с HR</strong></div>
    </div>
    <div class="jh-body">
      <p class="jh-funnel-hint">${hrEscapeHtml(message)}</p>
      ${linkHtml}
    </div>
  `);
  const btn = hrPanelEl?.querySelector('[data-action="open-chat"]');
  if (btn) {
    btn.addEventListener('click', () => window.open(webChatUrl(vacancyId), '_blank', 'noopener'));
  }
}

/** Чат SPA дорисовывает реплики асинхронно - ждём, пока парсер начнёт что-то находить (или дедлайн). */
async function waitForHrThread() {
  const deadline = Date.now() + 6000;
  let last = null;
  while (Date.now() < deadline) {
    if (!isExtensionAlive()) return null;
    const parsed = parseHrThreadFromDom(document);
    last = parsed;
    if (parsed.vacancy_id && parsed.messages.length) return parsed;
    await hrDelay(300);
  }
  return last;
}

/**
 * EXT-H1: реплики с `kind: null` (DOM-эвристика не нашла надёжного сигнала направления) —
 * один batched вызов background на весь тред, не на реплику. Сеть упала/бэк недоступен —
 * `response.ok === false`, реплики остаются `null` и ниже отфильтруются (прежний fallback).
 */
async function classifyAmbiguousDirections(messages) {
  if (!messages.some((m) => !m.kind)) return messages;

  const response = await hrSendMessage({
    action: 'classify_hr_direction',
    payload: { messages: messages.map((m, index) => ({ index, kind: m.kind, body: m.body })) },
  });
  if (!response?.ok) return messages;

  const resolved = response.data?.resolved || {};
  return messages.map((m, index) => (m.kind ? m : { ...m, kind: resolved[index] || null }));
}

async function runSync() {
  const parsed = await waitForHrThread();
  if (!parsed || !parsed.vacancy_id) {
    renderStatus(null, 'Не удалось определить вакансию для этого треда.');
    return;
  }
  if (!parsed.messages.length) {
    renderStatus(
      parsed.vacancy_id,
      'Сообщений в чате не нашли (либо их правда нет, либо hh поменял вёрстку - проверьте вручную).'
    );
    return;
  }

  await ensureHrConfig();
  const classified = await classifyAmbiguousDirections(parsed.messages);
  const messages = classified.filter((m) => m.kind); // без надёжного сигнала (и без LLM) — пропуск

  if (!messages.length) {
    renderStatus(
      parsed.vacancy_id,
      'Не удалось распознать направление ни одного сообщения (проверьте вручную).'
    );
    return;
  }

  const response = await hrSendMessage({
    action: 'hr_thread_sync',
    payload: {
      vacancy_id: parsed.vacancy_id,
      company: parsed.company || '',
      messages,
    },
  });

  if (!response?.ok) {
    renderStatus(parsed.vacancy_id, `Не удалось синхронизировать переписку: ${response?.error || 'ошибка'}`);
    return;
  }

  const total = response.data?.total_messages ?? messages.length;
  const synced = response.data?.synced_count ?? 0;
  const suffix = synced > 0 ? ` (+${synced} новых)` : '';
  renderStatus(parsed.vacancy_id, `Переписка синхронизирована · ${total} сообщений${suffix}`);
}

async function runForCurrentPage() {
  const key = location.href;
  if (hrSyncInFlight || hrSyncedPageKey === key) return;
  hrSyncInFlight = true;
  try {
    await runSync();
    hrSyncedPageKey = key;
  } catch (err) {
    console.warn('Job Hunter: hr-thread sync', err);
    renderStatus(null, String(err.message || err));
  } finally {
    hrSyncInFlight = false;
  }
}

// EX-7: точка монтирования в общий док (dock.ts владеет shadow-host/panel/toast/toolbar).
function ensureHrThreadUi(slots) {
  hrPanelEl = slots.panelEl;
  hrPanelEl.classList.add('jh-hr-panel');
  hrPanelEl.classList.remove('hidden');
  renderLoading();
}

function teardownHrThreadUi() {
  hrPanelEl = null;
  hrSyncedPageKey = '';
}

function mountHrThreadAdapter(slots) {
  ensureHrThreadUi(slots);
  hrSyncedPageKey = '';
  void runForCurrentPage();
}

/** SPA может подменить тред (соседняя ссылка в списке слева) без смены адаптера — синкаем заново. */
function onHrThreadNavigate(_slots, ctx) {
  if (!ctx.urlChanged) return;
  hrSyncedPageKey = '';
  renderLoading();
  void runForCurrentPage();
}

const hrThreadAdapter = {
  key: 'hr-thread',
  matches: (route: SiteRoute) =>
    route.site === 'hh' && route.pageType === HH_PAGE_TYPE.NEGOTIATION_THREAD,
  mount: mountHrThreadAdapter,
  onNavigate: onHrThreadNavigate,
  teardown: teardownHrThreadUi,
  liftForHhChat: true,
}

export { hrThreadAdapter }
