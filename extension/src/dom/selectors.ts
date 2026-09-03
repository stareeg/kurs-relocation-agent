/**
 * data-qa селекторы и парсинг HH (страница вакансии, SERP, тип URL).
 * Reference: legacy/autosend-letters-hh/config/selectors.js, jobUrls.js
 */
import { competitionLevel } from '../../../shared/criteria'
import { matchesTextSignal } from './extension-runtime-config'
import { getSelectors, type HhSelectorPack } from './selectors-config'
import { parseVacancyStructural } from './selectors-structural'

/** Тип страницы hh.ru (для routing extension / batch позже). */
const HH_PAGE_TYPE = {
  VACANCY: 'vacancy',
  SEARCH: 'search',
  VACANCIES: 'vacancies',
  EMPLOYER: 'employer',
  NEGOTIATIONS: 'negotiations',
  NEGOTIATION_THREAD: 'negotiation_thread',
  RESUMES: 'resumes',
  RESUME_HISTORY: 'resume_history',
  STATS_INDEX: 'stats_index',
  OTHER: 'other',
};

/** Паттерны URL (как JOB_URLS в autosend). */
const HH_URL_HINTS = {
  vacancy: '/vacancy/',
  search: '/search/vacancy',
  vacancies: '/vacancies',
  employer: '/employer/',
  negotiations: '/applicant/negotiations',
};

const _CITY_COUNTRY_SKIP = new Set(['россия', 'рф', 'russia', 'беларусь', 'казахстан']);
const _CITY_STREET_HINTS =
  /ул\.|улица|просп|пер\.|наб\.|аллея|шоссе|бульвар|пр-д|проезд|дом|д\.|корп|стр\.|площадь/i;

function _looksLikeStreetPart(part) {
  const p = String(part || '').trim();
  if (!p) return true;
  if (_CITY_STREET_HINTS.test(p)) return true;
  if (/\d/.test(p) && p.length > 12) return true;
  return /^\d+[\w/]*$/i.test(p);
}

function _looksLikeMetroPart(part, index) {
  if (index === 0) return false;
  const low = String(part).toLowerCase().replace(/ё/g, 'е');
  if (/^м\.?\s/.test(low) || low.includes('метро')) return true;
  if (_looksLikeStreetPart(part)) return false;
  if (part.length <= 25 && !/\d/.test(part)) return true;
  if (part.includes(' ') && !_looksLikeStreetPart(part)) return true;
  return false;
}

/** Город из строки локации HH (первый сегмент адреса, без метро/улицы). */
function parseCityFromArea(text) {
  const raw = String(text || '').trim().replace(/\s+/g, ' ');
  if (!raw) return '';
  const low = raw.toLowerCase().replace(/ё/g, 'е');
  if (/удален|remote|не имеет значения|любой город|дистанц|без привязки/.test(low)) {
    return '';
  }
  let cityPart = raw.replace(/,?\s*(?:м\.|метро)\s+[^,]+/gi, '').trim();
  if (!cityPart.includes(',')) return cityPart;

  const parts = cityPart.split(',').map((p) => p.trim()).filter(Boolean);
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i];
    const token = p.toLowerCase().replace(/ё/g, 'е');
    if (_CITY_COUNTRY_SKIP.has(token)) continue;
    if (_looksLikeStreetPart(p)) continue;
    if (_looksLikeMetroPart(p, i)) continue;
    if (p.length >= 2 && !/^\d+$/.test(p)) return p;
  }
  for (const p of parts) {
    const token = p.toLowerCase().replace(/ё/g, 'е');
    if (_CITY_COUNTRY_SKIP.has(token) || _looksLikeStreetPart(p)) continue;
    if (p.length >= 2) return p;
  }
  return parts[0] || '';
}

/** Адрес из блока «Где предстоит работать» (без узлов метро в DOM). */
function parseVacancyRawAddress(root = document) {
  const el =
    root.querySelector('[data-qa="vacancy-view-raw-address"]') ||
    root.querySelector('[data-qa="vacancy-address-with-map"]');
  if (!el) return '';
  const clone = el.cloneNode(true) as Element;
  clone
    .querySelectorAll(
      '.metro-station, [data-qa="address-metro-station-name"], .bloko-metro-pin'
    )
    .forEach((node) => node.remove());
  return (clone.textContent || '').replace(/\s+/g, ' ').trim();
}

const DEFAULT_HH_SELECTORS = {
  // —— Страница вакансии ——
  title: '[data-qa="vacancy-title"]',
  company: '[data-qa="vacancy-company-name"]',
  salary: '[data-qa="vacancy-salary"]',
  description: '[data-qa="vacancy-description"]',
  schedule: '[data-qa="vacancy-hiring-formats"]',
  remote: '[data-qa="vacancy-label-work-schedule-remote"]',
  // —— Новый magritte-хедер условий (hh 2025-2026): отдельные строки ——
  // ВАЖНО: «Формат работы: удалённо/гибрид/на месте» живёт здесь, а НЕ в schedule
  // (там на новом хедере «Оформление: Трудовой договор»). Без этого скоринг не видел удалёнку.
  workFormat: '[data-qa="work-formats-text"]',
  employmentText: '[data-qa="common-employment-text"]',
  scheduleByDays: '[data-qa="work-schedule-by-days-text"]',
  workingHours: '[data-qa="working-hours-text"]',
  experienceText: '[data-qa="vacancy-experience"]',
  address: '[data-qa="vacancy-view-raw-address"]',
  addressMap: '[data-qa="vacancy-address-with-map"]',
  // —— Сопроводительное / отклик (A6, cover_letter_spec) ——
  addCoverLetter: '[data-qa="vacancy-response-letter-toggle-text"]',
  addCoverLetterPopup: '[data-qa="add-cover-letter"]',
  coverLetterInput: '#cover-letter textarea',
  coverLetterInputPopup: '[data-qa="vacancy-response-popup-form-letter-input"]',
  modalOverlay: '[data-qa="modal-overlay"]',
  // Уже откликались (блок рядом с кнопкой отклика, magritte 2025–2026)
  alreadyApplied: '[data-qa="vacancy-response-link-viewed"]',
  archiveDescription: '[data-qa="vacancy-archive-description"]',
  archiveHeader: 'h2[data-qa="bloko-header-2"]',
  // Число откликов (A5) — HH меняет data-qa, есть text/embedded fallback
  responsesCount: '[data-qa="vacancy-view-responses-count"]',
  responsesInfo: '[data-qa="vacancy-response-info"]',
};

/** Тексты/узлы «отклик уже отправлен» на странице вакансии. */
// Подстроки «уже откликнулись» — из `text_signals.hh.already_applied` (рантайм-конфиг
// расширения, зашитый дефолт смержен), правится с сервера без переустановки zip.
const hhTextSaysApplied = (text: string) =>
  matchesTextSignal('hh', 'already_applied', text);

/** Парсинг «N откликов» из короткого текста (не из описания вакансии). */
const HH_RESPONSES_TEXT_RES = [
  /(?:уже\s+)?(\d[\d\s\u00a0]*)\s+отклик(?:ов|а|у)?(?:\s+на\s+вакансию)?/i,
  /(\d[\d\s\u00a0]*)\s+человек(?:а)?\s+уже\s+отклик/i,
  /(\d[\d\s\u00a0]*)\s+человек(?:а)?\s+откликнул/i,
  /откликов[:\s]+(\d[\d\s\u00a0]*)/i,
  /(?:более|менее)\s+(\d[\d\s\u00a0]*)\s+отклик/i,
];

/** SERP: список вакансий (поиск / подборки). */
const DEFAULT_HH_SERP_SELECTORS = {
  vacancyCard: '[data-qa="vacancy-serp__vacancy"]',
  title: '[data-qa="serp-item__title"]',
  titleLink: '[data-qa="serp-item__title"] a',
  employer: '[data-qa="vacancy-serp__vacancy-employer"]',
  employerLink: 'a[data-qa="vacancy-serp__vacancy-employer"]',
  salary: '[data-qa="compensation"]',
  address: '[data-qa="vacancy-serp__vacancy-address"]',
  metro: '[data-qa="vacancy-serp__vacancy-metro"]',
  respondBtn: '[data-qa="vacancy-serp__vacancy_response"]',
  pagerNext: '[data-qa="pager-next"]',
};

/** Кнопки отклика (страница вакансии + карточка SERP). */
const DEFAULT_HH_RESPONSE_LINK_SELECTORS = [
  '[data-qa="vacancy-response-link-top"]',
  '[data-qa="vacancy-response-link-bottom"]',
  '[data-qa="vacancy-response-link"]',
  DEFAULT_HH_SERP_SELECTORS.respondBtn,
];

/** Запасные CSS-селекторы если HH поменяет data-qa. */
const DEFAULT_HH_FALLBACKS = {
  title: [
    'h1[data-qa="vacancy-title"]',
    'h1.vacancy-title',
    '[class*="vacancy-title"]',
    'h1',
  ],
  company: [
    '[data-qa="vacancy-company-name"]',
    'a[data-qa="vacancy-company-name"]',
    '[data-qa="vacancy-company"] a',
    '.vacancy-company-name a',
    '.vacancy-company-name',
    'a[class*="companyName"]',
    '[class*="employerName"]',
  ],
  salary: [
    '[data-qa="vacancy-salary"]',
    '[data-qa="compensation"]',
    '[class*="vacancy-salary"]',
  ],
  description: [
    '[data-qa="vacancy-description"]',
    '.vacancy-description',
    '.vacancy-branded-user-content',
  ],
  serpTitleLink: ['a[href*="/vacancy/"]'],
  serpEmployer: ['[data-qa="vacancy-serp__vacancy-employer"]', '[class*="vacancy-serp__employer"]'],
  serpSalary: ['[data-qa="compensation"]', '[class*="compensation"]'],
};

