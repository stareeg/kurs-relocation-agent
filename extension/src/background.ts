// Базовый URL сайта и личный токен берём из chrome.storage (options-страница). Адрес API
// выводится из адреса сайта (EX-17, см. config.ts deriveApiBaseUrl) — пользователь вводит один
// URL, не два.
import { DEFAULT_WEB_BASE_URL, deriveApiBaseUrl, normalizeBaseUrl } from './config';
import { fetchSelectorsFromApi } from './dom/selectors-config';
import {
  createRealDeps,
  runAnketaResumeCycle,
  runAutoApplyCycle,
} from './background/auto-apply-runner';
import { createRealDeps as createDiscoveryDeps, runDiscoveryCycle } from './background/discovery-runner';
import { reconcileRecurringAlarms } from './background/schedule-alarms';
import { fetchRuntimeConfigFromApi, getFlag, getRuntimeConfig } from './dom/extension-runtime-config';

let backendUrl = deriveApiBaseUrl(DEFAULT_WEB_BASE_URL);
let authToken = '';
let configLoaded = null;

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get(['webBaseUrl', 'authToken']);
    backendUrl = deriveApiBaseUrl(normalizeBaseUrl(cfg.webBaseUrl, DEFAULT_WEB_BASE_URL));
    authToken = cfg.authToken || '';
  } catch (err) {
    console.warn('[Job Hunter] config load:', err);
  }
}

function ensureConfig() {
  if (!configLoaded) configLoaded = loadConfig();
  return configLoaded;
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.webBaseUrl || changes.authToken)) {
    configLoaded = loadConfig();
  }
});

/** URL эндпоинта нового API. */
function apiUrl(path) {
  return `${backendUrl}${path}`;
}

/** Версия расширения из manifest.json — шлём как X-Extension-Version, чтобы бэкенд знал,
 *  какой версией пользуется аккаунт (для подсказки «вышла новая версия» на странице «Расширение»). */
const EXTENSION_VERSION = chrome.runtime.getManifest().version || '';

/** Заголовки запроса к API: X-Auth-Token (если задан) + Content-Type для тела +
 *  X-Extension-Version (для отслеживания версии аккаунта). */
function apiHeaders(json) {
  const headers = {};
  if (json) headers['Content-Type'] = 'application/json';
  if (authToken) headers['X-Auth-Token'] = authToken;
  if (EXTENSION_VERSION) headers['X-Extension-Version'] = EXTENSION_VERSION;
  return headers;
}

const extHttpReported = new Set();

/** Неудачный ответ (>=400) или сетевой сбой собственного запроса расширения к API → одна
 *  строка в витрину логов (тот же POST /api/logs/frontend, что и parse-health.ts выше).
 *  Дедуп — один раз на (action, status) за жизнь service worker'а, иначе упавший бэкенд
 *  даст сотни одинаковых строк. Без window.onerror — расширение сидит на чужих страницах,
 *  глобальный перехват натащил бы в лог чужой JS с hh.ru/getmatch.ru. */
function reportExtHttpFailure(action, status, detail) {
  const key = `${action}:${status}`;
  if (extHttpReported.has(key)) return;
  extHttpReported.add(key);
  const level = status === 0 || status >= 500 ? 'ERROR' : 'WARNING';
  const reason = status === 0 ? 'сеть недоступна' : `HTTP ${status}`;
  const entry = {
    ts: new Date().toISOString(),
    level,
    kind: 'ext_http',
    message: `Запрос расширения к API упал: ${action} (${reason})${detail ? ' · ' + detail : ''}`,
    url: null,
    endpoint: `extension:${action}`,
    status,
  };
  fetch(apiUrl('/api/logs/frontend'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ entries: [entry] }),
  }).catch(() => {
    /* лог о падении лога не логируем — best-effort */
  });
}

/** fetch() к своему API с автоматическим репортом неудачи (см. reportExtHttpFailure) — тот
 *  же Response/exception, что голый fetch(), вызывающие функции не меняют свою логику. */
async function apiFetch(action, url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    reportExtHttpFailure(action, 0, err?.message);
    throw err;
  }
  if (!response.ok) {
    reportExtHttpFailure(action, response.status, null);
  }
  return response;
}

/** Прерывает текущий fetch к POST /score (отмена в UI), per-вкладка.
 *
 * Баг до фикса: один общий AbortController на весь background service worker (MV3 — общий
 * процесс на все вкладки) — скоринг вакансии B молча отменял ещё летящий скоринг вакансии A в
 * ДРУГОЙ вкладке. Открыл несколько вакансий параллельно — оценивалась только последняя. Ключ —
 * sender.tab.id (без вкладки, напр. options-страница, — фиксированный ключ 'no-tab'). */