function queryElIn(root, selectors) {
  const list = Array.isArray(selectors) ? selectors : [selectors];
  for (const sel of list) {
    try {
      const el = root.querySelector(sel);
      if (el && el.innerText && el.innerText.trim()) return el;
    } catch {
      /* неверный селектор */
    }
  }
  return null;
}

function queryEl(selectors) {
  return queryElIn(document, selectors);
}

function queryText(selectors, root = document) {
  const el = queryElIn(root, selectors);
  return el ? el.innerText.trim() : '';
}

function queryAllIn(root, selector): HTMLElement[] {
  try {
    return Array.from(root.querySelectorAll(selector));
  } catch {
    return [];
  }
}

function extractVacancyId(url) {
  const str = String(url || '');
  const pathMatch = str.match(/\/vacancy\/(\d+)/);
  if (pathMatch) return pathMatch[1];
  // /applicant/vacancy_response?vacancyId=... — форма отклика, куда HH иногда уводит вместо
  // AJAX-отклика на месте (доп. вопрос при отклике); id вакансии тут только в query.
  const queryMatch = str.match(/[?&]vacancyId=(\d+)/);
  return queryMatch ? queryMatch[1] : null;
}

/** Числовой ID переписки (nid) из href вида /negotiations/123 или /negotiations/active/123. */
function extractNegotiationId(url) {
  const m = String(url || '').match(/\/negotiations\/(?:active\/)?(\d+)/);
  return m ? m[1] : null;
}

function extractEmployerIdFromHref(href) {
  const m = String(href || '').match(/\/employer\/(\d+)/);
  return m ? m[1] : null;
}

function extractEmployerId(root = document) {
  const links = root.querySelectorAll('a[href*="/employer/"]');
  for (const link of links) {
    const id = extractEmployerIdFromHref((link as HTMLAnchorElement).href);
    if (id) return id;
  }
  return null;
}

/**
 * Тип страницы по URL (SPA-safe: передавать location.href).
 * @returns {typeof HH_PAGE_TYPE[keyof typeof HH_PAGE_TYPE]}
 */
function isNegotiationsPath(url = location.href) {
  try {
    const path = new URL(String(url), 'https://hh.ru').pathname;
    return (
      path === '/applicant/negotiations' ||
      path.startsWith('/applicant/negotiations/')
    );
  } catch {
    const base = String(url).split('#')[0];
    return /\/applicant\/negotiations(?:\/|$|\?)/.test(base);
  }
}

/**
 * EX-9: индивидуальный тред (`/applicant/negotiations/<id>` или `/negotiations/active/<id>`) — в
 * отличие от списка (`/applicant/negotiations`, опц. `?page=N`). Тот же числовой хвост, что и в
 * `extractNegotiationId` (ссылки на тред из карточек списка).
 */
function isNegotiationThreadPath(url = location.href) {
  try {
    const path = new URL(String(url), 'https://hh.ru').pathname;
    return /^\/applicant\/negotiations\/(?:active\/)?\d+\/?$/.test(path);
  } catch {
    const base = String(url).split('#')[0].split('?')[0];
    return /\/applicant\/negotiations\/(?:active\/)?\d+\/?$/.test(base);
  }
}

/**
 * Подтип кабинета соискателя: статистика резюме (AF-2). null — не resume-страница.
 * `/applicant/resumes` — список резюме со сводными счётчиками (легаси-вёрстка);
 * `/applicant/profile/me` — та же статистика («Статистика за неделю») переехала сюда (hh 2026-07);
 * `/applicant/resumeview/history` (и `/resumeview`) — история просмотров.
 */
function getResumePageType(url = location.href) {
  let path;
  try {
    path = new URL(String(url), 'https://hh.ru').pathname;
  } catch {
    path = String(url).split('#')[0].split('?')[0];
  }
  if (/^\/applicant\/resumeview/.test(path)) return HH_PAGE_TYPE.RESUME_HISTORY;
  if (path === '/applicant/resumes' || path.startsWith('/applicant/resumes/')) {
    return HH_PAGE_TYPE.RESUMES;
  }
  if (path === '/applicant/profile/me' || path === '/applicant/profile') {
    return HH_PAGE_TYPE.RESUMES;
  }
  return null;
}

/**
 * E-03: `stats.hh.ru` — отдельный поддомен-SPA (страница почти без пути), в отличие от остальных
 * типов (различаются по pathname на `hh.ru`) — здесь смотрим hostname, не путь.
 */
function isStatsHost(url = location.href) {
  try {
    return new URL(String(url), 'https://hh.ru').hostname.toLowerCase() === 'stats.hh.ru';
  } catch {
    return /^https?:\/\/stats\.hh\.ru(?:[/?#]|$)/i.test(String(url));
  }
}

/** Форма «доп. вопрос при отклике» (/applicant/vacancy_response) — getHhPageType() трактует её
 *  как HH_PAGE_TYPE.VACANCY (иначе панель/чат гаснут посреди отклика), но разметка тут не
 *  вакансийная: специфичных селекторов title/description на ней нет, и общий фолбэк `h1` в
 *  HH_FALLBACKS.title подхватывает заголовок формы («Отклик на вакансию») вместо названия
 *  вакансии. main.ts использует этот флаг, чтобы на такой странице не сверять DOM-заголовок с
 *  кэшем (ложный мисматч гасил валидный скор — «мёртвый путь», FR2-79) и не запускать
 *  автоскоринг/rescore по мусорному парсу (тут просто нет текста JD). */
function isVacancyResponseFormPage(url = location.href) {
  return /\/applicant\/vacancy_response/.test(String(url));
}

/** Тип страницы hh.ru (GM-4: для мультисайта используй site-router.resolveRoute). */
function getHhPageType(url = location.href) {
  const href = String(url);
  if (isStatsHost(href)) return HH_PAGE_TYPE.STATS_INDEX;
  if (/\/vacancy\/\d+/.test(href)) return HH_PAGE_TYPE.VACANCY;
  // Форма отклика с доп. вопросом уводит на отдельную страницу той же вакансии (id только в
  // query) — считаем её вакансией, иначе панель/чат обнуляются посреди отклика.
  if (isVacancyResponseFormPage(href) && /[?&]vacancyId=\d+/.test(href)) {
    return HH_PAGE_TYPE.VACANCY;
  }
  if (isNegotiationsPath(href)) {
    return isNegotiationThreadPath(href)
      ? HH_PAGE_TYPE.NEGOTIATION_THREAD
      : HH_PAGE_TYPE.NEGOTIATIONS;
  }
  const resumeType = getResumePageType(href);
  if (resumeType) return resumeType;
  if (href.includes(HH_URL_HINTS.search)) return HH_PAGE_TYPE.SEARCH;
  if (/\/vacancies(?:\/|\?|$)/.test(href) || href.includes(HH_URL_HINTS.vacancies)) {
    return HH_PAGE_TYPE.VACANCIES;
  }
  if (/\/employer\/\d+/.test(href)) return HH_PAGE_TYPE.EMPLOYER;
  return HH_PAGE_TYPE.OTHER;
}

/** @deprecated hh-only; для dock — resolveRoute() из site-router */
const getPageType = getHhPageType;

function isNegotiationsPage(url = location.href) {
  return isNegotiationsPath(url);
}

/** Номер страницы списка откликов HH (?page=0 — первая, ?page=1 — вторая…). */
function getNegotiationsPageIndex(url = location.href) {
  try {
    const u = new URL(String(url), 'https://hh.ru');
    const raw = u.searchParams.get('page');
    if (raw === null || raw === '') return 0;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    const m = String(url).match(/[?&]page=(\d+)/);
    return m ? Math.max(0, parseInt(m[1], 10)) : 0;
  }
}

/** Ключ страницы для SPA-навигации (pathname + page). */
function negotiationsPageKey(url = location.href) {
  try {
    const u = new URL(String(url), 'https://hh.ru');
    return `${u.pathname}|page=${getNegotiationsPageIndex(url)}`;
  } catch {
    return `${String(url).split('#')[0]}|page=${getNegotiationsPageIndex(url)}`;
  }
}

function isVacancyPage(url = location.href) {
  return getHhPageType(url) === HH_PAGE_TYPE.VACANCY;
}

function isSearchPage(url = location.href) {
  const t = getHhPageType(url);
  return t === HH_PAGE_TYPE.SEARCH || t === HH_PAGE_TYPE.VACANCIES;
}

function isSerpPage(url = location.href) {
  return isSearchPage(url);
}

/**
 * Эвристики по тексту карточки SERP (бейджи HH меняются — не только data-qa).
 */
function serpCardTextHints(cardEl) {
  const t = (cardEl.innerText || '').toLowerCase();
  return {
    letter_required_hint: /сопроводител/.test(t),
    already_responded_hint: /вы\s+отклик|отклик\s+отправлен|откликнулись|уже\s+отклик/i.test(t),
  };
}

/**
 * DOM: обязательное сопроводительное на странице вакансии (не отправка — только детект).
 */
/**
 * HH показывает «Вы откликнулись» после отправки отклика (read-only детект).
 */
function detectAlreadyAppliedOnPage(root = document, sel: HhSelectorPack = getSelectors()) {
  const HH_SELECTORS = sel.vacancy;
  // Авторитетный сигнал ТЕКУЩЕЙ вакансии: hh рисует vacancy-response-link-viewed в блоке отклика
  // именно этой вакансии. Самый надёжный признак — проверяем первым.
  if (queryElIn(root, [HH_SELECTORS.alreadyApplied])) {
    return true;
  }

  // Текстовый фолбэк (на случай смены data-qa) — ТОЛЬКО внутри блока отклика текущей вакансии.
  // Раньше скан шёл по main/document и ловил «Вы откликнулись» из блоков «Похожие вакансии» →
  // ложный «Отклик» на свежей вакансии (фантомная запись по чужому ID, статус прилипал навсегда).
  // Скоупим строго на [data-qa="vacancy-response"]; нет его — доверяем backend-трекингу по ID.
  const scope = root.querySelector('[data-qa="vacancy-response"]');
  if (!scope) return false;

  const nodes = scope.querySelectorAll('[class*="magritte-text"], [data-qa*="response"]');
  for (const el of nodes) {
    const t = ((el as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 80) continue;
    if (hhTextSaysApplied(t)) return true;
  }

  return false;
}

function parseResponsesCountFromText(text) {
  if (!text) return null;
  const t = String(text).replace(/\s+/g, ' ').trim();
  if (t.length > 500) return null;
  for (const re of HH_RESPONSES_TEXT_RES) {
    const m = t.match(re);
    if (!m) continue;
    const digits = m[1].replace(/[\s\u00a0]/g, '');
    const n = parseInt(digits, 10);
    if (Number.isFinite(n) && n >= 0 && n < 1_000_000) return n;
  }
  return null;
}

/**
 * Embedded state на странице (без HTTP API): totalResponsesCount в <script>.
 */
function parseResponsesFromEmbeddedState(root = document, vacancyId = null) {
  const scripts = root.querySelectorAll('script:not([src])');
  for (const script of scripts) {
    const raw = script.textContent || '';
    if (!raw.includes('totalResponsesCount')) continue;

    if (vacancyId) {
      const idPatterns = [
        `"id":${vacancyId}`,
        `"id":"${vacancyId}"`,
        `"vacancyId":${vacancyId}`,
        `"vacancyId":"${vacancyId}"`,
      ];
      for (const pat of idPatterns) {
        const idx = raw.indexOf(pat);
        if (idx < 0) continue;
        const slice = raw.slice(idx, idx + 4000);
        const m = slice.match(/"totalResponsesCount"\s*:\s*(\d+)/);
        if (m) return parseInt(m[1], 10);
      }
    }

    const global = raw.match(/"totalResponsesCount"\s*:\s*(\d+)/);
    if (global) return parseInt(global[1], 10);
  }
  return null;
}

/**
 * Число откликов на вакансию (DOM + embedded JSON). null если не найдено.
 */
function parseResponsesCount(root = document, vacancyId = null, sel: HhSelectorPack = getSelectors()) {
  const HH_SELECTORS = sel.vacancy;
  const vid = vacancyId || extractVacancyId(location.href);

  for (const sel of [HH_SELECTORS.responsesCount, HH_SELECTORS.responsesInfo]) {
    const el = queryElIn(root, [sel]);
    if (el) {
      const n = parseResponsesCountFromText(el.innerText || '');
      if (n != null) return n;
    }
  }

  const scopes = [
    root.querySelector('[data-qa="vacancy-response"]'),
    root.querySelector('[data-qa="vacancy-view"]'),
    root.querySelector('[data-qa="vacancy-actions"]'),
    root.querySelector('[class*="vacancy-action"]'),
  ].filter(Boolean);

  for (const scope of scopes) {
    const nodes = scope.querySelectorAll(
      '[class*="magritte-text"], [data-qa*="response"], [data-qa*="vacancy"]'
    );
    for (const el of nodes) {
      const t = ((el as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim();
      if (!t || t.length > 120) continue;
      const n = parseResponsesCountFromText(t);
      if (n != null) return n;
    }
    const nScope = parseResponsesCountFromText((scope as HTMLElement).innerText || '');
    if (nScope != null) return nScope;
  }

  const embedded = parseResponsesFromEmbeddedState(root, vid);
  if (embedded != null) return embedded;

  return null;
}

/** Дата публикации снизу страницы («Вакансия опубликована 21 мая 2026 …»). */
/** HH: блок «Вакансия в архиве» — отклики не принимаются. */
function detectVacancyArchived(root = document, sel: HhSelectorPack = getSelectors()) {
  const HH_SELECTORS = sel.vacancy;
  const desc = root.querySelector(HH_SELECTORS.archiveDescription);
  if (desc && (desc.textContent || '').trim()) {
    return true;
  }
  const headers = root.querySelectorAll(HH_SELECTORS.archiveHeader);
  for (const el of headers) {
    if (/вакансия\s+в\s+архиве/i.test((el.textContent || '').trim())) {
      return true;
    }
  }
  return Array.from(root.querySelectorAll('h2, h3')).some((el) =>
    /вакансия\s+в\s+архиве/i.test((el.textContent || '').trim())
  );
}

function parseVacancyPublishedAt(root = document) {
  const publishedRe =
    /(?:вакансия\s+)?опубликован[аоы]?\s+(\d{1,2}\s+[\p{L}]{3,}\s+\d{4})/iu;
  const nodes = root.querySelectorAll(
    '[class*="magritte-text_style-secondary"], [data-qa="vacancy-creation-time"]'
  );
  for (const el of nodes) {
    const text = ((el as HTMLElement).innerText || el.textContent || '').replace(/\u00a0/g, ' ');
    const m = text.match(publishedRe);
    if (m) return m[1].trim();
  }
  const bodyText = (root.body?.innerText || '').replace(/\u00a0/g, ' ');
  const mBody = bodyText.match(publishedRe);
  return mBody ? mBody[1].trim() : null;
}

// E-03: живая проверка hh.ru (2026-08-18) — все DOM-маркеры ниже (toggle/input/попап) рендерятся
// только ВНУТРИ модалки «Откликнуться», которой на пассивной странице вакансии (до клика) в DOM
// просто нет — поэтому на 329 живых вакансиях детектор молчал не потому, что письмо не требуется,
// а потому что смотрел не в то место. Добавлен текстовый эвристик по описанию вакансии — тот же
// приём, что serpCardTextHints даёт карточкам SERP.
function detectLetterRequired(root = document, sel: HhSelectorPack = getSelectors()) {
  const HH_SELECTORS = sel.vacancy;
  const HH_FALLBACKS = sel.fallbacks;
  if (
    queryElIn(root, [HH_SELECTORS.addCoverLetter, HH_SELECTORS.addCoverLetterPopup])
  ) {
    return true;
  }
  if (queryElIn(root, [HH_SELECTORS.coverLetterInput, HH_SELECTORS.coverLetterInputPopup])) {
    return true;
  }
  const responseBlock = root.querySelector('[data-qa="vacancy-response"]');
  if (responseBlock && /сопроводител/i.test((responseBlock as HTMLElement).innerText || '')) {
    return true;
  }
  const description = queryText([HH_SELECTORS.description, ...(HH_FALLBACKS.description || [])], root);
  if (description && /сопроводител/i.test(description)) {
    return true;
  }
  return false;
}

/**
 * Метаданные одной карточки SERP.
 * @param {Element} cardEl — узел [data-qa="vacancy-serp__vacancy"]
 */
function parseSerpCard(cardEl, sel: HhSelectorPack = getSelectors()) {
  const HH_SERP_SELECTORS = sel.serp;
  const HH_FALLBACKS = sel.fallbacks;
  if (!cardEl) return null;

  const titleLink =
    cardEl.querySelector(HH_SERP_SELECTORS.titleLink) ||
    queryElIn(cardEl, HH_FALLBACKS.serpTitleLink);
  const href = titleLink?.href || '';
  const vacancy_id = extractVacancyId(href);
  if (!vacancy_id) return null;

  const title =
    queryText([HH_SERP_SELECTORS.title], cardEl) ||
    (titleLink?.innerText?.trim() || '');
  const employerLink =
    cardEl.querySelector(HH_SERP_SELECTORS.employerLink) ||
    queryElIn(cardEl, HH_FALLBACKS.serpEmployer);
  const company =
    queryText([HH_SERP_SELECTORS.employer, HH_SERP_SELECTORS.employerLink], cardEl) ||
    queryText(HH_FALLBACKS.serpEmployer, cardEl);
  const employer_id =
    extractEmployerIdFromHref(employerLink?.href) || extractEmployerId(cardEl);
  const salary =
    queryText([HH_SERP_SELECTORS.salary], cardEl) ||
    queryText(HH_FALLBACKS.serpSalary, cardEl);
  const location =
    queryText([HH_SERP_SELECTORS.address, HH_SERP_SELECTORS.metro], cardEl);

  const hints = serpCardTextHints(cardEl);
  const respondBtn = cardEl.querySelector(HH_SERP_SELECTORS.respondBtn);
  const cardText = (cardEl.innerText || '').slice(0, 400);
  const total_responses_count = parseResponsesCountFromText(cardText);

  return {
    vacancy_id,
    title,
    company,
    salary,
    location,
    url: href.split('?')[0],
    letter_required_hint: hints.letter_required_hint,
    letter_required: hints.letter_required_hint,
    already_responded_hint: hints.already_responded_hint || (respondBtn?.disabled === true),
    area: parseCityFromArea(location),
    work_schedule: '',
    employer_id,
    total_responses_count,
    competition: competitionLevel(total_responses_count),
    source: 'serp',
    el: cardEl,
  };
}

/** Все карточки на текущей SERP-странице. */
function parseSerpCardsFromDom(root: Document | Element = document, sel: HhSelectorPack = getSelectors()) {
  const HH_SERP_SELECTORS = sel.serp;
  const cards = queryAllIn(root, HH_SERP_SELECTORS.vacancyCard);
  const out = [];
  for (const card of cards) {
    const meta = parseSerpCard(card, sel);
    if (meta) out.push(meta);
  }
  return out;
}

/** Известные data-qa строки «Найдено N вакансий» над выдачей — вёрстка этого блока меняется
 *  чаще карточек, поэтому есть текстовый фолбэк ниже (тот же приём, что `_findResumeStatsScope`). */
const HH_SERP_FOUND_GUESSES = [
  '[data-qa="vacancies-search-header"]',
  '[data-qa*="search-header"]',
  'h1[data-qa="bloko-header-1"]',
];

/** Наименьший узел с «найдено» + «вакан» рядом — чтобы не подцепить число из чужого блока. */
function _findSerpFoundScope(root = document) {
  for (const sel of HH_SERP_FOUND_GUESSES) {
    const el = root.querySelector?.(sel);
    if (el && /вакан/i.test(el.textContent || '')) return el;
  }
  let best = null;
  for (const el of queryAllIn(root, 'h1, div, span, p')) {
    const t = el.textContent || '';
    if (t.length > 200) continue;
    if (/найдено/i.test(t) && /вакан/i.test(t)) {
      if (!best || t.length < (best.textContent || '').length) best = el;
    }
  }
  return best;
}

/** «Найдено 1 234 вакансии» → 1234. null — блока нет на странице (SPA ещё не дорисовала). */
function parseSerpFoundCountFromDom(root = document) {
  const scope = _findSerpFoundScope(root);
  if (!scope) return null;
  const text = (scope.innerText || scope.textContent || '').replace(/ /g, ' ');
  const m = text.match(/(\d[\d ]*\d|\d)\s*вакан/i);
  return m ? _resumeStatInt(m[1]) : null;
}

/** Поисковый запрос из URL выдачи (`?text=`). Нормализация регистра/пробелов — на бэке. */
function parseSerpQueryFromUrl(url = location.href) {
  try {
    const u = new URL(String(url), 'https://hh.ru');
    return (u.searchParams.get('text') || '').trim();
  } catch {
    return '';
  }
}

/**
 * Показание спроса (E-01, план п.2.6.1): сколько вакансий нашлось по текущему запросу.
 * null — запрос пустой (страница `/vacancies` без `text=` не самостоятельный поиск) или счётчик
 * ещё не дорисован.
 */
function parseSerpDemandFromDom(root = document, url = location.href) {
  const query = parseSerpQueryFromUrl(url);
  if (!query) return null;
  const count = parseSerpFoundCountFromDom(root);
  if (count == null) return null;
  return { query, count };
}

/**
 * Парсит заголовок и компанию из document.title.
 */
function parseTitleFromDocumentTitle() {
  const t = document.title;

  let m = t.match(/^(?:Вакансия\s+)?(.+?)\s+в\s+.+?,\s*работа в компании\s+(.+?)(?:\s*[—–-].*)?$/i);
  if (m) return { title: m[1].trim(), company: m[2].trim() };

  m = t.match(/^(.+?)\s*[—–-]\s*(.+?)\s*[—–-]\s*hh\.ru/i);
  if (m) return { title: m[1].trim(), company: m[2].trim() };

  return null;
}

/** Статусы HH «Мои отклики» (нормализация для backend). */
const HH_NEGOTIATION_STATUS = {
  UNKNOWN: 'unknown',
  NOT_VIEWED_BY_EMPLOYER: 'not_viewed_by_employer',
  VIEWED_BY_EMPLOYER: 'viewed_by_employer',
  REJECTED: 'rejected',
  HH_INTERVIEW_STAGE: 'hh_interview_stage',
  INVITATION: 'invitation',
};

const DEFAULT_HH_NEGOTIATIONS_SELECTORS = {
  card: [
    '[data-qa="negotiations-item"]',
    '[data-qa="negotiations__item"]',
    '[data-qa="negotiation-item"]',
    'article[data-qa*="negotiation"]',
  ],
  titleLink: 'a[href*="/vacancy/"]',
  company: [
    '[data-qa="negotiations-item-company"]',
    '[data-qa="negotiations-item__company"]',
    '[data-qa="vacancy-serp__vacancy-employer"]',
    'a[href*="/employer/"]',
  ],
  statusBadge: [
    '[data-qa="negotiations-item-status"]',
    '[data-qa="negotiation-status"]',
    '[data-qa*="employer-state"]',
    '[data-qa*="negotiation-status"]',
  ],
  date: '[data-qa="negotiations-item-date"], time',
  lastMessage: [
    '[data-qa="negotiations-item-message"]',
    '[data-qa*="message-preview"]',
    '[data-qa*="last-message"]',
  ],
};

const HH_NEGOTIATION_STATUS_RES = [
  [/не\s+просмотрен/i, HH_NEGOTIATION_STATUS.NOT_VIEWED_BY_EMPLOYER],
  [/отказ/i, HH_NEGOTIATION_STATUS.REJECTED],
  [/собеседован/i, HH_NEGOTIATION_STATUS.HH_INTERVIEW_STAGE],
  [/приглаш/i, HH_NEGOTIATION_STATUS.INVITATION],
  [/просмотрен/i, HH_NEGOTIATION_STATUS.VIEWED_BY_EMPLOYER],
  [/отклик/i, HH_NEGOTIATION_STATUS.NOT_VIEWED_BY_EMPLOYER],
] as const;

function normalizeHhNegotiationStatus(rawText, employerStateId = null) {
  if (employerStateId) {
    const id = String(employerStateId).trim().toLowerCase();
    const idMap = {
      response: HH_NEGOTIATION_STATUS.NOT_VIEWED_BY_EMPLOYER,
      consider: HH_NEGOTIATION_STATUS.VIEWED_BY_EMPLOYER,
      discard: HH_NEGOTIATION_STATUS.REJECTED,
      discard_by_employer: HH_NEGOTIATION_STATUS.REJECTED,
      discard_after_interview: HH_NEGOTIATION_STATUS.REJECTED,
      invitation: HH_NEGOTIATION_STATUS.INVITATION,
      interview: HH_NEGOTIATION_STATUS.HH_INTERVIEW_STAGE,
      phone_interview: HH_NEGOTIATION_STATUS.HH_INTERVIEW_STAGE,
      assessment: HH_NEGOTIATION_STATUS.HH_INTERVIEW_STAGE,
    };
    if (idMap[id]) return idMap[id];
  }
  const text = String(rawText || '').trim();
  if (!text) return HH_NEGOTIATION_STATUS.UNKNOWN;
  for (const [re, status] of HH_NEGOTIATION_STATUS_RES) {
    if (re.test(text)) return status;
  }
  return HH_NEGOTIATION_STATUS.UNKNOWN;
}

/** Preview маппинга для UI (дубль backend/schemas/negotiations.py). */
function mapHhStatusToFunnel(hhStatus, hasHrMessage = false) {
  const FS = {
    VIEWED: 'Просмотр',
    APPLIED: 'Отклик',
    REJECTED: 'Отказ',
    SCREENING: 'Скрининг',
    TECH: 'Техничка',
    OFFER: 'Оффер',
  };
  if (hhStatus === HH_NEGOTIATION_STATUS.REJECTED) {
    return { funnel_status: FS.REJECTED, needs_interview_tracking: false };
  }
  if (hhStatus === HH_NEGOTIATION_STATUS.HH_INTERVIEW_STAGE) {
    return { funnel_status: FS.SCREENING, needs_interview_tracking: true };
  }
  if (hhStatus === HH_NEGOTIATION_STATUS.INVITATION) {
    return { funnel_status: FS.SCREENING, needs_interview_tracking: false };
  }
  if (hhStatus === HH_NEGOTIATION_STATUS.VIEWED_BY_EMPLOYER) {
    return {
      funnel_status: hasHrMessage ? FS.SCREENING : FS.APPLIED,
      needs_interview_tracking: false,
    };
  }
  if (hhStatus === HH_NEGOTIATION_STATUS.NOT_VIEWED_BY_EMPLOYER) {
    return { funnel_status: FS.APPLIED, needs_interview_tracking: false };
  }
  return { funnel_status: FS.APPLIED, needs_interview_tracking: false };
}

function findNegotiationCardRoot(linkEl, sel: HhSelectorPack = getSelectors()) {
  const HH_NEGOTIATIONS_SELECTORS = sel.negotiations as typeof DEFAULT_HH_NEGOTIATIONS_SELECTORS;
  if (!linkEl) return null;
  for (const sel of HH_NEGOTIATIONS_SELECTORS.card) {
    const card = linkEl.closest(sel);
    if (card) return card;
  }
  return (
    linkEl.closest('article') ||
    linkEl.closest('[class*="negotiation"]') ||
    linkEl.closest('div[class*="magritte"]')?.parentElement ||
    linkEl.parentElement?.parentElement
  );
}

/**
 * hh magritte-теги статуса кодируют состояние прямо в `data-qa` (напр. пробел-разделённое
 * `data-qa="negotiations-tag negotiations-item-not-viewed"`), устойчивее к смене текста/локали,
 * чем regex по innerText (JS-9.1). Известен подтверждённый суффикс `not-viewed`; остальные —
 * по аналогии именования hh, с фоллбэком на текстовую эвристику при незнакомом суффиксе.
 */
const NEGOTIATION_ITEM_TAG_STATUS = {
  'not-viewed': HH_NEGOTIATION_STATUS.NOT_VIEWED_BY_EMPLOYER,
  viewed: HH_NEGOTIATION_STATUS.VIEWED_BY_EMPLOYER,
  discard: HH_NEGOTIATION_STATUS.REJECTED,
  rejected: HH_NEGOTIATION_STATUS.REJECTED,
  invitation: HH_NEGOTIATION_STATUS.INVITATION,
  interview: HH_NEGOTIATION_STATUS.HH_INTERVIEW_STAGE,
};

function extractNegotiationStatusFromTag(cardEl) {
  const tagged = cardEl.querySelectorAll('[data-qa*="negotiations-item-"]');
  for (const el of tagged) {
    const tokens = String(el.getAttribute('data-qa') || '').split(/\s+/);
    for (const token of tokens) {
      if (!token.startsWith('negotiations-item-')) continue;
      const suffix = token.slice('negotiations-item-'.length);
      if (NEGOTIATION_ITEM_TAG_STATUS[suffix]) return NEGOTIATION_ITEM_TAG_STATUS[suffix];
    }
  }
  return null;
}

function extractNegotiationStatusText(cardEl, sel: HhSelectorPack = getSelectors()) {
  const HH_NEGOTIATIONS_SELECTORS = sel.negotiations as typeof DEFAULT_HH_NEGOTIATIONS_SELECTORS;
  const badge = queryElIn(cardEl, HH_NEGOTIATIONS_SELECTORS.statusBadge);
  if (badge?.innerText?.trim()) return badge.innerText.trim();
  const t = (cardEl.innerText || '').replace(/\s+/g, ' ');
  for (const [re] of HH_NEGOTIATION_STATUS_RES) {
    const m = t.match(re);
    if (m) return m[0];
  }
  return '';
}

const RU_MONTH_PREFIXES = [
  ['янв', 0],
  ['фев', 1],
  ['мар', 2],
  ['апр', 3],
  ['мая', 4],
  ['май', 4],
  ['июн', 5],
  ['июл', 6],
  ['авг', 7],
  ['сен', 8],
  ['окт', 9],
  ['ноя', 10],
  ['дек', 11],
] as const;

function formatNegotiationDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Дата отклика с карточки HH → YYYY-MM-DD HH:MM для Sheets. */
function normalizeNegotiationAppliedAt(raw) {
  if (!raw || !String(raw).trim()) return null;
  const s = String(raw).trim().replace(/\u00a0/g, ' ');
  const low = s.toLowerCase();
  const now = new Date();
  if (low === 'сегодня' || low === 'today') return formatNegotiationDate(now);
  if (low === 'вчера' || low === 'yesterday') {
    const d = new Date(now);
    d.setDate(d.getDate() - 1);
    return formatNegotiationDate(d);
  }
  const dot = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (dot) {
    const d = new Date(
      Number(dot[3]),
      Number(dot[2]) - 1,
      Number(dot[1]),
      Number(dot[4] || 12),
      Number(dot[5] || 0),
    );
    if (!Number.isNaN(d.getTime())) return formatNegotiationDate(d);
  }
  const ru = s.match(/(\d{1,2})\s+([а-яёa-z]+)(?:\s+(\d{4}))?/i);
  if (ru) {
    const day = Number(ru[1]);
    const monTxt = ru[2].toLowerCase();
    const year = Number(ru[3] || now.getFullYear());
    let month = -1;
    for (const [prefix, m] of RU_MONTH_PREFIXES) {
      if (monTxt.startsWith(prefix)) {
        month = m;
        break;
      }
    }
    if (month >= 0) {
      const d = new Date(year, month, day, 12, 0);
      if (!Number.isNaN(d.getTime())) return formatNegotiationDate(d);
    }
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.replace('T', ' ').slice(0, 16);
  return s.slice(0, 19);
}

function _extractNegotiationIdFromCard(cardEl) {
  const links = cardEl.querySelectorAll('a[href*="/negotiations/"]');
  for (const link of links) {
    const nid = extractNegotiationId(link.href);
    if (nid) return nid;
  }
  return null;
}

function parseNegotiationCard(cardEl, sel: HhSelectorPack = getSelectors()) {
  const HH_NEGOTIATIONS_SELECTORS = sel.negotiations as typeof DEFAULT_HH_NEGOTIATIONS_SELECTORS;
  const HH_SERP_SELECTORS = sel.serp;
  const HH_FALLBACKS = sel.fallbacks;
  if (!cardEl) return null;

  const titleLink =
    cardEl.querySelector(HH_NEGOTIATIONS_SELECTORS.titleLink) ||
    queryElIn(cardEl, HH_FALLBACKS.serpTitleLink);
  const href = titleLink?.href || '';
  const vacancy_id = extractVacancyId(href);
  if (!vacancy_id) return null;

  const title =
    (titleLink?.innerText || '').trim() ||
    queryText([HH_SERP_SELECTORS.title], cardEl);
  const companyLink = queryElIn(cardEl, HH_NEGOTIATIONS_SELECTORS.company);
  const company =
    queryText(HH_NEGOTIATIONS_SELECTORS.company, cardEl) ||
    (companyLink?.innerText || '').trim();
  const hh_status_raw = extractNegotiationStatusText(cardEl, sel);
  const hh_status = extractNegotiationStatusFromTag(cardEl) || normalizeHhNegotiationStatus(hh_status_raw);
  const lastMessage = queryText(HH_NEGOTIATIONS_SELECTORS.lastMessage, cardEl);
  const applied_at = normalizeNegotiationAppliedAt(
    queryText([HH_NEGOTIATIONS_SELECTORS.date], cardEl),
  );
  const has_hr_message = Boolean(lastMessage && lastMessage.length > 3);
  const mapped = mapHhStatusToFunnel(hh_status, has_hr_message);
  const negotiation_id = _extractNegotiationIdFromCard(cardEl);

  return {
    vacancy_id,
    title,
    company,
    url: href.split('?')[0],
    hh_status_raw,
    hh_status,
    applied_at,
    last_message: lastMessage || null,
    employer_viewed: hh_status === HH_NEGOTIATION_STATUS.VIEWED_BY_EMPLOYER,
    funnel_status_preview: mapped.funnel_status,
    needs_interview_tracking: mapped.needs_interview_tracking,
    negotiation_id: negotiation_id || null,
    source: 'hh_negotiations',
  };
}

function parseNegotiationsFromEmbeddedState(root = document) {
  const scripts = root.querySelectorAll('script:not([src])');
  const items = [];
  const seen = new Set();

  for (const script of scripts) {
    const raw = script.textContent || '';
    if (!raw.includes('vacancy') || !raw.includes('employer')) continue;

    const vacancyMatches = raw.matchAll(/"id"\s*:\s*"?(\d{6,})"?/g);
    for (const vm of vacancyMatches) {
      const vacancy_id = vm[1];
      if (seen.has(vacancy_id)) continue;
      const idx = vm.index ?? 0;
      const slice = raw.slice(Math.max(0, idx - 500), idx + 2500);
      if (!slice.includes('vacancy') && !slice.includes('name')) continue;

      let employer_state_id = null;
      const stateM = slice.match(/"employer_state"\s*:\s*\{[^}]*"id"\s*:\s*"([^"]+)"/);
      if (stateM) employer_state_id = stateM[1];
      if (!employer_state_id) {
        const stateM2 = slice.match(/"employer_state"\s*:\s*"([^"]+)"/);
        if (stateM2) employer_state_id = stateM2[1];
      }

      let title = '';
      const nameM = slice.match(/"name"\s*:\s*"([^"]{3,120})"/);
      if (nameM) title = nameM[1];

      let company = '';
      const empM = slice.match(/"employer"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"/);
      if (empM) company = empM[1];

      let negotiation_id = null;
      const nidM = slice.match(/"nid"\s*:\s*"?(\d+)"?/);
      if (nidM) negotiation_id = nidM[1];
      if (!negotiation_id) {
        const urlM = slice.match(/\/negotiations\/(?:active\/)?(\d+)/);
        if (urlM) negotiation_id = urlM[1];
      }

      const hh_status = normalizeHhNegotiationStatus('', employer_state_id);
      const mapped = mapHhStatusToFunnel(hh_status, false);
      seen.add(vacancy_id);
      items.push({
        vacancy_id,
        title,
        company,
        url: `https://hh.ru/vacancy/${vacancy_id}`,
        hh_status_raw: employer_state_id || '',
        hh_status,
        applied_at: null,
        last_message: null,
        employer_viewed: hh_status === HH_NEGOTIATION_STATUS.VIEWED_BY_EMPLOYER,
        funnel_status_preview: mapped.funnel_status,
        needs_interview_tracking: mapped.needs_interview_tracking,
        employer_state_id,
        negotiation_id: negotiation_id || null,
        source: 'hh_negotiations_embedded',
      });
    }
  }
  return items;
}

/** Все карточки откликов на странице «Мои отклики». */
function parseNegotiationCardsFromDom(root = document, pack: HhSelectorPack = getSelectors()) {
  const HH_NEGOTIATIONS_SELECTORS = pack.negotiations as typeof DEFAULT_HH_NEGOTIATIONS_SELECTORS;
  const byId = new Map();

  for (const sel of HH_NEGOTIATIONS_SELECTORS.card) {
    const cards = queryAllIn(root, sel);
    for (const card of cards) {
      const item = parseNegotiationCard(card, pack);
      if (item) byId.set(item.vacancy_id, item);
    }
    if (byId.size > 0) break;
  }

  if (byId.size === 0) {
    const links = root.querySelectorAll(HH_NEGOTIATIONS_SELECTORS.titleLink);
    for (const link of links) {
      const card = findNegotiationCardRoot(link, pack);
      const item = parseNegotiationCard(card, pack);
      if (item) byId.set(item.vacancy_id, item);
    }
  }

  if (byId.size === 0) {
    for (const item of parseNegotiationsFromEmbeddedState(root)) {
      byId.set(item.vacancy_id, item);
    }
  }

  return Array.from(byId.values());
}

// ── EX-9: индивидуальный тред HR (`/applicant/negotiations/<id>`) — тихий импорт в hr_threads ──
// hh не даёт готового data-qa под этот экран (снятый снимок в plans/ покрывает только список);
// кандидаты ниже — эмпирика по общим соглашениям hh (см. HH_NEGOTIATIONS_SELECTORS выше), требуют
// подтверждения на живой странице (EX-9 §2 плана). Парсер намеренно консервативен: без надёжного
// сигнала направления реплики (hr_in/hr_out) — пропускаем её, а не угадываем (не корёжим hr_threads).

const DEFAULT_HR_THREAD_SELECTORS = {
  vacancyLink: 'a[href*="/vacancy/"]',
  companyLink: 'a[href*="/employer/"]',
  messageItem: [
    '[data-qa*="negotiations-item-message"]',
    '[data-qa*="negotiation-letter"]',
    '[data-qa*="topic-message"]',
    '[data-qa*="chat-message"]',
    '[data-qa*="message-item"]',
  ],
  dayDivider: '[data-qa*="date-divider"], [class*="date-divider"], [class*="day-divider"]',
};

const HR_OUT_HINT_RE = /outgoing|own-message|applicant|my-message|\bself\b/i;
const HR_IN_HINT_RE = /incoming|employer|other-message|hr-message/i;

/** Вакансия + компания треда — по ссылкам на странице (не зависит от вёрстки самого чата). */
function parseHrThreadHeaderFromDom(root = document, url = location.href, sel: HhSelectorPack = getSelectors()) {
  const HR_THREAD_SELECTORS = sel.hrThread as typeof DEFAULT_HR_THREAD_SELECTORS;
  const vacLink = root.querySelector(HR_THREAD_SELECTORS.vacancyLink);
  const vacancy_id =
    extractVacancyId((vacLink as HTMLAnchorElement | null)?.href) || extractVacancyId(url);
  const empLink = root.querySelector(HR_THREAD_SELECTORS.companyLink);
  const company = ((empLink as HTMLElement | null)?.innerText || '').trim();
  return { vacancy_id, company };
}

function _sortInDomOrder(nodes) {
  return [...nodes].sort((a, b) => {
    const pos = a.compareDocumentPosition(b);
    if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
    if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
    return 0;
  });
}

/** Направление реплики по сигналам data-qa/class на самом узле и паре предков. null — не угадываем. */
function _hrMessageDirection(node) {
  let el = node;
  for (let i = 0; i < 4 && el; i++) {
    const sig = `${el.getAttribute?.('data-qa') || ''} ${el.className || ''}`;
    if (HR_OUT_HINT_RE.test(sig)) return 'hr_out';
    if (HR_IN_HINT_RE.test(sig)) return 'hr_in';
    el = el.parentElement;
  }
  return null;
}

/** Текст реплики без узла времени (клон+вырезание — как parseVacancyRawAddress выше). */
function _hrMessageBody(node) {
  const clone = node.cloneNode(true);
  clone.querySelectorAll('time').forEach((el) => el.remove());
  return (clone.innerText || clone.textContent || '').replace(/\s+/g, ' ').trim();
}

/** Время реплики из <time> (datetime атрибут либо текст HH:MM) + дата ближайшего day-divider. */
function _hrMessageSentAt(node, currentDay) {
  const timeEl = node.querySelector?.('time');
  if (!timeEl) return null;
  const dt = timeEl.getAttribute('datetime');
  if (dt) {
    const d = new Date(dt);
    if (!Number.isNaN(d.getTime())) return formatNegotiationDate(d);
  }
  const txt = (timeEl.innerText || timeEl.textContent || '').trim();
  const m = txt.match(/(\d{1,2}):(\d{2})/);
  if (!m) return null;
  const day = currentDay || new Date();
  const d = new Date(day.getFullYear(), day.getMonth(), day.getDate(), Number(m[1]), Number(m[2]));
  return formatNegotiationDate(d);
}

/** Дата day-divider'а («Сегодня»/«Вчера»/«3 июля [2026]») → Date (полночь того дня). null — не понят. */
function _parseDayDividerText(el, now) {
  const t = (el.innerText || '').toLowerCase().replace(/ /g, ' ').trim();
  if (/сегодня/.test(t)) return now;
  if (/вчера/.test(t)) {
    const d = new Date(now);
    d.setDate(d.getDate() - 1);
    return d;
  }
  const ru = t.match(/(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?/i);
  if (ru) {
    const day = Number(ru[1]);
    const monTxt = ru[2];
    const year = Number(ru[3] || now.getFullYear());
    for (const [prefix, m] of RU_MONTH_PREFIXES) {
      if (monTxt.startsWith(String(prefix))) return new Date(year, Number(m), day);
    }
  }
  return null;
}

/**
 * Реплики треда в хронологическом порядке документа. [] — кандидаты не найдены (вёрстка не та,
 * которую ожидали, либо чат ещё не дорисован) — вызывающий код это не спамит, просто не синкает.
 *
 * EX-9/EXT-H1: реплика без надёжного сигнала направления раньше выбрасывалась здесь молча
 * (`continue`). Теперь она остаётся в списке с `kind: null` — решение угадывать или пропускать
 * переносится на вызывающий код (`content/hr-thread.ts`), у которого есть доступ к LLM-фолбэку
 * (batched `classify_hr_direction`) перед финальным синком в `hr_threads`.
 */
function parseHrThreadMessagesFromDom(root = document, pack: HhSelectorPack = getSelectors()) {
  const HR_THREAD_SELECTORS = pack.hrThread as typeof DEFAULT_HR_THREAD_SELECTORS;
  const seen = new Set();
  let nodes = [];
  for (const sel of HR_THREAD_SELECTORS.messageItem) {
    for (const el of queryAllIn(root, sel)) {
      if (!seen.has(el)) {
        seen.add(el);
        nodes.push(el);
      }
    }
  }
  if (!nodes.length) return [];
  nodes = _sortInDomOrder(nodes);

  const dividers = _sortInDomOrder(queryAllIn(root, HR_THREAD_SELECTORS.dayDivider));
  const now = new Date();
  let dividerIdx = 0;
  let currentDay = now;

  const items = [];
  for (const node of nodes) {
    while (
      dividerIdx < dividers.length &&
      dividers[dividerIdx].compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING
    ) {
      currentDay = _parseDayDividerText(dividers[dividerIdx], now) || currentDay;
      dividerIdx += 1;
    }

    const direction = _hrMessageDirection(node); // null — нет надёжного сигнала, решает вызывающий код

    const body = _hrMessageBody(node);
    if (!body || body.length > 20_000) continue;

    items.push({ kind: direction, body, sent_at: _hrMessageSentAt(node, currentDay) });
  }
  return items;
}

/** Вакансия + компания + реплики треда одним вызовом (точка входа для content/hr-thread.ts). */
function parseHrThreadFromDom(root = document, url = location.href, sel: HhSelectorPack = getSelectors()) {
  const header = parseHrThreadHeaderFromDom(root, url, sel);
  return { ...header, messages: parseHrThreadMessagesFromDom(root, sel) };
}

/** Срезает лейбл условия hh («Формат работы:», «График:», «Оформление:») — оставляем значение. */
function stripConditionLabel(text) {
  return String(text || '')
    .replace(/^[^:]{2,40}:\s*/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Текстовый фолбэк формата работы из шапки — если hh сменит data-qa work-formats-text.
 * Берём первое «Формат работы: …» (оно в хедере, до описания).
 */
function parseWorkFormatFromText(root = document) {
  const scope =
    root.querySelector('[data-qa="vacancy-view-employment-mode"]') ||
    root.querySelector('main') ||
    root.body ||
    root;
  const text = ((scope as HTMLElement | null)?.innerText || '').replace(/ /g, ' ');
  const m = text.match(/Формат\s+работы:\s*([^\n.;]{2,60})/i);
  return m ? m[1].trim() : '';
}

function collectCssVacancyCore(root, vacancy, fallbacks) {
  return {
    title: queryText(vacancy.title, root) || queryText(fallbacks.title || [], root),
    company: queryText(vacancy.company, root) || queryText(fallbacks.company || [], root),
    salary: queryText(vacancy.salary, root) || queryText(fallbacks.salary || [], root),
    description:
      queryText(vacancy.description, root) || queryText(fallbacks.description || [], root),
  };
}

function parseVacancyFromDom(url = location.href, sel: HhSelectorPack = getSelectors()) {
  const HH_SELECTORS = sel.vacancy;
  const HH_FALLBACKS = sel.fallbacks;
  const css = collectCssVacancyCore(document, HH_SELECTORS, HH_FALLBACKS);
  let title = css.title;
  let company = css.company;
  let salary = css.salary;
  let description = css.description;
  let parse_method = sel.origin === 'builtin' ? 'default' : 'config';

  if (!title && sel.origin !== 'builtin') {
    const baked = collectCssVacancyCore(document, DEFAULT_HH_SELECTORS, DEFAULT_HH_FALLBACKS);
    if (baked.title) parse_method = 'default';
    if (!title) title = baked.title;
    if (!company) company = baked.company;
    if (!salary) salary = baked.salary;
    if (!description) description = baked.description;
  }

  if (!title || !company) {
    const fromDocTitle = parseTitleFromDocumentTitle();
    if (fromDocTitle) {
      if (!title) title = fromDocTitle.title;
      if (!company) company = fromDocTitle.company;
    }
  }

  if (!title || !company || !salary || !description) {
    const structural = parseVacancyStructural(document);
    if (structural) {
      if (!title) {
        title = structural.title;
        parse_method = 'structural';
      }
      if (!company) company = structural.company;
      if (!salary) salary = structural.salary;
      if (!description) description = structural.description;
    }
  }

  // Условия из хедера hh. Новый magritte-хедер (2025-2026) разносит их по отдельным data-qa;
  // «Формат работы: удалённо/гибрид/на месте» лежит в work-formats-text (НЕ в schedule, где
  // теперь «Оформление: …»). Старые лейблы остаются фолбэком для прежней вёрстки.
  const workFormatRaw = queryText(HH_SELECTORS.workFormat) || parseWorkFormatFromText(document);
  const remoteLabel = queryText(HH_SELECTORS.remote); // старый лейбл «Удалённая работа»
  const employmentText = queryText(HH_SELECTORS.employmentText);
  const scheduleByDays = queryText(HH_SELECTORS.scheduleByDays);
  const workingHours = queryText(HH_SELECTORS.workingHours);
  const hiringFormats = queryText(HH_SELECTORS.schedule); // на новом хедере = «Оформление: …»

  // Значение формата работы без лейбла — для remote-оценки и поля schedule («удалённо», «гибрид»).
  const format = stripConditionLabel(workFormatRaw) || stripConditionLabel(remoteLabel);

  // Прочие условия хедера — каждое самодостаточно («Полная занятость», «График: 5/2»).
  const otherConditions = [employmentText, scheduleByDays, workingHours, hiringFormats]
    .map((s) => String(s || '').trim())
    .filter(Boolean);

  const address =
    parseVacancyRawAddress() ||
    queryText(HH_SELECTORS.address) ||
    queryText(HH_SELECTORS.addressMap);
  const letter_required = detectLetterRequired(document, sel);
  const published_at = parseVacancyPublishedAt(document);
  const vacancy_id = extractVacancyId(url);
  const employer_id = extractEmployerId(document);
  const total_responses_count = parseResponsesCount(document, vacancy_id, sel);

  const is_archived = detectVacancyArchived(document, sel);

  const parts = [];
  if (is_archived) {
    parts.push(
      'ВАКАНСИЯ В АРХИВЕ (HH): работодатель, вероятно, уже нашёл кандидата и больше не принимает отклики.'
    );
  }
  if (title) parts.push(title);
  if (company) parts.push(`Компания: ${company}`);
  if (salary) parts.push(`Зарплата: ${salary}`);
  if (format) parts.push(`Формат работы: ${format}`);
  if (otherConditions.length) parts.push(`Условия: ${otherConditions.join(' · ')}`);
  if (address) parts.push(`Локация: ${address}`);
  if (description) {
    if (parts.length) parts.push('');
    parts.push(description);
  }

  return {
    title,
    company,
    salary,
    schedule: format,
    work_format: format,
    work_schedule: format,
    address,
    area: parseCityFromArea(address),
    description,
    letter_required,
    published_at,
    employer_id,
    total_responses_count,
    competition: competitionLevel(total_responses_count),
    text: parts.join('\n').trim(),
    url,
    vacancy_id,
    page_type: getHhPageType(url),
    source: 'vacancy_page',
    is_archived,
    parse_method,
  };
}

// ── AF-2: статистика резюме (счётчики + история просмотров) ──
// Вёрстка кабинета соискателя hh нестабильна и меняется чаще вакансий — парсинг держим на
// текстовых якорях («Показы»/«Просмотры»/«Приглашения»), data-qa только как догадка-ускоритель.
// Читаем ТОЛЬКО публичные счётчики своего резюме (CLAUDE.md - HH read-only).

function isResumesPage(url = location.href) {
  return getResumePageType(url) === HH_PAGE_TYPE.RESUMES;
}

function isStatsPage(url = location.href) {
  return isStatsHost(url);
}

function isResumeHistoryPage(url = location.href) {
  return getResumePageType(url) === HH_PAGE_TYPE.RESUME_HISTORY;
}

/** ID резюме (hex-хэш) из URL или первой ссылки /resume/<id> на странице. '' если нет. */
function extractResumeId(root = document, url = location.href) {
  const fromUrl = String(url || '').match(/\/resume\/([0-9a-f]{6,})/i);
  if (fromUrl) return fromUrl[1];
  const link = root.querySelector?.('a[href*="/resume/"]');
  const href = link
    ? String(link.getAttribute('href') || (link as HTMLAnchorElement).href || '')
    : '';
  const m = href.match(/\/resume\/([0-9a-f]{6,})/i);
  return m ? m[1] : '';
}

function _resumeStatInt(str) {
  const d = String(str || '').replace(/[\s ]/g, '');
  const n = parseInt(d, 10);
  return Number.isFinite(n) && n >= 0 && n < 10_000_000 ? n : null;
}

// Корни-якоря (без хвоста \w*, чтобы не съесть прилегающее число): «показ…», «просмотр…»,
// «приглашен…». Кириллица обоих регистров — флаг i ненадёжен для не-ASCII в части движков.
const RESUME_STAT_ANCHORS = [
  ['impressions', 'показ[а-яёА-ЯЁ]*'],
  ['views', 'просмотр[а-яёА-ЯЁ]*'],
  ['invitations', 'приглашен[а-яёА-ЯЁ]*'],
];

/**
 * Из плоского текста статистики достаёт число и недельную дельту по каждому якорю.
 * hh пишет «Показы 2917», «Просмотры 41 +4», «Приглашения 1 +1» (порядок/вёрстка пляшут):
 * сначала «якорь → число (+дельта)», затем фолбэк «число → якорь» (без дельты).
 */
function parseResumeStatsText(text) {
  const norm = String(text || '').replace(/ /g, ' ').replace(/\s+/g, ' ');
  const out: Record<string, number | null> = {};
  for (const [key, anchor] of RESUME_STAT_ANCHORS) {
    // якорь → только пробел/двоеточие до числа (НЕ запятая/буквы - иначе «2917 показов, 41
    // просмотр» утянет в показы соседнее 41) → жадное число с разрядными пробелами → опц. «+дельта».
    // Жадность важна: «2 917» иначе обрывается на первом пробеле, дав 2 вместо 2917.
    const fwd = norm.match(new RegExp(`${anchor}[:\\s]{0,4}(\\d[\\d ]*\\d|\\d)(?: *\\+ *(\\d+))?`, 'i'));
    if (fwd) {
      out[key] = _resumeStatInt(fwd[1]);
      out[`${key}_delta`] = fwd[2] ? _resumeStatInt(fwd[2]) || 0 : 0;
      continue;
    }
    // фолбэк «2917 показов» (без дельты)
    const bwd = norm.match(new RegExp(`(\\d[\\d ]*\\d|\\d) *${anchor}`, 'i'));
    if (bwd) {
      out[key] = _resumeStatInt(bwd[1]);
      out[`${key}_delta`] = 0;
    }
  }
  return out;
}

/**
 * Кол-во рекомендуемых вакансий: кнопка «N вакансии/вакансий» под резюме на `/applicant/profile/me`
 * (data-qa="resume-recommendations__button_editResume"). Отдельный блок от «Статистика за неделю»,
 * читаем независимо от `_findResumeStatsScope`. null — блока нет на странице (не ошибка).
 */
function parseRecommendedVacanciesFromDom(root = document) {
  const el = root.querySelector?.('[data-qa="resume-recommendations__button_editResume"]');
  if (!el) return null;
  const text = ((el as HTMLElement).innerText || el.textContent || '').replace(/ /g, ' ');
  const m = text.match(/(\d[\d ]*\d|\d)\s*вакан/i);
  return m ? _resumeStatInt(m[1]) : null;
}

/** Наименьший контейнер со всеми тремя якорями — чтобы не цеплять чужие числа со всей страницы. */
function _findResumeStatsScope(root = document) {
  const guesses = [
    '[data-qa="resume-stats"]',
    '[data-qa*="resume-statistics"]',
    '[class*="resume-statistics"]',
    '[class*="statistics"]',
  ];
  for (const sel of guesses) {
    const el = root.querySelector?.(sel);
    if (el && /показ/i.test(el.textContent || '')) return el;
  }
  let best = null;
  for (const el of queryAllIn(root, 'div, section, aside, ul')) {
    const t = el.textContent || '';
    if (t.length > 2000) continue;
    if (/показ/i.test(t) && /просмотр/i.test(t) && /приглашен/i.test(t)) {
      if (!best || (el.textContent || '').length < (best.textContent || '').length) best = el;
    }
  }
  return best;
}

/**
 * Снимок счётчиков резюме со страницы `/applicant/resumes` / `/applicant/profile/me`. null — блок статистики не найден
 * (молча не шлём, не падаем). Числа отсутствующих метрик → 0, дельты → 0.
 */
function parseResumeStatsFromDom(root = document) {
  const scope = _findResumeStatsScope(root) || root.body || root;
  const text = scope.innerText || scope.textContent || '';
  const parsed = parseResumeStatsText(text);
  const recommended = parseRecommendedVacanciesFromDom(root);
  const hasAny =
    parsed.impressions != null ||
    parsed.views != null ||
    parsed.invitations != null ||
    recommended != null;
  if (!hasAny) return null;
  return {
    resume_id: extractResumeId(root),
    period: 'week',
    impressions: parsed.impressions ?? 0,
    views: parsed.views ?? 0,
    invitations: parsed.invitations ?? 0,
    recommended_vacancies: recommended ?? 0,
    views_delta: parsed.views_delta ?? 0,
    invitations_delta: parsed.invitations_delta ?? 0,
    raw: { source: 'hh_resumes', text: text.replace(/\s+/g, ' ').trim().slice(0, 600) },
  };
}

/** Дата строки истории из <time datetime> / текста карточки → «YYYY-MM-DD HH:MM». */
function _resumeViewDateText(cardEl) {
  const timeEl = cardEl.querySelector('time');
  if (timeEl) {
    const dt = timeEl.getAttribute('datetime');
    if (dt) return dt;
    const t = (timeEl.innerText || timeEl.textContent || '').trim();
    if (t) return t;
  }
  const text = (cardEl.innerText || '').replace(/ /g, ' ');
  const m =
    text.match(/(?:сегодня|вчера)(?:\s+в\s+\d{1,2}:\d{2})?/i) ||
    text.match(/\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2})?/) ||
    text.match(/\d{1,2}\s+[а-яё]+(?:\s+\d{4})?(?:\s+в\s+\d{1,2}:\d{2})?/i);
  return m ? m[0].replace(/\s+в\s+/i, ' ') : '';
}

function _parseResumeHistoryRow(cardEl) {
  if (!cardEl) return null;
  const empLink = cardEl.querySelector('a[href*="/employer/"]');
  const vacLink = cardEl.querySelector('a[href*="/vacancy/"]');
  const employer = (empLink?.innerText || empLink?.textContent || '').trim();
  const vacancy_title = (vacLink?.innerText || vacLink?.textContent || '').trim();
  const vacancy_url = (vacLink?.href || '').split('?')[0] || '';
  const viewed_at = normalizeNegotiationAppliedAt(_resumeViewDateText(cardEl));

  // Ни компании, ни вакансии, ни даты — это не строка истории (хедер таблицы, разделитель).
  if (!employer && !vacancy_url && !viewed_at) return null;

  return { employer, vacancy_title, vacancy_url, viewed_at, resume_id: '', raw: {} };
}

/** Контейнеры строк истории просмотров (data-qa догадки → фолбэк по ссылке работодателя). */
function _resumeHistoryRowEls(root = document) {
  const out = [];
  const seen = new Set();
  const selectors = [
    '[data-qa*="resume-view-history-item"]',
    '[data-qa*="resumeview-item"]',
    '[data-qa*="view-history"] tr',
    'tr[data-qa*="resume"]',
    'li[data-qa*="resume"]',
  ];
  for (const sel of selectors) {
    for (const el of queryAllIn(root, sel)) {
      if (!seen.has(el)) {
        seen.add(el);
        out.push(el);
      }
    }
    if (out.length) return out;
  }
  for (const link of queryAllIn(root, 'a[href*="/employer/"]')) {
    const card =
      link.closest('tr, li, [class*="item"], [class*="row"]') || link.parentElement;
    if (card && !seen.has(card)) {
      seen.add(card);
      out.push(card);
    }
  }
  return out;
}

/**
 * Строки истории просмотров резюме (`/applicant/resumeview/history`): кто смотрел и когда.
 * Дедуп в пределах страницы по (работодатель | ссылка | время) — финальный дедуп на бэке.
 */
function parseResumeViewHistoryFromDom(root = document) {
  const rows = [];
  const seen = new Set();
  for (const card of _resumeHistoryRowEls(root)) {
    const row = _parseResumeHistoryRow(card);
    if (!row) continue;
    const key = `${row.employer}|${row.vacancy_url}|${row.viewed_at || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(row);
  }
  return { resume_id: extractResumeId(root), rows };
}

// ── E-03: индекс рынка «резюме на вакансию» со страницы stats.hh.ru ──
// Вёрстка — хешированные CSS-модули (React SPA), меняются на каждый деплой hh, устойчивого
// data-qa нет вообще. Держим парсинг на текстовом якоре «hh.индекс» (заголовок бейджа), а не на
// классах — тот же приём, что `_findResumeStatsScope`/`_findSerpFoundScope` выше.

/** Узел с точным текстом «hh.индекс» — заголовок бейджа индекса рынка. null — SPA ещё не дорисовала. */
function _findMarketIndexTitleNode(root = document) {
  for (const el of queryAllIn(root, 'div, span, p')) {
    if (/^hh\.индекс$/i.test((el.textContent || '').trim())) return el;
  }
  return null;
}

/**
 * Значение индекса рядом с заголовком «hh.индекс»: поднимаемся по предкам заголовка, пока не
 * найдём внутри них изолированное число (`_shortInfo` хh — общий родитель заголовка и значения,
 * обычно на 3-м уровне вверх; запас до 6, если hh добавит обёртку). null — блока/числа нет.
 */
function parseMarketIndexFromDom(root = document) {
  const titleEl = _findMarketIndexTitleNode(root);
  if (!titleEl) return null;

  let container = titleEl;
  for (let i = 0; i < 6 && container; i++) {
    for (const el of queryAllIn(container, 'span, div')) {
      const t = (el.textContent || '').trim();
      if (/^\d{1,3}(?:[.,]\d{1,2})?$/.test(t)) {
        const value = parseFloat(t.replace(',', '.'));
        if (Number.isFinite(value) && value >= 0 && value < 1000) return { value };
      }
    }
    container = container.parentElement;
  }
  return null;
}

/** Фолбэк на случай отсутствия `pagerNext` (Этап 4 редизайна «Расширения»): текущая вёрстка hh
 *  (Magritte-пагинатор) вообще не рендерит отдельную стрелку «следующая» — только пронумерованные
 *  `data-qa="pager-page"`-ссылки, из которых текущая помечена `aria-current="true"`. Следующая —
 *  соседний по DOM-порядку элемент (номера идут по возрастанию), без разбора номера страницы из
 *  href/URL — сам номер завязан на CSS-модули, которые меняются от деплоя к деплою, `aria-current`
 *  и порядок в DOM устойчивее. */
function _getSerpNextPageUrlFromPagerPages(root: Document | Element): string | null {
  const pageLinks = queryAllIn(root, '[data-qa="pager-page"]') as HTMLAnchorElement[];
  if (!pageLinks.length) return null;
  const currentIdx = pageLinks.findIndex((a) => a.getAttribute('aria-current') === 'true');
  if (currentIdx === -1) return null;
  return pageLinks[currentIdx + 1]?.href || null;
}

/** Ссылка «Следующая страница» выдачи hh.ru (`pagerNext`) — null на последней странице. Раньше
 *  селектор был определён, но нигде не использовался (мёртвый код); нужен discovery-раннеру,
 *  чтобы листать выдачу дальше первой страницы. Причина #3 редизайна «Расширения»
 *  (`plans/extension_pipeline_redesign_2026_08_18.md`) — на живом hh.ru (проверено 2026-08-19)
 *  `data-qa="pager-next"` в текущей вёрстке вообще не рендерится, есть только `pager-page` —
 *  без фолбэка раннер считал выдачу законченной уже на первой странице. */
function getSerpNextPageUrl(root = document, sel: HhSelectorPack = getSelectors()) {
  const HH_SERP_SELECTORS = sel.serp;
  const el = root.querySelector(HH_SERP_SELECTORS.pagerNext) as HTMLAnchorElement | null;
  if (el?.href) return el.href;
  return _getSerpNextPageUrlFromPagerPages(root);
}

export {
  DEFAULT_HH_SELECTORS,
  DEFAULT_HH_SELECTORS as HH_SELECTORS,
  DEFAULT_HH_FALLBACKS,
  DEFAULT_HH_FALLBACKS as HH_FALLBACKS,
  DEFAULT_HH_SERP_SELECTORS,
  DEFAULT_HH_RESPONSE_LINK_SELECTORS,
  DEFAULT_HH_RESPONSE_LINK_SELECTORS as HH_RESPONSE_LINK_SELECTORS,
  DEFAULT_HH_NEGOTIATIONS_SELECTORS,
  DEFAULT_HR_THREAD_SELECTORS,
  HH_PAGE_TYPE,
  parseVacancyFromDom,
  extractVacancyId,
  getHhPageType,
  isVacancyResponseFormPage,
  getPageType,
  isResumesPage,
  isResumeHistoryPage,
  isStatsPage,
  parseResumeStatsFromDom,
  parseResumeViewHistoryFromDom,
  parseMarketIndexFromDom,
  detectLetterRequired,
  detectAlreadyAppliedOnPage,
  detectVacancyArchived,
  isNegotiationsPage,
  isNegotiationThreadPath,
  parseNegotiationCardsFromDom,
  parseHrThreadFromDom,
  parseSerpCardsFromDom,
  parseSerpDemandFromDom,
  getSerpNextPageUrl,
  negotiationsPageKey,
  getNegotiationsPageIndex,
  mapHhStatusToFunnel,
}