const scoreFetchAbortByTab = new Map();
const NO_TAB_KEY = 'no-tab';

function tabKeyFor(sender) {
  return sender?.tab?.id ?? NO_TAB_KEY;
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'sync_negotiations_stream') return;
  port.onMessage.addListener((msg) => {
    if (msg.action !== 'start') return;
    syncNegotiationsStream(msg.payload, (event) => {
      try {
        port.postMessage({ type: 'progress', event });
      } catch {
        /* port closed */
      }
    })
      .then((data) => port.postMessage({ type: 'done', data }))
      .catch((err) => port.postMessage({ type: 'error', error: err.message }));
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // EX-11: кнопка «Параметры» в доке (content-script не имеет доступа к openOptionsPage — релей).
  if (message.action === 'open_settings') {
    chrome.runtime.openOptionsPage();
    return false;
  }

  if (message.action === 'cancel_score') {
    const key = tabKeyFor(sender);
    scoreFetchAbortByTab.get(key)?.abort();
    scoreFetchAbortByTab.delete(key);
    sendResponse({ ok: true });
    return false;
  }

  if (message.action === 'score') {
    scoreVacancy(message.payload, tabKeyFor(sender))
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'poll_salary') {
    pollSalaryEstimate(message.payload?.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'poll_skip_reasons') {
    pollSkipReasons(message.payload?.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'update_status') {
    updateStatus(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'check_seen') {
    checkVacancySeen(message.payload.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'get_vacancy_record') {
    getVacancyRecord(message.payload.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'get_funnel') {
    getFunnelStatus(message.payload.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'ask') {
    askVacancy(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'get_conversation') {
    getConversation(message.payload?.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'cover_letter') {
    generateCoverLetter(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'cover_letter_save') {
    updateCoverLetterText(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'skip') {
    skipVacancy(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'unskip') {
    unskipVacancy(message.payload.vacancy_id)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'update_theses') {
    updateVacancyTheses(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'sync_negotiations') {
    syncNegotiations(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'negotiations_preview') {
    negotiationsPreview(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'marketDemand') {
    ingestMarketDemand(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'marketIndex') {
    ingestMarketIndex(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'resumeStats') {
    ingestResumeStats(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'resumeViews') {
    ingestResumeViews(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'gm_profile_sync') {
    ingestGmProfile(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'gm_trust_sync') {
    ingestGmTrust(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'hr_thread_sync') {
    syncHrThread(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'classify_hr_direction') {
    classifyHrDirection(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'get_settings') {
    ensureConfig()
      .then(() => apiFetch('get_settings', apiUrl('/api/settings'), { headers: apiHeaders(false) }))
      .then((r) => {
        if (!r.ok) throw new Error(`Backend HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'health') {
    ensureConfig()
      .then(() => apiFetch('health', apiUrl('/health'), { headers: apiHeaders(false) }))
      .then((r) => {
        if (!r.ok) throw new Error(`Backend HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  // FR2-71: хелсчек селекторов → POST /api/logs/frontend (тот же X-API-Key путь).
  if (message.action === 'report_parse_health') {
    maybeRefreshSelectorsOnParseHealth(message.payload, sender.tab?.id);
    postParseHealth(message.payload)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'refresh_parser_selectors') {
    fetchSelectorsFromApi({ force: Boolean(message.force) })
      .then((pack) =>
        sendResponse({
          ok: true,
          version: pack.version,
          origin: pack.origin,
        }),
      )
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  // EX-10 fix: вход/статус из дока на hh.ru/getmatch.ru — релей через background, а не прямой
  // fetch из content script. Content-script fetch идёт с Origin страницы (https://hh.ru), а не
  // chrome-extension://<id> — бэк такой Origin не пускает (CORS allow_origins = сайт +
  // ^chrome-extension://.*$, про hh.ru/getmatch.ru он не знает). Запросы из background идут от
  // имени расширения и матчатся extension_origin_regex, как и все остальные экшены выше.
  if (message.action === 'login') {
    loginWithBackend(message.payload?.token)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.action === 'auth_status') {
    fetchAuthStatusFromBackend(message.payload?.token)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

});

function parseHealthReasonLabel(reason) {
  if (reason === 'zero_cards') return '0 карточек (селекторы не нашли вакансии)';
  if (reason === 'vacancy_timeout') return 'таймаут ожидания DOM (текст не стабилизировался)';
  if (reason === 'vacancy_empty') return 'пустой/короткий текст вакансии (селекторы не сработали)';
  if (reason === 'responses_count_missing') return 'не найден счётчик откликов (2026-08-18: hh.ru обычно не отдаёт его на странице вакансии вовсе — не обязательно поломка селектора)';
  if (reason === 'rsc_fallback_to_jsonld') return 'RSC-слой упал, вакансия распарсена из JSON-LD';
  if (reason === 'rsc_fallback_to_dom') return 'RSC и JSON-LD упали, вакансия распарсена из DOM';
  if (reason === 'unknown_selector_key') return 'конфиг парсера: неизвестный ключ отброшен';
  if (reason === 'invalid_selector') return 'конфиг парсера: невалидный CSS-селектор отброшен';
  if (reason === 'config_schema_invalid') return 'конфиг парсера: схема невалидна, откат на дефолты';
  if (reason === 'config_http_insecure') return 'конфиг парсера: apiBaseUrl не https (и не localhost)';
  return String(reason || 'unknown');
}

const SELECTOR_REFRESH_REASONS = new Set(['zero_cards', 'vacancy_empty', 'vacancy_timeout']);
const selectorRefreshTabs = new Set();

/** Один рефетч конфига на вкладку при подозрении, что селекторы hh мертвы. */
function maybeRefreshSelectorsOnParseHealth(payload, tabId) {
  if (payload?.site !== 'hh') return;
  if (!SELECTOR_REFRESH_REASONS.has(payload.reason)) return;
  const key = tabId == null ? 'no-tab' : tabId;
  if (selectorRefreshTabs.has(key)) return;
  selectorRefreshTabs.add(key);
  void fetchSelectorsFromApi({ force: true });
}

/** Причины, которые НЕ являются поломкой парсера и не должны стоять в журнале WARNING'ом.
 *  `responses_count_missing`: hh.ru обычно вовсе не отдаёт счётчик откликов на странице
 *  вакансии — за 4 дня прода это дало 59 строк WARNING подряд и забило витрину, из-за которой
 *  журнал и заводился. Ошибкой это не было ни разу. */
const PARSE_HEALTH_INFO_REASONS = new Set([
  'responses_count_missing',
  'rsc_fallback_to_jsonld',
  'rsc_fallback_to_dom',
]);

/** FR2-71: одна строка в витрину логов — редизайн hh/getmatch сразу виден в «Логах».
 *  WARNING только для настоящих подозрений на поломку селекторов (см. набор выше). */
async function postParseHealth(payload) {
  await ensureConfig();
  const site = payload?.site || '?';
  const page = payload?.page || '?';
  const reason = payload?.reason || 'unknown';
  const detail = payload?.detail ? ` · ${payload.detail}` : '';
  const entry = {
    ts: new Date().toISOString(),
    level: PARSE_HEALTH_INFO_REASONS.has(reason) ? 'INFO' : 'WARNING',
    kind: 'extension_parse',
    message: `Парсер ${site}/${page}: ${parseHealthReasonLabel(reason)}${detail}`,
    url: payload?.url || null,
    endpoint: `extension:${site}/${page}`,
    status: 0,
    parse_method: payload?.method || null,
    config_version: payload?.config_version ?? null,
    config_origin: payload?.config_origin || null,
  };
  const response = await fetch(apiUrl('/api/logs/frontend'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ entries: [entry] }),
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`HTTP ${response.status}`);
  }
}

async function updateStatus(payload: any) {
  await ensureConfig();
  const body: any = {
    vacancy_id: payload.vacancy_id,
    status: payload.status,
  };
  if (payload.cover_letter) body.cover_letter = payload.cover_letter;
  if (payload.published_at) body.published_at = payload.published_at;
  if (payload.offer_at) body.offer_at = payload.offer_at;
  if (payload.title) body.title = payload.title;
  if (payload.company) body.company = payload.company;
  if (payload.vacancy_text) body.vacancy_text = payload.vacancy_text;
  const response = await apiFetch('update_status', apiUrl('/funnel'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

async function checkVacancySeen(vacancyId) {
  if (!vacancyId) {
    return { seen: false, vacancy_id: vacancyId };
  }
  await ensureConfig();
  const response = await apiFetch(
    'check_seen',
    apiUrl(`/vacancies/${encodeURIComponent(vacancyId)}/seen`),
    { headers: apiHeaders(false) },
  );
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function getVacancyRecord(vacancyId) {
  if (!vacancyId) throw new Error('vacancy_id обязателен');
  await ensureConfig();
  const response = await apiFetch(
    'get_vacancy_record',
    apiUrl(`/vacancies/${encodeURIComponent(vacancyId)}/record`),
    { headers: apiHeaders(false) },
  );
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

async function getFunnelStatus(vacancyId) {
  if (!vacancyId) {
    return { vacancy_id: vacancyId, status: null, source: null };
  }
  await ensureConfig();
  const response = await apiFetch(
    'get_funnel',
    apiUrl(`/funnel/${encodeURIComponent(vacancyId)}`),
    { headers: apiHeaders(false) },
  );
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function getConversation(vacancyId) {
  if (!vacancyId) {
    return { vacancy_id: vacancyId, thread: null, messages: [], hr_link: '' };
  }
  await ensureConfig();
  const response = await apiFetch(
    'get_conversation',
    apiUrl(`/api/conversations/${encodeURIComponent(vacancyId)}`),
    { headers: apiHeaders(false) },
  );
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

async function askVacancy(payload) {
  await ensureConfig();
  const vacancyId = payload.vacancy_id;
  const response = await apiFetch('ask', apiUrl(`/vacancies/${encodeURIComponent(vacancyId)}/ask`), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      question: payload.question,
      history: payload.history || [],
      vacancy_text: payload.vacancy_text || null,
      title: payload.title || null,
      company: payload.company || null,
      salary_text: payload.salary_text || null,
      score: payload.score || null,
    }),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

/** Достаёт человекочитаемое `detail.message` из тела ошибки API (или fallback `HTTP {status}`).
 *
 * Конверт бэка — `{"detail": {code, message, details}}` (см. `api/errors.py`). До фикса тут был
 * `JSON.stringify(body.detail)` — пользователь в панели видел сырой JSON вида
 * `{"code":"llm_error","message":"...","details":{}}` вместо текста ошибки. */
async function errorDetail(response) {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.json();
    const d = body?.detail;
    if (typeof d === 'string' && d.trim()) {
      detail = d;
    } else if (d && typeof d === 'object' && typeof d.message === 'string' && d.message.trim()) {
      detail = d.message;
    } else if (d) {
      detail = JSON.stringify(d);
    }
  } catch {
    /* ignore */
  }
  return detail;
}

// EX-10 fix: POST /auth/token — вход по токену из панели на hh.ru/getmatch.ru (см. релей в
// onMessage выше). Токен ещё не сохранён в chrome.storage на момент вызова, поэтому шлём его как
// есть из payload, а не через apiHeaders()/authToken.
async function loginWithBackend(token) {
  await ensureConfig();
  const response = await apiFetch('login', apiUrl('/auth/token'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: token || '' }),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

// EX-10 fix: GET /auth/status с явным токеном из payload (а не из закэшированного authToken
// background — checkAuthGate в dock.ts проверяет токен, который мог ещё не долететь до
// chrome.storage.onChanged).
async function fetchAuthStatusFromBackend(token) {
  await ensureConfig();
  const headers = {};
  if (token) headers['X-Auth-Token'] = token;
  const response = await apiFetch('auth_status', apiUrl('/auth/status'), { headers });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

// EX-4: черновик сопроводительного на странице вакансии. Ключ — числовой job.id (как в
// /api/jobs/{id}); расширение знает его из ответа /score (поле id). Текст уже пишется в
// jobs.cover_letter_text на бэке; здесь возвращаем его для показа + копирования.
// Э4.4: payload.lang ("ru"|"en") — переключалка в панели; без него бэкенд выводит язык из
// резюме сам и возвращает фактический выбор в data.lang.
async function generateCoverLetter(payload) {
  await ensureConfig();
  const jobId = payload.job_id;
  const response = await apiFetch(
    'cover_letter',
    apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/cover-letter`),
    {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({ lang: payload.lang || null }),
    },
  );
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// Правка 2026-08-20: ручная правка письма прямо на странице вакансии (клик по тексту в панели —
// см. `onCoverEditStartClick`/`onCoverSaveClick` в `content/main.ts`), тот же PATCH-эндпоинт, что
// использует веб-дровер (`updateJobApplyFields`, `frontend/src/api/jobs.ts`) — расширение теперь
// не отправляет владельца в веб, чтобы отредактировать сгенерированное письмо.
async function updateCoverLetterText(payload) {
  await ensureConfig();
  const jobId = payload.job_id;
  const response = await apiFetch('cover_letter_save', apiUrl(`/api/jobs/${encodeURIComponent(jobId)}`), {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify({ cover_letter_text: payload.cover_letter_text ?? '' }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// EX-4: быстрый триаж «Пропустить» с причиной. POST /skip фиксирует решение «не подавать»
// (ортогонально статусу воронки) в Postgres; попадает на вкладку «Пропущенные» в web.
async function skipVacancy(payload) {
  await ensureConfig();
  const response = await apiFetch('skip', apiUrl('/skip'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      vacancy_id: payload.vacancy_id,
      skip_reason: payload.skip_reason,
      url: payload.url || null,
      title: payload.title || null,
      company: payload.company || null,
      overall_score: payload.overall_score ?? null,
      recommendation: payload.recommendation || null,
    }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// Решение 3: drag-and-drop правка тезисов (Плюсы/Минусы/Красные флаги) на панели — всегда шлём
// все три списка целиком (не diff), PATCH переписывает только их внутри уже посчитанного score.
async function updateVacancyTheses(payload) {
  await ensureConfig();
  const vacancyId = payload.vacancy_id;
  const response = await apiFetch(
    'update_theses',
    apiUrl(`/vacancies/${encodeURIComponent(vacancyId)}/score/theses`),
    {
      method: 'PATCH',
      headers: apiHeaders(true),
      body: JSON.stringify({
        pros: payload.pros || [],
        cons: payload.cons || [],
        red_flags: payload.red_flags || [],
      }),
    },
  );
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// Снятие пропуска: DELETE /skip/{id} возвращает вакансию в воронку. Решение «не подавать»
// отменяемо — чтобы «Пропущено» не было вечным тупиком (в т.ч. для исторически авто-скипнутых).
async function unskipVacancy(vacancyId) {
  await ensureConfig();
  const response = await apiFetch(
    'unskip',
    apiUrl(`/skip/${encodeURIComponent(vacancyId)}`),
    { method: 'DELETE', headers: apiHeaders(false) },
  );
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// E-01: показание «Найдено N вакансий» со страницы выдачи hh (D-07 /api/market/demand).
// Дневная идемпотентность — на бэке (upsert по день+запрос+источник), не 500 без PG: расширение
// шлёт на каждый заход, не должно спамить ошибками.
async function ingestMarketDemand(payload) {
  await ensureConfig();
  const response = await apiFetch('marketDemand', apiUrl('/api/market/demand'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      query: payload.query,
      count: payload.count,
      source: payload.source || 'hh_serp',
    }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// E-03: месячный индекс «резюме на вакансию» со страницы статистики hh (D-07 /api/market/index).
// Идемпотентность — на бэке (upsert по месяцу), не 500 без PG: расширение шлёт на каждый заход.
async function ingestMarketIndex(payload) {
  await ensureConfig();
  const response = await apiFetch('marketIndex', apiUrl('/api/market/index'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      value: payload.value,
      source: payload.source || 'hh_stats',
    }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// AF-2: статистика резюме (счётчики + история просмотров). Эндпоинты под префиксом /api
// (resume_stats router), auth по X-API-Key. Приём мягко деградирует на бэке (нет PG →
// persisted=false, не 500) — расширение шлёт авто на заходе, не должно спамить ошибками.
async function ingestResumeStats(payload) {
  await ensureConfig();
  const response = await apiFetch('resumeStats', apiUrl('/api/resume-stats'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      resume_id: payload.resume_id || '',
      period: payload.period || 'week',
      impressions: payload.impressions ?? 0,
      views: payload.views ?? 0,
      invitations: payload.invitations ?? 0,
      recommended_vacancies: payload.recommended_vacancies ?? 0,
      views_delta: payload.views_delta ?? 0,
      invitations_delta: payload.invitations_delta ?? 0,
      raw: payload.raw || {},
    }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

async function ingestResumeViews(payload) {
  await ensureConfig();
  const rows = (payload.rows || []).map((r) => ({
    employer: r.employer || '',
    vacancy_title: r.vacancy_title || '',
    vacancy_url: r.vacancy_url || '',
    viewed_at: r.viewed_at || null,
    resume_id: r.resume_id || '',
    raw: r.raw || {},
  }));
  const response = await apiFetch('resumeViews', apiUrl('/api/resume-views'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ resume_id: payload.resume_id || '', rows }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// GM-13: тихий синк getmatch-профиля кандидата → POST /api/resume/gm-profile-diff. Бэк сравнивает
// с Copilot-резюме и возвращает расхождения (diff). Расширение шлёт на заходе, бэк мягко
// деградирует (нет PG → пустой diff, не 500).
async function ingestGmProfile(payload) {
  await ensureConfig();
  const response = await apiFetch('gm_profile_sync', apiUrl('/api/resume/gm-profile-diff'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ profile: payload || {} }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// GM-12: синк чеклиста доверия getmatch → POST /api/resume/gm-trust. Бэк сохраняет снимок и
// возвращает статус заполненности (N/6 + пропуски). Мягко деградирует (нет PG → stored=false).
async function ingestGmTrust(payload) {
  await ensureConfig();
  const response = await apiFetch('gm_trust_sync', apiUrl('/api/resume/gm-trust'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ trust: payload || {} }),
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

// EX-9: тихий импорт переписки с HR из индивидуального треда (content/hr-thread.ts) в hr_threads
// (AF-5, /api/hr-threads). REST-роут не идемпотентен (POST всегда создаёт новый тред) -
// идемпотентность (создать один раз) и дедуп сообщений держим здесь, на стороне расширения.
function hrMessageDedupKey(kind, sentAt, body) {
  // Сравниваем только цифры даты/времени - хх.ru отдаёт ISO ("...T14:32:00+00:00"), расширение
  // шлёт "YYYY-MM-DD HH:MM" (см. formatNegotiationDate) - форматы разные, минуты те же.
  const sentKey = sentAt ? String(sentAt).replace(/\D/g, '').slice(0, 12) : '';
  return `${kind}|${sentKey}|${String(body || '').slice(0, 100)}`;
}

async function syncHrThread(payload) {
  await ensureConfig();
  const vacancyId = payload.vacancy_id;
  if (!vacancyId) throw new Error('Не удалось определить вакансию');

  const listResp = await apiFetch(
    'hr_thread_sync',
    apiUrl(`/api/hr-threads?vacancy_id=${encodeURIComponent(vacancyId)}`),
    { headers: apiHeaders(false) },
  );
  if (!listResp.ok) throw new Error(await errorDetail(listResp));
  const listData = await listResp.json();
  let thread = (listData.items || [])[0] || null;

  if (!thread) {
    const createResp = await apiFetch('hr_thread_sync', apiUrl('/api/hr-threads'), {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({
        vacancy_id: vacancyId,
        channel: 'hh',
        company: payload.company || '',
      }),
    });
    if (!createResp.ok) throw new Error(await errorDetail(createResp));
    thread = await createResp.json();
  }

  const messagesResp = await apiFetch(
    'hr_thread_sync',
    apiUrl(`/api/hr-threads/${thread.id}/messages`),
    { headers: apiHeaders(false) },
  );
  if (!messagesResp.ok) throw new Error(await errorDetail(messagesResp));
  const messagesData = await messagesResp.json();
  const existingKeys = new Set(
    (messagesData.items || []).map((m) => hrMessageDedupKey(m.kind, m.sent_at, m.body))
  );

  let synced = 0;
  for (const msg of payload.messages || []) {
    const key = hrMessageDedupKey(msg.kind, msg.sent_at, msg.body);
    if (existingKeys.has(key)) continue;
    const addResp = await apiFetch('hr_thread_sync', apiUrl(`/api/hr-threads/${thread.id}/messages`), {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({
        kind: msg.kind,
        body: msg.body,
        sent_at: msg.sent_at || null,
      }),
    });
    if (!addResp.ok) throw new Error(await errorDetail(addResp));
    existingKeys.add(key);
    synced += 1;
  }

  return {
    thread_id: thread.id,
    synced_count: synced,
    total_messages: (messagesData.items || []).length + synced,
  };
}

// EXT-H1: батч-классификация направления реплик, которые `_hrMessageDirection` (dom/selectors.ts)
// не смогла определить по DOM-сигналу. Один вызов на весь тред (content/hr-thread.ts), не на
// реплику; бэк сам решает, кого классифицировать (kind=null во входных элементах).
async function classifyHrDirection(payload) {
  await ensureConfig();
  const response = await apiFetch('classify_hr_direction', apiUrl('/api/hr-threads/classify-direction'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ messages: payload.messages || [] }),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

async function negotiationsPreview(payload) {
  await ensureConfig();
  const response = await apiFetch('negotiations_preview', apiUrl('/funnel/negotiations-preview'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ items: payload.items || [] }),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

/** Разбор SSE-кадров (A-14): id/event/data, комментарии-heartbeat пропускаем. */
function drainSseFrames(buffer, onFrame) {
  let rest = buffer;
  let sep;
  while ((sep = rest.indexOf('\n\n')) !== -1) {
    const frame = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    let event = 'message';
    const dataLines = [];
    for (const raw of frame.split('\n')) {
      const line = raw.replace(/\r$/, '');
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
    }
    if (dataLines.length === 0) continue;
    let data;
    try {
      data = JSON.parse(dataLines.join('\n'));
    } catch {
      continue;
    }
    onFrame({ event, data });
  }
  return rest;
}

async function syncNegotiationsStream(payload, onProgress) {
  await ensureConfig();
  const response = await apiFetch('sync_negotiations_stream', apiUrl('/funnel/sync-negotiations/stream'), {
    method: 'POST',
    headers: {
      ...apiHeaders(true),
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      items: payload.items || [],
      source: 'hh_negotiations',
      dry_run: Boolean(payload.dry_run),
      use_llm: payload.use_llm !== false,
      force: Boolean(payload.force),
    }),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  if (!response.body) {
    throw new Error('Streaming не поддерживается');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let finalData = null;
  let streamError = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    buf = drainSseFrames(buf, ({ event, data }) => {
      const kind = typeof data.type === 'string' ? data.type : event;
      if (onProgress) onProgress(data);
      if ((kind === 'done' || kind === 'complete' || event === 'done') && data.response) {
        finalData = data.response;
      }
      if (kind === 'error' || event === 'error') {
        streamError = data.message || data.detail || 'Ошибка синхронизации';
      }
    });
  }
  if (streamError) throw new Error(streamError);
  if (!finalData) {
    throw new Error('Синхронизация завершилась без ответа');
  }
  return finalData;
}

async function syncNegotiations(payload) {
  await ensureConfig();
  const response = await apiFetch('sync_negotiations', apiUrl('/funnel/sync-negotiations'), {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      items: payload.items || [],
      source: 'hh_negotiations',
      dry_run: Boolean(payload.dry_run),
      use_llm: payload.use_llm !== false,
      force: Boolean(payload.force),
    }),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

async function scoreVacancy(payload, tabKey = NO_TAB_KEY) {
  await ensureConfig();
  scoreFetchAbortByTab.get(tabKey)?.abort();
  const abort = new AbortController();
  scoreFetchAbortByTab.set(tabKey, abort);

  let response;
  try {
    response = await fetch(apiUrl('/score'), {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({
        text: payload.text,
        url: payload.url,
        vacancy_id: payload.vacancy_id,
        title: payload.title || null,
        company: payload.company || null,
        salary_text: payload.salary_text || null,
        area: payload.area || null,
        work_format: payload.work_format || null,
        work_schedule: payload.work_schedule || null,
        total_responses: payload.total_responses ?? null,
        letter_required: payload.letter_required ?? null,
        published_at: payload.published_at || null,
        employer_id: payload.employer_id || null,
        source: payload.source || null,
        is_archived: payload.is_archived ?? false,
        skills: payload.skills ?? null,
        qualification: payload.qualification ?? null,
        salary_currency: payload.salary_currency ?? null,
        specialization: payload.specialization ?? null,
        seniority: payload.seniority ?? null,
        parse_method: payload.parse_method ?? null,
        employment_type: payload.employment_type ?? null,
        location_raw: payload.location_raw ?? null,
        remote_type: payload.remote_type ?? null,
      }),
      signal: abort.signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') {
      // Отмена самим пользователем (новая карточка/повторный клик) — не сбой API, не репортим.
      throw new Error('Оценка отменена');
    }
    reportExtHttpFailure('score', 0, err?.message);
    throw err;
  } finally {
    if (scoreFetchAbortByTab.get(tabKey) === abort) {
      scoreFetchAbortByTab.delete(tabKey);
    }
  }

  if (!response.ok) {
    reportExtHttpFailure('score', response.status, null);
    throw new Error(await errorDetail(response));
  }

  return response.json();
}

async function pollSalaryEstimate(vacancyId) {
  if (!vacancyId) throw new Error('vacancy_id обязателен');
  await ensureConfig();
  const response = await apiFetch(
    'poll_salary',
    apiUrl(`/score/${encodeURIComponent(vacancyId)}/salary`),
    { method: 'GET', headers: apiHeaders(false) },
  );
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

async function pollSkipReasons(vacancyId) {
  if (!vacancyId) throw new Error('vacancy_id обязателен');
  await ensureConfig();
  const response = await apiFetch(
    'poll_skip_reasons',
    apiUrl(`/vacancies/${encodeURIComponent(vacancyId)}/skip-reasons`),
    { method: 'GET', headers: apiHeaders(false) },
  );
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

// Фаза 2.1: раннер автооткликов — тик раз в tuning.auto_apply_tick_minutes, пока сервис-воркер
// жив. chrome.alarms (не setInterval) — MV3 может усыплять service worker между тиками, alarms
// переживают это и сами разбудят воркер к следующему сроку. Период — из рантайм-конфига
// расширения (правится с сервера), см. reconcileAlarms() ниже.
const AUTO_APPLY_ALARM_NAME = 'auto_apply_tick';
let autoApplyRunInFlight = false;

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== AUTO_APPLY_ALARM_NAME) return;
  void runAutoApplyTick();
});

async function runAutoApplyTick() {
  // Тик может занять минуты (несколько вкладок, рандомизированные паузы) — следующий тик alarms
  // не должен запускать параллельный проход по той же очереди.
  if (autoApplyRunInFlight) return;
  autoApplyRunInFlight = true;
  try {
    await ensureConfig();
    const deps = createRealDeps({ apiFetch, apiUrl, apiHeaders });
    // Два прохода — независимо: сбой основного цикла (напр. chrome.tabs.create кинул) не должен
    // отменять досыл одобренных анкет/писем, и наоборот.
    const results = [];
    try {
      results.push(...(await runAutoApplyCycle(deps)));
    } catch (err) {
      reportExtHttpFailure('auto_apply_tick', 0, err?.message);
    }
    // Фаза 3.3/3.4: одобренные анкеты/письма — отдельный проход тем же тиком (раньше не
    // вызывался вообще: подтверждения в вебе копились, а реальной отправки не было).
    try {
      results.push(...(await runAnketaResumeCycle(deps)));
    } catch (err) {
      reportExtHttpFailure('auto_apply_anketa_tick', 0, err?.message);
    }
    // Heartbeat: итог тика в журнал бэка — «раннер жив / бьётся / очередь пуста» должно быть
    // видно в проде (инцидент 2026-08-27..28: раннер молчал 9 часов, в логах — ничего).
    await deps.reportTickSummary?.(results);
  } finally {
    autoApplyRunInFlight = false;
  }
}

// Discovery (авто-открытие вакансий) — отдельный, более частый тик: открытие вкладки на
// просмотр вакансии не так чувствительно к детекту, как реальный отклик (auto-apply-runner
// выше), поэтому темп заметно быстрее. Период — `discovery_tick_minutes` из рантайм-конфига
// (дефолт 0.5 = 30с; chrome.alarms допускает дробное ≥0.5 с Chrome 120, распакованному
// расширению — и без ограничения). Фактический интервал 30–90с добирает джиттер в раннере.
const DISCOVERY_ALARM_NAME = 'discovery_tick';
let discoveryRunInFlight = false;

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== DISCOVERY_ALARM_NAME) return;
  void runDiscoveryTick();
});

async function runDiscoveryTick() {
  if (discoveryRunInFlight) return;
  // Серверный аварийный стоп автопросмотра (рантайм-конфиг расширения) — поверх per-account.
  if (!getFlag('discovery_enabled')) return;
  discoveryRunInFlight = true;
  try {
    await ensureConfig();
    const deps = createDiscoveryDeps({ apiFetch, apiUrl, apiHeaders });
    await runDiscoveryCycle(deps);
  } catch (err) {
    reportExtHttpFailure('discovery_tick', 0, err?.message);
  } finally {
    discoveryRunInFlight = false;
  }
}

// Конфиг hh-селекторов + рантайм-конфиг расширения (флаги/тюнинг/селекторы отклика) — раз в
// 30 минут из SW в chrome.storage.local; content-script читает оттуда.
const CONFIG_REFRESH_ALARM_NAME = 'hh_selectors_refresh';
const CONFIG_REFRESH_TICK_MINUTES = 30;

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== CONFIG_REFRESH_ALARM_NAME) return;
  void fetchSelectorsFromApi();
  void refreshRuntimeConfig();
});

/** Свести периоды alarm'ов к желаемым из рантайм-конфига. Звать на старте воркера И после
 *  загрузки свежего конфига — reconcileRecurringAlarms трогает alarm только если период
 *  реально изменился, лишних сбросов таймера нет (см. schedule-alarms.ts). */
function reconcileAlarms(): void {
  const tuning = getRuntimeConfig().tuning;
  reconcileRecurringAlarms(chrome.alarms, [
    { name: AUTO_APPLY_ALARM_NAME, periodInMinutes: tuning.auto_apply_tick_minutes },
    { name: DISCOVERY_ALARM_NAME, periodInMinutes: tuning.discovery_tick_minutes },
    { name: CONFIG_REFRESH_ALARM_NAME, periodInMinutes: CONFIG_REFRESH_TICK_MINUTES },
  ]);
}

async function refreshRuntimeConfig(): Promise<void> {
  try {
    await ensureConfig();
    await fetchRuntimeConfigFromApi({
      onHttpError: (status) =>
        reportExtHttpFailure(
          'extension_runtime_config',
          status,
          'рантайм-конфиг не обновился — работаем на кэше/дефолте, kill-switch-флаги могут быть устаревшими',
        ),
    });
    reconcileAlarms();
  } catch (err) {
    reportExtHttpFailure('extension_runtime_config', 0, err?.message);
  }
}

// Старт воркера: сначала alarm'ы по дефолтным/закэшированным периодам (не ждём сети), затем
// подтягиваем свежий конфиг и, если период сменился, пересводим.
reconcileAlarms();
void fetchSelectorsFromApi();
void refreshRuntimeConfig();

