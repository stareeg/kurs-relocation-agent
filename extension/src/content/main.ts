import {
  FUNNEL_STATUS,
  funnelStatusClass,
  funnelStatusLabel,
} from './funnel'
import { splitHighlight } from '../../../shared/highlight'
import {
  DEFAULT_SCORE_BREAKDOWN_MAX,
  GRADE_TONE,
  competitionLevel,
  COMPETITION_LEVEL_SUFFIX,
  RECOMMENDATION_LABEL,
  SCORE_BREAKDOWN_LABEL,
  scoreLevel,
} from '../../../shared/criteria'
import { parseScoreGate, scoreBreakdownRows } from '../../../shared/score-breakdown'
import {
  formatFactCard,
  formatSalaryCardText,
  gradeFactCard,
  resolveSalaryForCard,
  salaryCardCaption,
  salaryCardValueTone,
  salaryProvenanceShort,
} from '../../../shared/fact-cards'
import { waitForVacancyDomReady, waitForVacancyStable } from '../dom/dom-utils'
import {
  GETMATCH_PAGE_TYPE,
  HABR_PAGE_TYPE,
  HH_PAGE_TYPE,
  type SiteRoute,
  getSite,
  resolveRoute,
} from '../dom/site-router'
import {
  hhVacancyExtractor,
} from '../dom/extractors/hh'
import {
  isVacancyResponseFormPage,
  getSerpNextPageUrl,
} from '../dom/selectors'
import { getRuntimeConfig, initRuntimeConfig } from '../dom/extension-runtime-config'
import { getSelectors, initSelectors } from '../dom/selectors-config'
import { parseSerpListingFromDom } from '../dom/serp-json'
import {
  parseGetmatchCatalogCardsFromDom,
  hasGetmatchNextPage,
  clickGetmatchNextPage,
  waitForCatalogPageChange,
} from '../dom/selectors-getmatch-catalog'
import { getmatchVacancyExtractor } from '../dom/extractors/getmatch'
import { habrVacancyExtractor, parseHabrListingFromDom } from '../dom/extractors/habr'
import { GM_RESPONSE_LINK_SELECTORS, gmApplySel } from '../dom/selectors-getmatch'
import type { VacancyExtractor } from '../dom/extractors/types'
import { negotiationsAdapter } from './negotiations'
import { hrThreadAdapter } from './hr-thread'
import { resumesAdapter } from './resumes'
import { hhStatsAdapter } from './hh-stats'
import { serpAdapter } from './serp'
import { idleAdapter } from './idle'
import { getmatchIdleAdapter } from './getmatch-idle'
import { getmatchApplicationsAdapter } from './getmatch-applications'
import { getmatchCatalogAdapter } from './getmatch-catalog'
import { habrApplicationsAdapter } from './habr-applications'
import {
  convMessagesToQaHistory,
  qaHistoryForAsk,
} from './qa-conversation'
import { normalizeScoreErrorMessage } from './score-error'
import { pruneScoreCache, writeScoreCache } from './score-cache'
import { getmatchProfileStatsAdapter } from './getmatch-profile-stats'
import { bootDock } from './dock'
import { startNegotiationsHeartbeat } from './negotiations-heartbeat'
import { startGetmatchHeartbeat } from './getmatch-heartbeat'
import { getmatchProfilePageAdapter } from './getmatch-profile-page'
import { iconMarkup } from '../ui/icons'
import { loadConfig, DEFAULT_WEB_BASE_URL } from '../config'
import { reportParseHealth } from '../parse-health'
import { SKIP_REASONS, DODGY_COMPANY_REASON, type SkipReasonSuggestion } from '../skip-reasons'
import { runHhApplyFlow, type AnketaAnswerInput, type AnketaQuestionDom } from './hh-apply-flow'

/** Активный парсер вакансии для текущей вкладки (hh / getmatch / habr). */
let vacancyExtractor: VacancyExtractor = hhVacancyExtractor

function ensureVacancyExtractor() {
  const site = getSite()
  if (site === 'getmatch') vacancyExtractor = getmatchVacancyExtractor
  else if (site === 'habr') vacancyExtractor = habrVacancyExtractor
  else vacancyExtractor = hhVacancyExtractor
  return vacancyExtractor
}

/** Подпись площадки в пользовательских строках (hh.ru / getmatch.ru / career.habr.com). */
function listingSiteLabel() {
  const site = getSite()
  if (site === 'getmatch') return 'getmatch.ru'
  if (site === 'habr') return 'career.habr.com'
  return 'hh.ru'
}

function normTitle(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Кэш скоринга привязан к vacancy_id; сверяем заголовок с DOM, чтобы не показать чужой результат. */
function scoreCacheMatchesDom(cached, parsed) {
  if (!cached?.score) return false
  if (parsed?.vacancy_id && cached.vacancy_id && cached.vacancy_id !== parsed.vacancy_id) {
    return false
  }
  const domTitle = normTitle(parsed?.title)
  const cachedTitle = normTitle(cached?.title)
  if (!domTitle || !cachedTitle) return true
  if (domTitle === cachedTitle) return true
  const probe = domTitle.slice(0, Math.min(24, domTitle.length))
  return probe.length >= 10 && cachedTitle.includes(probe)
}

function mergeParsedJobMeta(record, parsed) {
  if (!parsed) return record
  return {
    ...record,
    vacancy_id: parsed.vacancy_id || record.vacancy_id,
    title: parsed.title || record.title,
    company: parsed.company || record.company,
    salary_text: parsed.salary || record.salary_text,
    work_format: parsed.work_format || record.work_format,
    published_at: parsed.published_at || record.published_at,
  }
}

/** Шапка бренда панели: одна lucide-иконка + «Copilot» (fallback, если название вакансии
 *  ещё не распарсено — см. headerTitleRowHtml). */
const BRAND_HTML = `<div class="jh-brand">${iconMarkup('sparkles', { size: 14 })}<span>Copilot</span></div>`;

/** Подписи кнопок воронки (иконка + текст) — переиспользуются при сбросе после ошибки. */
const MARK_APPLIED_HTML = `${iconMarkup('check', { size: 14 })}<span>Откликнуться</span>`;
const APPLIED_DONE_HTML = `${iconMarkup('check', { size: 14 })}<span>Есть отклик</span>`;
const SKIP_HTML = `${iconMarkup('circle-x', { size: 14 })}<span>Пропустить</span>`;
/** «Вернуть» (снять пропуск) — тот же стиль, что у «Пропустить», но иконка возврата. */
const UNSKIP_HTML = `${iconMarkup('undo-2', { size: 14 })}<span>Вернуть</span>`;
const SAVING_HTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Сохраняем…</span>`;

/** Единые подписи действий (U-08 / U-15): чат и сопроводительное. */
const COVER_LETTER_LABEL = 'Сопроводительное';
const COVER_LETTER_HTML = `${iconMarkup('file-text', { size: 14 })}<span>${COVER_LETTER_LABEL}</span>`;
/** «Чат» — живёт рядом с «Отправить» в композере (Решение 5), не в ряду действий. Правка
 *  2026-08-20: подпись сокращена с «Открыть чат» — рядом с «Отправить» и так понятно, что кнопка
 *  открывает чат; полная формулировка осталась в `title` (тултип), не в самой кнопке. */
const OPEN_CHAT_LABEL = 'Чат';
const OPEN_CHAT_TITLE = 'Открыть чат по вакансии в вебе';
const OPEN_CHAT_HTML = `${iconMarkup('message-circle', { size: 14 })}<span>${OPEN_CHAT_LABEL}</span>`;
/** Статичная кнопка «Избегать компанию» — отдельная от LLM-чипов пропуска, во 2 ряду.
 *  Иконка — `ban` (круг+диагональ), не `circle-x` («Пропустить»/«Вернуть»): чтобы не путать
 *  «пропустить эту вакансию» с «больше не показывать компанию вообще». */
const DODGY_COMPANY_HTML = `${iconMarkup('ban', { size: 14 })}<span>Избегать</span>`;
/** Done-state той же кнопки — компания уже в списке «Избегать» (см. renderScore/alreadyAvoided). */
const DODGY_COMPANY_DONE_HTML = `${iconMarkup('ban', { size: 14 })}<span>Уже избегаем</span>`;

// Ярлыки, порядок и классификация good/mid/bad критериев — общий словарь shared/criteria (E-02),
// единственный источник для панели и дровера (Решение 3 плана vacancy_ui_2026_07_28.md).
const GRADE_CLASS = GRADE_TONE;

/** Заполняется `ensureScoreBreakdownMax()` из `scoring_weights` (`/api/settings`); null → фолбэк. */
let scoreBreakdownMax = null;
let scoreBreakdownMaxLoaded = null;

/** Грузит максимумы критериев один раз (с кэшем); падение сети — тихо остаёмся на фолбэке. */
async function ensureScoreBreakdownMax(force = false) {
  if (!scoreBreakdownMaxLoaded || force) {
    scoreBreakdownMaxLoaded = chrome.runtime
      .sendMessage({ action: 'get_settings' })
      .then((response: any) => {
        if (response?.ok && response.data?.scoring_weights) {
          scoreBreakdownMax = response.data.scoring_weights;
        }
      })
      .catch(() => { /* остаёмся на DEFAULT_SCORE_BREAKDOWN_MAX */ });
  }
  return scoreBreakdownMaxLoaded;
}

/** Разбор балла «Почему N» — строки с полосами, как ScoreBreakdown дровера (U-06).
 *  Подпись фактора — hover-подсказка (dark-тултип, как ScoreBreakdownLabel в вебе) с
 *  `reasoning`; если фактор сыграл барьером (гейт) — иконка сразу после подписи фактора (не
 *  после числа справа), с той же подсказкой, что и у самой подписи — наводиться можно на любое
 *  из двух и увидеть одно и то же объяснение. «Калибровка» тут не показываем — под шестью
 *  полосами она только мешается (в отличие от дровера, где остаётся как есть). */
function scoreBreakdownSectionHtml(s) {
  const weights = scoreBreakdownMax || DEFAULT_SCORE_BREAKDOWN_MAX;
  const rows = scoreBreakdownRows(s, weights);
  if (!rows) {
    return `<p class="jh-breakdown-unavailable">Разбор недоступен — вакансия скорена до перехода на новый формат.</p>`;
  }

  const gate = parseScoreGate(s.gate_triggered);
  const gateKey = s.gate_triggered ? gate.key : null;

  const rowsHtml = rows
    .map((r) => {
      const pct = Math.max(4, Math.min(100, Math.round((Math.max(0, r.value) / r.max) * 100)));
      const isGate = gateKey === r.key;
      const hintParts = [];
      if (isGate) hintParts.push(`Барьер: ${gate.label}`);
      if (r.reasoning) hintParts.push(r.reasoning);
      const hint = hintParts.join('\n');
      const hintAttr = hint ? ` data-jh-tip="${escapeAttr(hint)}"` : '';
      const interactive = hint ? ' jh-has-tip' : '';
      const iconHtml = isGate
        ? `<span class="jh-breakdown-flag jh-has-tip"${hintAttr}>${iconMarkup('triangle-alert', { size: 12 })}</span>`
        : '';
      return `
        <div class="jh-breakdown-row">
          <span class="jh-breakdown-label${interactive}"${hintAttr}>${escapeHtml(r.label)}</span>
          ${iconHtml}
          <span class="jh-breakdown-track"><span class="jh-breakdown-fill ${r.tone}" style="width:${pct}%"></span></span>
          <span class="jh-breakdown-nums ${r.tone}">${r.value} / ${r.max}</span>
        </div>`;
    })
    .join('');

  return `
    <div class="jh-breakdown-section">
      <div class="jh-section-title">Почему ${s.overall_score}</div>
      <div class="jh-breakdown-rows">${rowsHtml}</div>
    </div>`;
}

/** EXT-S1: гейт больше не рисуем отдельным slop-бейджем в шапке — иконка-барьер живёт
 *  в строке фактора разбора «Почему N» (см. scoreBreakdownSectionHtml). */

let shadowRoot = null;
let panelEl = null;
let barActionsEl = null;
let dockSlots = null;
let scoreBtn = null;
let cancelBtn = null;
let expandBtn = null;
let toastEl = null;
let currentVacancyId = null;
let currentFunnelStatus = null;
/** Последнее значение /vacancies/{id}/seen (состояние для навигации; UI-бейдж снят). */
let currentSeen = false;
/** Конфиг расширения (webBaseUrl) для handoff-ссылок; грузится один раз. */
let extConfig = null;
let toastTimer = null;
const _appliedSyncInFlight = new Set();
/** Дедуп POST /funnel для пары vacancy_id + status */
const _funnelStatusInFlight = new Map();
/** Кэш job_id по vacancy_id — чтобы кнопка «Сопроводительное» работала без предварительного /score.
 *  Заполняется из ответа POST /funnel (job_id новый) и из ScoreResponse.id (после /score). */
const jobIdCache: Record<string, number> = {};
let currentScoreRecord = null;
let isLoading = false;
let panelCollapsed = false;
let activeScoreRunId = 0;
let snapshotBeforeScore = null;
let qaLoading = false;
/** U-14: кэш Q&A в памяти; персист — Postgres через `/vacancies/{id}/ask` + чтение `/api/conversations`. */
const qaHistoryCache = {};
/** vacancyId → был ли уже чат (thread или сообщения) — для «Начать / Продолжить чат». */
const hasChatCache = {};
/** EX-4: сгенерированные сопроводительные по vacancy_id (переживают re-render панели). */
const coverLetterCache = {};
/** Э4.4: выбранный/фактический язык письма по vacancy_id ("ru"|"en"). Нет записи —
 *  переключалка показывает нейтральное состояние (автоопределение по резюме). */
const coverLetterLangCache = {};
/** EX-4: vacancy_id, помеченные «Пропустить» (ручной skip / авто по recommendation / бэкенд). */
const skippedCache = new Set();
/** Причина пропуска по vacancy_id (известна только при ручном skip в этой сессии). */
const skipReasonCache = {};
/** LLM-сгенерированные чипы причин пропуска по vacancy_id (6 конкретных причин). */
const skipReasonsLlmCache = {};

function shouldPollSalary(record) {
  return (
    Boolean(record?.score?.salary?.estimate_pending) &&
    resolveSalaryForCard(record).text === 'оценка…'
  );
}

/** Фоновая вилка: поллим GET /score/{id}/salary и обновляем док + кэш. */
async function pollSalaryEstimateIntoRecord(vacancyId, record, funnelStatus) {
  // Увеличенный бюджет поллинга (был 30×2с=60с, LLM reasoning может дольше):
  // 45 попыток × 3с = 135с — покрывает бюджет_ms=75_000 фичи salary_estimate + запас.
  // continue по pending/task_running больше НЕ сжирает попытку — отдельный счётчик.
  const maxAttempts = 45;
  const intervalMs = 3000;
  let pendingAttempts = 0;
  for (let i = 0; i < maxAttempts; i += 1) {
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const response: any = await chrome.runtime.sendMessage({
        action: 'poll_salary',
        payload: { vacancy_id: vacancyId },
      });
      if (!response?.ok || !response.data) continue;
      const data = response.data;
      // pending/task_running — НЕ считаем как попытку: фон ещё работает, поллим дальше.
      // Раньше continue сжирал i, и за 30 попыток все уходили на pending — карточка
      // зависала на «оценка…» навсегда, хотя backend ещё считал.
      if (data.estimate_pending || data.task_running) {
        const preview = {
          ...record,
          score: {
            ...(record.score || {}),
            salary: { ...(record.score?.salary || {}), ...data },
          },
        };
        // Вилка уже на карточке — не крутим «оценка…», даже если флаг pending залип.
        if (resolveSalaryForCard(preview).text !== 'оценка…') {
          const next = {
            ...record,
            score: {
              ...(record.score || {}),
              salary: {
                ...(record.score?.salary || {}),
                estimated_range: data.estimated_range || record.score?.salary?.estimated_range || '',
                estimated_min: data.estimated_min ?? record.score?.salary?.estimated_min ?? null,
                estimated_max: data.estimated_max ?? record.score?.salary?.estimated_max ?? null,
                value_or_range: data.value_or_range || record.score?.salary?.value_or_range || '',
                meets_min: data.meets_min ?? record.score?.salary?.meets_min,
                note: data.note || record.score?.salary?.note || '',
                confidence: data.confidence || record.score?.salary?.confidence || 'low',
                source: data.source || record.score?.salary?.source || 'none',
                estimate_pending: false,
              },
            },
          };
          currentScoreRecord = next;
          if (record.score) record.score = next.score;
          renderScore(next, funnelStatus);
          void writeScoreCache(vacancyId, next);
          return;
        }
        pendingAttempts += 1;
        // Но если pending висит аномально долго (>40 проверок) — выходим, не зацикливаемся.
        if (pendingAttempts > 40) {
          console.warn('[Job Hunter] salary poll: pending слишком долго, выходим для', vacancyId);
          // Раньше здесь был голый return: поллинг останавливался, а запись оставалась с
          // estimate_pending=true навсегда — карточка висела на «оценка…» без объяснения,
          // даже когда бэкенд сам уже снял флаг (запись просто не перечитывалась). Пишем
          // терминальное состояние явно, чтобы карточка показала честный «—», а не вечный спиннер.
          const timedOut = {
            ...record,
            score: {
              ...(record.score || {}),
              salary: {
                ...(record.score?.salary || {}),
                estimate_pending: false,
                source: record.score?.salary?.source || 'none',
              },
            },
          };
          currentScoreRecord = timedOut;
          if (record.score) record.score = timedOut.score;
          renderScore(timedOut, funnelStatus);
          void writeScoreCache(vacancyId, timedOut);
          return;
        }
        continue;
      }
      const next = {
        ...record,
        score: {
          ...(record.score || {}),
          salary: {
            ...(record.score?.salary || {}),
            estimated_range: data.estimated_range || '',
            estimated_min: data.estimated_min ?? null,
            estimated_max: data.estimated_max ?? null,
            value_or_range: data.value_or_range || record.score?.salary?.value_or_range || '',
            meets_min: data.meets_min,
            note: data.note || '',
            confidence: data.confidence || 'low',
            source: data.source || 'none',
            estimate_pending: false,
          },
        },
      };
      currentScoreRecord = next;
      if (record.score) record.score = next.score;
      renderScore(next, funnelStatus);
      void writeScoreCache(vacancyId, next);
      return;
    } catch {
      /* сеть — ещё попытка */
    }
  }
}

/** Поллим LLM-причины пропуска (GET /vacancies/{id}/skip-reasons) и обновляем чипы. */
async function pollSkipReasonsIntoCache(vacancyId, funnelStatus) {
  const maxAttempts = 20;
  const intervalMs = 2000;
  for (let i = 0; i < maxAttempts; i += 1) {
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const response: any = await chrome.runtime.sendMessage({
        action: 'poll_skip_reasons',
        payload: { vacancy_id: vacancyId },
      });
      if (!response?.ok || !response.data) continue;
      const data = response.data;
      const reasons = data.reasons;
      // Нет причин и задача неактивна — LLM не сгенерировал, фолбэк на статичные.
      if (!reasons || reasons.length === 0) {
        if (!data.task_running) return;
        continue;
      }
      skipReasonsLlmCache[vacancyId] = reasons;
      // Если панель сейчас показывает эту вакансию — перерисуем триаж с новыми чипами.
      const activeVid = currentVacancyId || currentScoreRecord?.vacancy_id;
      if (activeVid === vacancyId && currentScoreRecord) {
        renderScore(currentScoreRecord, funnelStatus);
      }
      return;
    } catch {
      /* сеть — ещё попытка */
    }
  }
}

/** Приоритет: DOM с цифрами → LLM value → estimated_range; pending — «оценка…». */
function resolveSalary(record) {
  return resolveSalaryForCard(record);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Атрибут тултипа — безопасно для переносов строк: \n в атрибуте HTML невалиден и гасит весь тултип. */
function escapeAttr(text) {
  return escapeHtml(text).replace(/\r?\n/g, ' &#10;');
}

/**
 * Выделяет жирным ключевую часть пункта (V-06: разбор строки — в общем модуле `shared/highlight`,
 * тут только HTML-рендер с экранированием, общий для дровера не подходит).
 */
function highlightItem(text) {
  if (!text) return '';
  const { bold, rest } = splitHighlight(text);
  return `<strong>${escapeHtml(bold)}</strong>${escapeHtml(rest)}`;
}

/** Списки, которым нельзя опустеть (ScoreResult.pros/cons — `min_length=1`, см. models.py). */
const THESIS_MIN1 = new Set(['pros', 'cons']);

function thesisItemHtml(text, listClass, index, locked) {
  const delAttrs = locked ? ' disabled title="Должен остаться хотя бы один пункт"' : ' title="Удалить"';
  return `
    <li class="jh-thesis-item" draggable="true" data-list="${listClass}" data-index="${index}">
      <span class="jh-thesis-dot" aria-hidden="true">${iconMarkup('grip-vertical', { size: 12 })}</span>
      <span class="jh-thesis-text">${highlightItem(text)}</span>
      <button type="button" class="jh-thesis-del" data-action="thesis-delete" data-list="${listClass}" data-index="${index}"${delAttrs}>${iconMarkup('trash-2', { size: 12 })}</button>
    </li>`;
}

function listItems(items, listClass) {
  if (!items?.length) return '';
  const locked = THESIS_MIN1.has(listClass) && items.length <= 1;
  return items.map((item, i) => thesisItemHtml(item, listClass, i, locked)).join('');
}

/** Секция списка (Плюсы / флаги / Минусы) — Решение 3: рендерим всегда, даже пустую (нужна
 *  как валидная зона сброса drag-and-drop между тремя списками), не только при непустых items. */
function bulletListSectionHtml(title, items, listClass) {
  return `
    <div class="jh-section">
      <div class="jh-section-title">${escapeHtml(title)}</div>
      <ul class="jh-list ${listClass}" data-list="${listClass}">${listItems(items, listClass)}</ul>
    </div>`;
}

/** Вердикт одной строкой — после разбора балла, как TabDecision дровера (U-07). */
function verdictHtml(verdict) {
  const text = verdict && String(verdict).trim() ? String(verdict).trim() : '';
  if (!text) return '';
  return `<div class="jh-verdict"><p>${escapeHtml(text)}</p></div>`;
}

/** Карточка факта (U-05): label / value / caption — зеркало FactCard дровера. */
function factCardHtml(label, value, caption, toneClass = '', title = '') {
  const tipAttr = title ? ` jh-has-tip data-jh-tip="${escapeAttr(title)}"` : '';
  return `
    <div class="jh-fact-card${tipAttr}">
      <div class="jh-fact-card-label">${escapeHtml(label)}</div>
      <div class="jh-fact-card-value ${toneClass}">${escapeHtml(value)}</div>
      <div class="jh-fact-card-caption">${escapeHtml(caption)}</div>
    </div>`;
}

/** Тройка карточек «Зарплата · Формат · Грейд» — как FactCards во вкладке «Решение». */
function factCardsHtml(record, s) {
  const salary = resolveSalaryForCard(record);
  const salaryValue = formatSalaryCardText(salary);
  const provenance = salaryProvenanceShort(salary.source, s.salary?.note);
  const format = formatFactCard(record, s);
  const grade = gradeFactCard(s);

  return `<div class="jh-fact-cards">
    ${factCardHtml(
      SCORE_BREAKDOWN_LABEL.salary,
      salaryValue,
      salaryCardCaption(salary, provenance),
      salaryCardValueTone(salary),
      provenance ?? '',
    )}
    ${factCardHtml(
      SCORE_BREAKDOWN_LABEL.work_format,
      format.value,
      format.caption,
      format.tone,
      format.title ?? '',
    )}
    ${factCardHtml(
      SCORE_BREAKDOWN_LABEL.grade_match,
      grade.value,
      grade.caption,
      GRADE_CLASS[s.grade_match?.level] || 'neutral',
      grade.title ?? '',
    )}
  </div>`;
}

/** Бейдж конкуренции по числу откликов (A5, только UI). */
function headerMetaSep() {
  return '<span class="jh-header-meta-sep">·</span>';
}

/** Строка скора (U-04): балл слева, пилюли (Совет/Воронка/Письмо/Отклики) — справа. */
function headerScoreRowHtml(score, pillsHtml) {
  if (score == null) return '';
  return `
    <div class="jh-header-score-row">
      <span class="jh-score ${scoreLevel(score)}">${score}<span class="jh-score-max">/100</span></span>
      <div class="jh-pills-row">${pillsHtml}</div>
    </div>`;
}

/** Название вакансии — отдельной строкой под строкой скора (зеркало SheetTitle дровера).
 *  Правка 2026-08-20: кликабельно, если известен `vacancyId` — открывает дровер вакансии на
 *  фронтенде в новой вкладке (`webJobUrl`), тот же URL, что уже использует «Править в вебе»/
 *  синк откликов getmatch/habr; без `vacancyId` — обычный (некликабельный) текст, как раньше. */
function headerTitleRowHtml(title, vacancyId) {
  const titleText = title && String(title).trim() ? String(title).trim() : '';
  if (!titleText) return '';
  const inner = escapeHtml(titleText);
  if (!vacancyId) {
    return `<div class="jh-header-title-row"><span class="jh-header-vacancy-title">${inner}</span></div>`;
  }
  const href = escapeAttr(webJobUrl(vacancyId));
  return `<div class="jh-header-title-row"><a class="jh-header-vacancy-title jh-header-vacancy-title-link" href="${href}" target="_blank" rel="noopener" title="Открыть вакансию в вебе">${inner}</a></div>`;
}

/** Вторая строка шапки (U-04): компания и мета — типографика SheetDescription (13px, slate-500). */
function headerMetaHtml(company, metaItems = []) {
  const companyText =
    company && String(company).trim() ? String(company).trim() : 'Компания не указана';
  const parts = [`<span>${escapeHtml(companyText)}</span>`];
  for (const item of metaItems) {
    if (item) parts.push(`${headerMetaSep()}<span>${escapeHtml(item)}</span>`);
  }
  return `<div class="jh-header-meta">${parts.join('')}</div>`;
}

/** Бейдж конкуренции по числу откликов (A5, только UI). */
function competitionBadgeHtml(totalResponsesCount, competition) {
  if (totalResponsesCount == null || totalResponsesCount < 0) return '';
  const level = competition || competitionLevel(totalResponsesCount);
  if (!level) return '';
  const suffix = COMPETITION_LEVEL_SUFFIX[level] ? ` · ${COMPETITION_LEVEL_SUFFIX[level]}` : '';
  const formatted = totalResponsesCount.toLocaleString('ru-RU');
  return `<span class="jh-pill-badge jh-competition-${level} jh-has-tip" data-jh-tip="${escapeAttr(`Откликов на вакансию на ${listingSiteLabel()}`)}">${iconMarkup('users', { size: 12 })}<span>${escapeHtml(formatted)}${escapeHtml(suffix)}</span></span>`;
}

// ── EX-3: прозрачная связь с web и ботом ──

/** Грузит конфиг один раз (webBaseUrl для handoff-ссылок). */
async function ensureExtConfig() {
  if (!extConfig) extConfig = await loadConfig();
  return extConfig;
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.webBaseUrl) {
    extConfig = null;
    void ensureExtConfig();
  }
});

/** Deep-link на дровер вакансии в web: ${webBaseUrl}/jobs/{vacancy_id}. */
function webJobUrl(vacancyId) {
  const base = extConfig?.webBaseUrl || DEFAULT_WEB_BASE_URL;
  return `${base}/jobs/${encodeURIComponent(vacancyId)}`;
}

/** Deep-link на чат по вакансии в web: ${webBaseUrl}/chat?vacancy=… */
function webChatUrl(vacancyId) {
  const base = extConfig?.webBaseUrl || DEFAULT_WEB_BASE_URL;
  return `${base}/chat?vacancy=${encodeURIComponent(vacancyId)}`;
}

/** Произвольный deep-link в web SPA: ${webBaseUrl}{path}. */
function webUrl(path) {
  const base = extConfig?.webBaseUrl || DEFAULT_WEB_BASE_URL;
  return `${base}${path}`;
}

function openExternal(url) {
  if (url) window.open(url, '_blank', 'noopener');
}

function hideToast() {
  if (!toastEl) return;
  toastEl.classList.add('hidden');
  toastEl.innerHTML = '';
  clearTimeout(toastTimer);
  toastTimer = null;
}

/** Тосты под панелью отключены — статус уже виден в шапке/триаже. */
function showToast(_message, _actions = null, _icon = 'circle-check') {
  hideToast();
}

// Действия handoff (открыть в вебе / бот / подготовка / разбор) собираются
// в renderActionsHtml — едином верхнем блоке действий панели. Глубокая работа
// (подготовка/разбор) живёт в web/bot, расширение только ссылается.
// `webJobUrl` — теперь только для клика по названию вакансии в шапке (`headerTitleRowHtml`) и
// для getmatch/habr-синка (`web-links.ts`); своя кнопка «Открыть в вебе» у письма убрана
// (правка 2026-08-20) — правка текста теперь на месте, см. `onCoverEditStartClick`.

function onOpenChatClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  if (vacancyId) openExternal(webChatUrl(vacancyId));
}

// EX-7: точка монтирования в общий док (dock.ts владеет shadow-host/panel/toast/toolbar — здесь
// только рендер vacancy-специфичного содержимого тулбара + подписка на него, ровно как раньше
// делал ensureUi() в своём собственном shadow-host).
function ensureUi(slots) {
  dockSlots = slots;
  shadowRoot = slots.shadowRoot;
  panelEl = slots.panelEl;
  barActionsEl = slots.barActionsEl;
  toastEl = slots.toastEl;

  panelEl.setAttribute('tabindex', '-1');
  panelEl.setAttribute('role', 'dialog');
  panelEl.setAttribute('aria-label', 'Copilot — оценка вакансии');
  panelEl.addEventListener('keydown', onPanelKeydown);

  slots.toolbarEl.innerHTML = `
    <button type="button" class="jh-btn-expand hidden" id="jh-expand-btn">${iconMarkup('chevron-down', { size: 14 })}<span>Развернуть</span></button>
    <button type="button" class="jh-btn" id="jh-score-btn">${iconMarkup('sparkles', { size: 16 })}<span id="jh-score-btn-label">Оценить вакансию</span></button>
    <button type="button" class="jh-btn-cancel hidden" id="jh-cancel-btn">${iconMarkup('x', { size: 14 })}<span>Отмена</span></button>
  `;

  // Действия по вакансии — в баре сверху слева, единый стиль с «Аккаунт» (иконка + подпись).
  slots.barActionsEl.innerHTML = `
    <button type="button" class="jh-bar-btn hidden" id="jh-bar-collapse" title="Свернуть панель" aria-label="Свернуть панель">${iconMarkup('chevron-down', { size: 14 })}<span>Свернуть</span></button>
    <button type="button" class="jh-bar-btn hidden" id="jh-bar-rescore" title="Обновить — оценить вакансию заново" aria-label="Обновить оценку">${iconMarkup('refresh-cw', { size: 14 })}<span>Обновить</span></button>
  `;

  scoreBtn = shadowRoot.getElementById('jh-score-btn');
  cancelBtn = shadowRoot.getElementById('jh-cancel-btn');
  expandBtn = shadowRoot.getElementById('jh-expand-btn');
  scoreBtn.addEventListener('click', onScoreClick);
  cancelBtn.addEventListener('click', onCancelScoreClick);
  expandBtn.addEventListener('click', onExpandPanelClick);
  shadowRoot.getElementById('jh-bar-rescore').addEventListener('click', () => {
    void runScoringFlow({ auto: false });
  });
  shadowRoot.getElementById('jh-bar-collapse').addEventListener('click', collapsePanel);

  document.addEventListener('jh-account-toggle', onDockAccountToggle);
  bindTooltips();
  bindThesisDnd();
}

/** Esc по панели: открытый список причин пропуска свернуть, иначе свернуть/закрыть панель. */
function onPanelKeydown(e) {
  if (e.key !== 'Escape') return;
  const reasons = shadowRoot?.getElementById('jh-skip-reasons');
  if (reasons && !reasons.classList.contains('hidden')) {
    e.stopPropagation();
    const toggle = shadowRoot?.querySelector('[data-action="skip-toggle"]');
    if (toggle) toggle.click();
    return;
  }
  e.stopPropagation();
  if (currentScoreRecord?.score) collapsePanel();
  else hidePanel();
}

/** Действия в баре видны только когда есть что сворачивать/обновлять и «Аккаунт» закрыт. */
function updateBarActions() {
  if (!barActionsEl) return;
  const accountOpen = Boolean(dockSlots?.accountOpen);
  const hasScore = Boolean(currentScoreRecord?.score);
  const panelVisible = hasScore && !panelCollapsed && panelEl && !panelEl.classList.contains('hidden');
  const toggle = (id, show) => {
    const el = barActionsEl.querySelector(`#${id}`);
    if (el) el.classList.toggle('hidden', !show);
  };
  toggle('jh-bar-rescore', !accountOpen && hasScore && !isLoading);
  toggle('jh-bar-collapse', !accountOpen && panelVisible && !isLoading);
}

/** Лёгкий dark-тултип (зеркало variant="dark" в вебе): читаем data-jh-tip у элемента под
 *  курсором, рисуем один общий бокс внутри shadow-root. Текст многострочный (барьер + почему). */
let tipEl = null;
function positionTip(anchor) {
  if (!tipEl || !shadowRoot) return;
  const win = shadowRoot.querySelector('.jh-window') || shadowRoot.host;
  const winRect = win.getBoundingClientRect();
  const rootRect = shadowRoot.host.getBoundingClientRect();
  const r = anchor.getBoundingClientRect();
  tipEl.style.visibility = 'hidden';
  tipEl.style.left = '0px';
  tipEl.style.top = '0px';
  const tw = tipEl.offsetWidth || 200;
  const th = tipEl.offsetHeight || 40;

  // Ограничиваем по горизонтали границами окна панели (.jh-window)
  const minLeft = winRect.left - rootRect.left + 8;
  const maxLeft = winRect.right - rootRect.left - tw - 8;
  let left = r.left - rootRect.left;
  left = Math.max(minLeft, Math.min(left, maxLeft));

  // Позиционируем сверху, если не влезает — снизу
  let top = r.top - rootRect.top - th - 8;
  if (r.top - th - 8 < winRect.top) {
    top = r.bottom - rootRect.top + 8;
  }
  tipEl.style.left = `${Math.round(left)}px`;
  tipEl.style.top = `${Math.round(top)}px`;
  tipEl.style.visibility = 'visible';
}
function hideTip() {
  if (tipEl) tipEl.remove();
  tipEl = null;
}
function onTipOver(e) {
  const anchor = e.target?.closest?.('[data-jh-tip]');
  if (!anchor || !shadowRoot?.contains(anchor)) return;
  const text = anchor.getAttribute('data-jh-tip') || '';
  if (!text.trim()) return;
  if (!tipEl) {
    tipEl = document.createElement('div');
    tipEl.className = 'jh-tip';
    shadowRoot.appendChild(tipEl);
  }
  if (tipEl.textContent !== text) tipEl.textContent = text;
  positionTip(anchor);
}
function bindTooltips() {
  if (!shadowRoot || shadowRoot.__jhTipsBound) return;
  shadowRoot.__jhTipsBound = true;
  shadowRoot.addEventListener('mouseover', onTipOver);
  shadowRoot.addEventListener('mouseout', (e) => {
    if (e.target?.closest?.('[data-jh-tip]')) hideTip();
  });
  shadowRoot.addEventListener('mousedown', hideTip);
}

// ── Решение 3: drag-and-drop тезисов между Плюсы/Минусы/Красные флаги + удаление ──

/** {list, index} перетаскиваемого тезиса; живёт между dragstart и drop/dragend одного жеста. */
let thesisDrag = null;

function currentThesisLists() {
  const s = currentScoreRecord?.score;
  return {
    pros: [...(s?.pros || [])],
    cons: [...(s?.cons || [])],
    flags: [...(s?.red_flags || [])],
  };
}

/** Применяет мутацию к копии трёх списков и, если она не заблокирована гардом min1, сохраняет:
 *  локально (перерисовка) + фоном на бэк (PATCH, не блокируем UI на сетевой round-trip). */
function applyThesisMutation(mutate) {
  if (!currentScoreRecord?.score) return;
  const lists = currentThesisLists();
  const ok = mutate(lists);
  if (!ok) return;
  for (const key of THESIS_MIN1) {
    if (lists[key].length < 1) return; // гард min1 сработал бы на бэке — не уходим в запрос впустую
  }
  currentScoreRecord.score.pros = lists.pros;
  currentScoreRecord.score.cons = lists.cons;
  currentScoreRecord.score.red_flags = lists.flags;
  renderScore(currentScoreRecord, currentFunnelStatus);
  const vacancyId = currentVacancyId || currentScoreRecord.vacancy_id;
  if (!vacancyId) return;
  sendMessage({
    action: 'update_theses',
    payload: { vacancy_id: vacancyId, pros: lists.pros, cons: lists.cons, red_flags: lists.flags },
  }).then((response) => {
    if (!response?.ok) console.warn('[Job Hunter] правка тезисов не сохранилась:', response?.error);
  }).catch((err) => console.warn('[Job Hunter] правка тезисов не сохранилась:', err));
}

function onThesisDeleteClick(btn) {
  const listClass = btn.getAttribute('data-list');
  const index = Number(btn.getAttribute('data-index'));
  if (!listClass || !Number.isInteger(index)) return;
  applyThesisMutation((lists) => {
    if (index < 0 || index >= lists[listClass].length) return false;
    lists[listClass].splice(index, 1);
    return true;
  });
}

function clearThesisDropVisuals() {
  shadowRoot?.querySelectorAll('.jh-drop-target').forEach((el) => el.classList.remove('jh-drop-target'));
  shadowRoot?.querySelectorAll('.jh-dragging').forEach((el) => el.classList.remove('jh-dragging'));
}

/** Индекс вставки внутри целевого списка — по вертикальной половине наведённого элемента (перед/
 *  после), либо конец списка, если навели на пустое место контейнера. */
function thesisDropIndex(container: Element, clientY: number) {
  const items = Array.from(container.querySelectorAll(':scope > .jh-thesis-item')) as HTMLElement[];
  for (const item of items) {
    const r = item.getBoundingClientRect();
    if (clientY < r.top + r.height / 2) return Number(item.getAttribute('data-index'));
  }
  return items.length;
}

function bindThesisDnd() {
  if (!shadowRoot || shadowRoot.__jhThesisDndBound) return;
  shadowRoot.__jhThesisDndBound = true;

  shadowRoot.addEventListener('dragstart', (e) => {
    const item = e.target?.closest?.('.jh-thesis-item');
    if (!item || !shadowRoot.contains(item)) return;
    thesisDrag = { list: item.getAttribute('data-list'), index: Number(item.getAttribute('data-index')) };
    item.classList.add('jh-dragging');
    try {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', `${thesisDrag.list}:${thesisDrag.index}`);
    } catch {
      /* dataTransfer недоступен в некоторых тестовых DOM — сам жест это переживёт */
    }
  });

  shadowRoot.addEventListener('dragover', (e) => {
    if (!thesisDrag) return;
    const list = e.target?.closest?.('.jh-list[data-list]');
    if (!list || !shadowRoot.contains(list)) return;
    e.preventDefault();
    shadowRoot.querySelectorAll('.jh-drop-target').forEach((el) => {
      if (el !== list) el.classList.remove('jh-drop-target');
    });
    list.classList.add('jh-drop-target');
  });

  shadowRoot.addEventListener('drop', (e) => {
    const list = e.target?.closest?.('.jh-list[data-list]');
    if (!thesisDrag || !list || !shadowRoot.contains(list)) return;
    e.preventDefault();
    const from = thesisDrag;
    const toList = list.getAttribute('data-list');
    const toIndex = thesisDropIndex(list, e.clientY);
    thesisDrag = null;
    clearThesisDropVisuals();
    if (from.list === toList && (from.index === toIndex || from.index === toIndex - 1)) return;
    applyThesisMutation((lists) => {
      if (from.index < 0 || from.index >= lists[from.list].length) return false;
      const [moved] = lists[from.list].splice(from.index, 1);
      let insertAt = toIndex;
      if (from.list === toList && from.index < toIndex) insertAt -= 1;
      lists[toList].splice(Math.max(0, Math.min(insertAt, lists[toList].length)), 0, moved);
      return true;
    });
  });

  shadowRoot.addEventListener('dragend', () => {
    thesisDrag = null;
    clearThesisDropVisuals();
  });
}

function showPanel(html) {
  // hidden→shown — это «открытие»: уводим фокус в панель (Esc/Tab/чтение с клавиатуры).
  // Перерендер уже видимой панели (смена этапа, пропуск, фоновый поллинг причин/зарплаты) фокус
  // не трогает — а прокрутку тела специально сохраняем: innerHTML целиком пересобирает DOM и
  // сбрасывает scrollTop, из-за чего панель «подпрыгивала» наверх посреди чтения плюсов/минусов.
  const wasHidden = panelEl.classList.contains('hidden');
  const prevBody = wasHidden ? null : panelEl.querySelector('.jh-body');
  const prevScrollTop = prevBody ? prevBody.scrollTop : 0;
  panelEl.innerHTML = html;
  panelEl.classList.remove('hidden');
  if (wasHidden) {
    try {
      panelEl.focus({ preventScroll: true });
    } catch (err) {
      /* focus может бросить в редких рантаймах — некритично */
    }
  } else if (prevScrollTop) {
    const body = panelEl.querySelector('.jh-body');
    if (body) body.scrollTop = prevScrollTop;
  }
}

function hidePanel() {
  hideTip();
  panelEl.classList.add('hidden');
  panelEl.innerHTML = '';
  panelCollapsed = false;
  updateToolbar();
  updateBarActions();
}

function collapsePanel() {
  if (!currentScoreRecord?.score) {
    hidePanel();
    return;
  }
  hideTip();
  panelCollapsed = true;
  panelEl.classList.add('hidden');
  updateToolbar();
  updateBarActions();
}

function expandPanel() {
  if (!currentScoreRecord?.score) return;
  panelCollapsed = false;
  renderScore(currentScoreRecord, currentFunnelStatus);
}

function updateToolbar() {
  if (!scoreBtn || !cancelBtn || !expandBtn) return;
  const hasScore = Boolean(currentScoreRecord?.score);
  const showCancel = isLoading;
  // «Обновить» (перескор) живёт в баре сверху (иконка refresh-cw); в тулбаре — только первая оценка.
  const showScore = !isLoading && !hasScore;
  const showExpand =
    !isLoading && panelCollapsed && hasScore;
  cancelBtn.classList.toggle('hidden', !showCancel);
  scoreBtn.classList.toggle('hidden', !showScore);
  expandBtn.classList.toggle('hidden', !showExpand);
  scoreBtn.disabled = false;
  const label = scoreBtn.querySelector('#jh-score-btn-label');
  if (label) label.textContent = 'Оценить вакансию';
}

function beginScoreOperation() {
  activeScoreRunId += 1;
  sendMessage({ action: 'cancel_score' }).catch(() => {});
  return activeScoreRunId;
}

function cancelScoreOperation() {
  activeScoreRunId += 1;
  sendMessage({ action: 'cancel_score' }).catch(() => {});
}

function isScoreRunActive(runId) {
  return runId === activeScoreRunId;
}

function isScoreCancelledError(err) {
  const msg = String(err?.message || err || '');
  return msg.includes('Оценка отменена') || msg.includes('aborted');
}

function takeUiSnapshot() {
  return {
    record: currentScoreRecord
      ? { ...currentScoreRecord, score: currentScoreRecord.score }
      : null,
    funnelStatus: currentFunnelStatus,
    panelCollapsed,
    panelWasVisible: panelEl && !panelEl.classList.contains('hidden'),
  };
}

function restoreAfterCancel() {
  setLoading(false);
  const snap = snapshotBeforeScore;
  snapshotBeforeScore = null;
  if (!snap) {
    hidePanel();
    return;
  }
  if (snap.record?.score) {
    currentScoreRecord = snap.record;
    currentFunnelStatus = snap.funnelStatus;
    panelCollapsed = snap.panelCollapsed;
    if (!panelCollapsed && snap.panelWasVisible) {
      renderScore(snap.record, snap.funnelStatus);
    } else {
      panelEl.classList.add('hidden');
      updateToolbar();
    }
    return;
  }
  hidePanel();
}

function setSeenBadge(seen) {
  currentSeen = Boolean(seen);
}

async function refreshSeenBadge(vacancyId) {
  if (!vacancyId) {
    setSeenBadge(false);
    return;
  }
  try {
    const response = await sendMessage({ action: 'check_seen', payload: { vacancy_id: vacancyId } });
    setSeenBadge(Boolean(response?.ok && response.data?.seen));
  } catch {
    setSeenBadge(false);
  }
}

function setLoading(loading) {
  isLoading = loading;
  updateToolbar();
  updateBarActions();
}

/** Точечный skeleton + animate-pulse (зеркало раскладки renderScore: триаж → факты → разбор). */
function renderSkeleton(caption, preview = null) {
  const factSkel =
    '<div class="jh-fact-card"><span class="jh-skel jh-skel-line sm"></span><span class="jh-skel jh-skel-line"></span><span class="jh-skel jh-skel-line sm"></span></div>';
  const breakdownSkel =
    '<div class="jh-breakdown-row"><span class="jh-skel jh-skel-line sm"></span><span class="jh-skel jh-skel-bar"></span><span class="jh-skel jh-skel-nums"></span></div>';
  const listSkel =
    '<div class="jh-skel-section"><span class="jh-skel jh-skel-line sm"></span><span class="jh-skel jh-skel-line md"></span></div>';
  const actionsSkel = `
    <div class="jh-actions">
      <div class="jh-triage-row">
        <span class="jh-skel jh-skel-btn"></span>
        <span class="jh-skel jh-skel-btn"></span>
        <span class="jh-skel jh-skel-btn"></span>
      </div>
      <div class="jh-act-row">
        <span class="jh-skel jh-skel-act"></span>
        <span class="jh-skel jh-skel-act"></span>
        <span class="jh-skel jh-skel-act"></span>
      </div>
    </div>`;
  const company = preview?.company;
  const title = preview?.title;
  const hasPreview =
    (company && String(company).trim()) || (title && String(title).trim());
  const headerBlock = hasPreview
    ? `<div class="jh-header-title-row">
         <span class="jh-skel jh-skel-score"></span>
         ${title && String(title).trim()
           ? `<span class="jh-header-vacancy-title">${escapeHtml(String(title).trim())}</span>`
           : '<span class="jh-skel jh-skel-line md"></span>'}
       </div>
       ${headerMetaHtml(company)}`
    : `<div class="jh-header-title-row">
         <span class="jh-skel jh-skel-score"></span>
         <span class="jh-skel jh-skel-line md"></span>
       </div>`;
  showPanel(`
    <div class="jh-header">
      <div class="jh-header-main">
        ${headerBlock}
        <div class="jh-skel-row">
          <span class="jh-skel jh-skel-pill"></span>
          <span class="jh-skel jh-skel-pill"></span>
        </div>
      </div>
    </div>
    <div class="jh-body">
      ${actionsSkel}
      <div class="jh-fact-cards">${factSkel.repeat(3)}</div>
      <div class="jh-breakdown-section">
        <span class="jh-skel jh-skel-line sm"></span>
        <div class="jh-breakdown-rows">${breakdownSkel.repeat(6)}</div>
      </div>
      <div class="jh-verdict"><span class="jh-skel jh-skel-line md"></span></div>
      ${listSkel.repeat(3)}
      <div class="jh-skel-caption">${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>${escapeHtml(caption)}</span></div>
    </div>
  `);
  panelCollapsed = false;
}

/** Ошибка скоринга — силуэт ErrorState веба: заголовок, note, «Повторить». */
function renderError(message) {
  const note = normalizeScoreErrorMessage(message);
  showPanel(`
    <div class="jh-header">
      <div class="jh-header-main">
        ${BRAND_HTML}
      </div>
      <button type="button" class="jh-close" data-action="close" title="Закрыть">${iconMarkup('x', { size: 16 })}</button>
    </div>
    <div class="jh-body">
      <div class="jh-error-state">
        <div class="jh-error-icon">${iconMarkup('triangle-alert', { size: 20 })}</div>
        <p class="jh-error-title">Не удалось оценить</p>
        <p class="jh-error-note">${escapeHtml(note)}</p>
        <button type="button" class="jh-error-retry" data-action="retry-score">${iconMarkup('rotate-ccw', { size: 14 })}<span>Повторить</span></button>
      </div>
    </div>
  `);
  bindPanelActions();
}

/** Пилюля статуса воронки рядом с баллом (справа): явная подпись «Воронка» + цвет по этапу —
 *  чтобы не путать с чипом рекомендации слева. */
function funnelPillHtml(status) {
  if (!status) return '';
  const cls = funnelStatusClass(status);
  return (
    `<span class="jh-funnel-pill ${cls}" id="jh-funnel-pill" title="Текущий этап воронки">` +
    `<span class="jh-funnel-pill-label">Воронка</span>` +
    `<span class="jh-funnel-pill-val"><span class="jh-funnel-pill-dot"></span>${escapeHtml(funnelStatusLabel(status))}</span>` +
    `</span>`
  );
}

function qaStorageKey(vacancyId) {
  return `qa:${vacancyId}`;
}

function getQaHistory(vacancyId) {
  if (!vacancyId) return [];
  return qaHistoryCache[vacancyId] || [];
}

function setQaHistory(vacancyId, history) {
  if (!vacancyId) return;
  qaHistoryCache[vacancyId] = history;
  if (history.length > 0) hasChatCache[vacancyId] = true;
  // Зеркало для офлайн-fallback; источник истины — `/api/conversations`.
  chrome.storage.local.set({ [qaStorageKey(vacancyId)]: history });
}

async function loadQaHistory(vacancyId) {
  if (!vacancyId) return [];

  try {
    const response = await sendMessage({
      action: 'get_conversation',
      payload: { vacancy_id: vacancyId },
    });
    if (response?.ok) {
      const messages = response.data?.messages || [];
      const history = convMessagesToQaHistory(messages);
      setQaHistory(vacancyId, history);
      hasChatCache[vacancyId] =
        Boolean(response.data?.thread) || messages.length > 0 || history.length > 0;
      return history;
    }
  } catch {
    /* бэкенд недоступен — читаем локальный кэш */
  }

  if (qaHistoryCache[vacancyId]) return qaHistoryCache[vacancyId];

  return new Promise((resolve) => {
    chrome.storage.local.get(qaStorageKey(vacancyId), (result) => {
      const history = result[qaStorageKey(vacancyId)] || [];
      qaHistoryCache[vacancyId] = history;
      if (history.length > 0) hasChatCache[vacancyId] = true;
      resolve(history);
    });
  });
}

/** `HH:MM` — компактная подпись времени под пузырём (мини-версия `fmtMsgTime` из веб-чата
 *  вакансии, `VacancyDialog.tsx`; там `ДД.ММ ЧЧ:ММ`, здесь диалог короткий и почти всегда
 *  за один день, дата не нужна). */
function formatQaTime(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Инлайн-разметка реплики: экранирование + `**жирный**` → `<strong>` — узкое подмножество
 *  веб-`MarkdownView` (`frontend/src/components/markdown-view.tsx`), которого достаточно для
 *  коротких Q&A-ответов (жирный на ключевых моментах — без заголовков/кода/формул). */
function renderQaInline(text) {
  return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}

/** Ответ ассистента — абзацы + списки (`-`/`*`/`1.`) с жирным внутри строк. Вопрос владельца
 *  рендерится обычным текстом (см. `qaMessagesHtml` ниже) — тот же выбор, что у веб-чата
 *  (`Bubble` в `VacancyDialog.tsx`: `MarkdownView` только для `llm_assistant`). */
function renderQaAssistantHtml(text) {
  const blocks = [];
  let list = null;
  const flushList = () => {
    if (!list) return;
    const items = list.items.map((it) => `<li>${renderQaInline(it)}</li>`).join('');
    blocks.push(`<${list.tag}>${items}</${list.tag}>`);
    list = null;
  };
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    const ordered = /^\d+\.\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
      list.items.push(bullet[1]);
      continue;
    }
    if (ordered) {
      if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; }
      list.items.push(ordered[1]);
      continue;
    }
    flushList();
    if (line) blocks.push(`<p>${renderQaInline(line)}</p>`);
  }
  flushList();
  return blocks.join('') || `<p>${renderQaInline(text)}</p>`;
}

/** Пузырь реплики (правка 2026-08-20, мини-версия веб-чата вакансии — `Bubble` в
 *  `VacancyDialog.tsx`): цвет по роли, жирный/списки в ответе ассистента, подпись времени,
 *  кнопка «копировать» — текст пузыря к тому же выделяется мышью как обычный текст (CSS). */
function qaMessagesHtml(history) {
  if (!history.length) return '';
  return history.map((msg) => {
    const cls = msg.role === 'user' ? 'user' : 'assistant';
    const bodyHtml =
      msg.role === 'assistant' ? renderQaAssistantHtml(msg.content) : `<p>${renderQaInline(msg.content)}</p>`;
    const time = msg.ts ? formatQaTime(msg.ts) : '';
    return `
      <div class="jh-qa-msg ${cls}">
        <div class="jh-qa-msg-body">${bodyHtml}</div>
        <div class="jh-qa-msg-meta">
          <button type="button" class="jh-qa-msg-copy" data-qa-copy="${escapeAttr(msg.content)}" title="Копировать сообщение">${iconMarkup('copy', { size: 11 })}</button>
          ${time ? `<span class="jh-qa-msg-time">${time}</span>` : ''}
        </div>
      </div>`;
  }).join('');
}

function qaSendIcon() {
  return qaLoading
    ? iconMarkup('loader', { size: 16, className: 'jh-spin' })
    : iconMarkup('send', { size: 16 });
}

/** Тред переписки по вакансии — в прокручиваемом теле, сразу после «Минусы».
 *  Без заголовка/подсказки: пока сообщений нет, контейнер скрыт (`:empty`). */
function qaThreadHtml(history) {
  return `<div class="jh-qa-messages" id="jh-qa-messages">${qaMessagesHtml(history)}</div>`;
}

/** Композер чата — закреплён в подвале панели, виден всегда без прокрутки. Поле — `<textarea>`
 *  (было `<input>`, правка 2026-08-20): в одну строку, пока пусто, растёт с текстом до
 *  `QA_INPUT_MAX_HEIGHT` (см. `autosizeQaInput`), дальше — обычный скролл внутри поля. */
function qaComposerHtml() {
  return `
    <div class="jh-qa-input-row">
      <textarea class="jh-qa-input" id="jh-qa-input" rows="1" placeholder="Спросить про вакансию…" maxlength="2000" ${qaLoading ? 'disabled' : ''}></textarea>
      <button type="button" class="jh-qa-send" data-action="qa-send" ${qaLoading ? 'disabled' : ''}>${qaSendIcon()}<span>Отправить</span></button>
      <button type="button" class="jh-qa-open-chat" data-action="open-chat" title="${OPEN_CHAT_TITLE}">${OPEN_CHAT_HTML}</button>
    </div>
  `;
}

/** Компактный потолок высоты поля (панель узкая) — дальше скролл внутри textarea, не рост панели. */
const QA_INPUT_MAX_HEIGHT = 96;

/** Растёт с текстом от однострочной высоты до `QA_INPUT_MAX_HEIGHT` (тот же приём, что у
 *  веб-`Textarea`, `frontend/src/components/ui/textarea.tsx`): сбросить высоту, измерить
 *  `scrollHeight`, поставить обратно с потолком. */
function autosizeQaInput() {
  const el = shadowRoot?.getElementById('jh-qa-input');
  if (!el) return;
  el.style.height = 'auto';
  const next = Math.min(el.scrollHeight, QA_INPUT_MAX_HEIGHT);
  el.style.height = `${next}px`;
  el.style.overflowY = el.scrollHeight > QA_INPUT_MAX_HEIGHT ? 'auto' : 'hidden';
}

/** Прокрутить тело панели к последнему сообщению (композер закреплён в подвале). */
function scrollQaToBottom() {
  const body = shadowRoot?.querySelector('.jh-body');
  if (body) body.scrollTop = body.scrollHeight;
}

function updateQaMessagesDom(history) {
  const box = shadowRoot?.getElementById('jh-qa-messages');
  if (box) {
    box.innerHTML = qaMessagesHtml(history);
    scrollQaToBottom();
  }
}

async function onQaSend(questionOverride?) {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  const input = shadowRoot?.getElementById('jh-qa-input');
  const question = (questionOverride || input?.value || '').trim();
  if (!question || qaLoading || !vacancyId || !currentScoreRecord) return;

  await loadQaHistory(vacancyId);

  const history = qaHistoryForAsk(getQaHistory(vacancyId));
  const userMsg = { role: 'user', content: question, ts: Date.now() };
  const pendingHistory = [...getQaHistory(vacancyId), userMsg];
  setQaHistory(vacancyId, pendingHistory);
  updateQaMessagesDom(pendingHistory);
  if (input) {
    input.value = '';
    autosizeQaInput();
  }

  qaLoading = true;
  bindQaControls(true);

  try {
    const response = await sendMessage({
      action: 'ask',
      payload: {
        vacancy_id: vacancyId,
        question,
        history,
        vacancy_text: (() => {
          const t = currentScoreRecord.vacancy_text;
          if (t && t.length >= 50) return t;
          return ensureVacancyExtractor().parseVacancyFromDom().text || t;
        })(),
        title: currentScoreRecord.title,
        company: currentScoreRecord.company,
        salary_text: currentScoreRecord.salary_text,
        score: currentScoreRecord.score,
      },
    });

    if (!response?.ok) {
      throw new Error(response?.error || 'Ошибка Q&A');
    }

    const assistantMsg = { role: 'assistant', content: response.data.answer, ts: Date.now() };
    const fullHistory = [...pendingHistory, assistantMsg];
    setQaHistory(vacancyId, fullHistory);
    updateQaMessagesDom(fullHistory);
  } catch (err) {
    const errMsg = { role: 'assistant', content: String(err.message || err), ts: Date.now() };
    const errHistory = [...pendingHistory, errMsg];
    setQaHistory(vacancyId, errHistory);
    updateQaMessagesDom(errHistory);
  } finally {
    qaLoading = false;
    bindQaControls(false);
  }
}

function bindQaControls(disabled) {
  const input = shadowRoot?.getElementById('jh-qa-input');
  const sendBtn = shadowRoot?.querySelector('[data-action="qa-send"]');
  if (input) input.disabled = disabled;
  if (sendBtn) {
    sendBtn.disabled = disabled;
    const icon = disabled
      ? iconMarkup('loader', { size: 16, className: 'jh-spin' })
      : iconMarkup('send', { size: 16 });
    sendBtn.innerHTML = `${icon}<span>Отправить</span>`;
  }
}

/** Клик по «копировать» в пузыре сообщения — делегирование на контейнер (правка 2026-08-20):
 *  `updateQaMessagesDom` целиком перезаписывает `innerHTML` списка на каждый обмен, отдельные
 *  слушатели на кнопках терялись бы при каждом ответе; сам `#jh-qa-messages` при этом не
 *  пересоздаётся, слушатель на нём переживает любое число обменов. */
function bindQaCopyDelegation(messagesBox) {
  messagesBox.addEventListener('click', (e) => {
    const btn = e.target?.closest?.('[data-qa-copy]');
    if (!btn) return;
    const text = btn.getAttribute('data-qa-copy') || '';
    void copyToClipboard(text).then((ok) => {
      btn.innerHTML = iconMarkup(ok ? 'check' : 'copy', { size: 11 });
      setTimeout(() => {
        btn.innerHTML = iconMarkup('copy', { size: 11 });
      }, 1200);
    });
  });
}

function bindQaActions() {
  const sendBtn = shadowRoot?.querySelector('[data-action="qa-send"]');
  const input = shadowRoot?.getElementById('jh-qa-input');
  const messagesBox = shadowRoot?.getElementById('jh-qa-messages');
  if (sendBtn) {
    sendBtn.addEventListener('click', () => onQaSend());
  }
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        onQaSend();
      }
    });
    input.addEventListener('input', autosizeQaInput);
    autosizeQaInput();
  }
  if (messagesBox) {
    bindQaCopyDelegation(messagesBox);
  }
}

function renderScore(record, funnelStatus = null) {
  const s = record.score;
  const statusToShow = funnelStatus ?? record.status ?? currentFunnelStatus ?? null;

  const letterBadge =
    record.letter_required || vacancyExtractor.detectLetterRequired?.(document)
      ? `<span class="jh-pill-badge jh-pill-warn jh-has-tip" data-jh-tip="${escapeAttr('Нужно сопроводительное письмо')}">${iconMarkup('mail', { size: 12 })}<span>Письмо</span></span>`
      : '';

  const competitionBadge = competitionBadgeHtml(
    record.total_responses_count,
    record.competition
  );

  const factCardsBlock = factCardsHtml(record, s);
  const breakdownBlock = scoreBreakdownSectionHtml(s);
  const verdictBlock = verdictHtml(s.one_line_verdict);
  const prosBlock = bulletListSectionHtml('Плюсы', s.pros, 'pros');
  const consBlock = bulletListSectionHtml('Минусы', s.cons, 'cons');
  const redFlagsBlock = bulletListSectionHtml('Красные флаги', s.red_flags, 'flags');

  const vacancyId = record.vacancy_id || currentVacancyId;
  currentScoreRecord = record;
  // Запомнить id строки jobs — fallback для «Сопроводительного», если currentScoreRecord.id
  // не проставлен (stub-вакансия без /score). Сам record.id уже берётся из ScoreResponse.id.
  if (vacancyId && record.id) {
    jobIdCache[vacancyId] = record.id;
  }
  // recommendation=skip — это СОВЕТ модели, а не решение пользователя «Пропустить». Он уже виден
  // как пилюля «Пропустить» рядом с баллом; в skippedCache НЕ кладём, иначе триаж гасится в
  // тупик «Пропущено» без действий на первой же оценке. Пропуск = только явный клик/бэкенд-флаг.
  const qaHistory = getQaHistory(vacancyId);
  const hhShowsApplied = vacancyExtractor.detectAlreadyAppliedOnPage?.(document) ?? false;
  // Компания уже в «Избегать»: либо этот же клик уже зафиксирован в сессии (skippedCache), либо
  // свежий скоринг сам об это споткнулся — жёсткий гейт rules.py всегда цепляет avoid-компанию
  // (rules_from_search_lists), его reason детерминированно начинается с «избегать: ».
  const gate = parseScoreGate(s.gate_triggered);
  const alreadyAvoided =
    (Boolean(vacancyId) && skippedCache.has(vacancyId) && skipReasonCache[vacancyId] === DODGY_COMPANY_REASON) ||
    (Boolean(s.gate_triggered) && /^избегать:/i.test(gate.label));

  // Если компания уже в «Избегать», вакансия автоматически уходит в статус «Пропущено» с причиной DODGY_COMPANY_REASON
  if (alreadyAvoided && vacancyId) {
    skippedCache.add(vacancyId);
    if (!skipReasonCache[vacancyId]) {
      skipReasonCache[vacancyId] = DODGY_COMPANY_REASON;
    }
  }

  const actionsHtml = renderActionsHtml(vacancyId, statusToShow, hhShowsApplied, alreadyAvoided);

  showPanel(`
    <div class="jh-header">
      <div class="jh-header-main">
        ${headerScoreRowHtml(s.overall_score, `
          <div class="jh-rec-group">
            <span class="jh-rec-label">Совет</span>
            <span class="jh-rec ${s.recommendation}">${escapeHtml(RECOMMENDATION_LABEL[s.recommendation] || s.recommendation)}</span>
          </div>
          ${funnelPillHtml(statusToShow)}
          ${letterBadge}
          ${competitionBadge}
        `)}
        ${headerTitleRowHtml(record.title, vacancyId)}
        ${headerMetaHtml(record.company)}
      </div>
    </div>

    <div class="jh-body">

      ${actionsHtml}

      ${factCardsBlock}

      ${breakdownBlock}

      ${verdictBlock}

      ${prosBlock}

      ${redFlagsBlock}

      ${consBlock}

      ${qaThreadHtml(qaHistory)}
    </div>

    <div class="jh-footer">
      ${qaComposerHtml()}
    </div>
  `);
  bindPanelActions();
  bindQaActions();
  currentFunnelStatus = statusToShow;
  panelCollapsed = false;
  updateToolbar();
  updateBarActions();

  if (vacancyId) {
    syncAppliedFromDomIfNeeded(vacancyId);
  }
}

/**
 * Верхний блок действий панели (сразу под баллом):
 *  1. триаж — «Откликнуться» / «Пропустить» (или done-state);
 *  2. чат + сопроводительное.
 */
function renderActionsHtml(vacancyId, status, hhShowsApplied, alreadyAvoided = false) {
  const coverLetter = vacancyId ? coverLetterCache[vacancyId] : null;
  const skipped = Boolean(vacancyId) && skippedCache.has(vacancyId);

  const dodgyBtnHtml = alreadyAvoided
    ? `<button type="button" class="jh-act-btn jh-act-dodgy" disabled title="Компания уже в списке «Избегать»">${DODGY_COMPANY_DONE_HTML}</button>`
    : `<button type="button" class="jh-act-btn jh-act-dodgy" data-action="dodgy-company" title="Добавить компанию в список «Избегать»">${DODGY_COMPANY_HTML}</button>`;

  return `
    <div class="jh-actions">
      ${renderTriageHtml(status, hhShowsApplied, skipped, vacancyId)}

      <div class="jh-act-row">
        <button type="button" class="jh-act-btn" data-action="cover-letter" title="Черновик сопроводительного">${COVER_LETTER_HTML}</button>
        ${dodgyBtnHtml}
      </div>
      ${langToggleHtml(vacancyId)}

      <div class="jh-cover-result" id="jh-cover-result">${coverLetter ? coverLetterResultHtml(coverLetter) : ''}</div>
    </div>`;
}

/** Э4.4 dual_employment_and_contracting_2026.md: переключалка RU/EN рядом с «Сопроводительное».
 *  Ничего не подсвечено — генерация уйдёт без явного `lang`, бэкенд определит язык по резюме сам. */
function langToggleHtml(vacancyId) {
  const lang = vacancyId ? coverLetterLangCache[vacancyId] : null;
  return `
    <div class="jh-lang-toggle" role="group" aria-label="Язык письма">
      <button type="button" class="jh-lang-btn${lang === 'ru' ? ' jh-lang-active' : ''}" data-action="cover-lang" data-lang="ru" title="Русское письмо">RU</button>
      <button type="button" class="jh-lang-btn${lang === 'en' ? ' jh-lang-active' : ''}" data-action="cover-lang" data-lang="en" title="Письмо на английском">EN</button>
    </div>`;
}

/** Точечно обновить активный чип после клика/генерации — без полного ре-рендера панели
 *  (тот же приём, что `updatePanelFunnelStatus`). */
function updateLangToggleUI(vacancyId) {
  const lang = vacancyId ? coverLetterLangCache[vacancyId] : null;
  const container = shadowRoot?.querySelector('.jh-lang-toggle');
  if (!container) return;
  container.querySelectorAll('[data-action="cover-lang"]').forEach((btn) => {
    btn.classList.toggle('jh-lang-active', btn.getAttribute('data-lang') === lang);
  });
}

function onCoverLangClick(lang) {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  if (!vacancyId) return;
  coverLetterLangCache[vacancyId] = lang;
  updateLangToggleUI(vacancyId);
}

/** Триаж: «Откликнуться» / «Пропустить» — первый блок тела (или done-state). */
function renderTriageHtml(status, hhShowsApplied, skipped, vacancyId) {
  if (status === FUNNEL_STATUS.ARCHIVE || status === FUNNEL_STATUS.REJECTED) {
    return `
      <div class="jh-archive-done">
        <span class="jh-banner-text">${iconMarkup('circle-x', { size: 15 })}<span>Отказ — в колонке «Отказ» на доске</span></span>
      </div>`;
  }
  if (status === FUNNEL_STATUS.APPLIED) {
    return `
      <div class="jh-triage-block">
        <div class="jh-skip-picker hidden" id="jh-skip-reasons">
          <p class="jh-skip-picker-label">Почему пропускаем?</p>
          <div class="jh-skip-reasons">${skipReasonsHtml(vacancyId)}</div>
        </div>
        <div class="jh-triage-row">
          <button type="button" class="jh-btn-applied-done" disabled>${APPLIED_DONE_HTML}</button>
          <button type="button" class="jh-btn-skip" data-action="skip-toggle">${SKIP_HTML}</button>
        </div>
      </div>`;
  }
  if (status === FUNNEL_STATUS.OFFER) {
    return `
      <div class="jh-applied-done">
        <span class="jh-banner-text">${iconMarkup('star', { size: 15 })}<span>Статус «Оффер» — в системе</span></span>
      </div>`;
  }
  // Пропущено (ручной skip или авто по recommendation=skip) — done-state без активной кнопки.
  // Проверяем ПОСЛЕ «Отклик»/«Оффер»: реальный прогресс воронки важнее флага пропуска
  // (вакансия, на которую откликнулись вопреки рекомендации skip, не должна гаситься как «Пропущено»).
  if (skipped) {
    const reason = vacancyId ? skipReasonCache[vacancyId] : null;
    const suffix = reason ? ` · ${reason}` : '';
    // «Вернуть» (DELETE /skip) в done-state — тот же стиль/высота, что у «Пропустить»; «Откликнуться» убран.
    return `
      <div class="jh-skip-done">
        <span class="jh-skip-done-label">${iconMarkup('circle-x', { size: 15 })}<span>Пропущено${escapeHtml(suffix)}</span></span>
        <button type="button" class="jh-btn-unskip" data-action="unskip">${UNSKIP_HTML}</button>
      </div>`;
  }

  const hint = hhShowsApplied
    ? `<p class="jh-funnel-hint">На ${listingSiteLabel()} отмечено: вы уже откликнулись.</p>`
    : '';
  return `
    ${hint}
    <div class="jh-triage-block">
      <div class="jh-skip-picker hidden" id="jh-skip-reasons">
        <p class="jh-skip-picker-label">Почему пропускаем?</p>
        <div class="jh-skip-reasons">${skipReasonsHtml(vacancyId)}</div>
      </div>
      <div class="jh-triage-row">
        <button type="button" class="jh-btn-mark-applied" data-action="mark-applied">${MARK_APPLIED_HTML}</button>
        <button type="button" class="jh-btn-skip" data-action="skip-toggle">${SKIP_HTML}</button>
      </div>
    </div>`;
}

// ── EX-4: быстрые on-page действия — черновик письма + триаж-пропуск ──

/** Карточка сгенерированного письма: текст (клик — редактировать на месте) + «копировать».
 *  Правка 2026-08-20: «Править в вебе» убрана — правка теперь прямо здесь (см.
 *  `onCoverEditStartClick`/`coverLetterEditHtml` ниже), уводить в веб больше незачем. */
function coverLetterResultHtml(text) {
  return `
    <div class="jh-cover-box">
      <div class="jh-cover-text" data-action="cover-edit-start" title="Нажмите, чтобы отредактировать">${escapeHtml(text)}</div>
      <div class="jh-cover-actions">
        <button type="button" class="jh-quick-btn" data-action="cover-copy">${iconMarkup('copy', { size: 14 })}<span>Копировать</span></button>
      </div>
    </div>`;
}

/** Карточка письма в режиме правки — textarea + Сохранить/Отмена. */
function coverLetterEditHtml() {
  return `
    <div class="jh-cover-box">
      <textarea class="jh-cover-textarea" id="jh-cover-textarea" maxlength="4000"></textarea>
      <div class="jh-cover-actions">
        <button type="button" class="jh-quick-btn jh-quick-btn-primary" data-action="cover-save">${iconMarkup('check', { size: 14 })}<span>Сохранить</span></button>
        <button type="button" class="jh-quick-btn" data-action="cover-cancel">${iconMarkup('x', { size: 14 })}<span>Отмена</span></button>
      </div>
    </div>`;
}

/** Чипы причин пропуска: LLM-сгенерированные (если есть в кэше) или статичный фолбэк.
 *  «Избегать компанию» НЕ входит — она отдельная статичная кнопка во 2 ряду. */
function skipReasonsHtml(vacancyId) {
  const llm = vacancyId ? skipReasonsLlmCache[vacancyId] : null;
  if (llm && llm.length > 0) {
    return llm
      .map(
        (r) =>
          `<button type="button" class="jh-skip-reason" data-skip-reason="${escapeHtml(r.text)}" data-skip-canonical="${escapeHtml(r.canonical)}">${escapeHtml(r.text)}</button>`,
      )
      .join('');
  }
  // Фолбэк: статичные канонические причины (без «Избегать компанию» — она отдельная кнопка).
  return SKIP_REASONS.filter((r) => r !== DODGY_COMPANY_REASON)
    .map(
      (r) =>
        `<button type="button" class="jh-skip-reason" data-skip-reason="${escapeHtml(r)}" data-skip-canonical="${escapeHtml(r)}">${escapeHtml(r)}</button>`,
    )
    .join('');
}

async function refreshFunnelStatus(vacancyId) {
  if (!vacancyId) {
    currentFunnelStatus = null;
    return null;
  }
  try {
    const response = await sendMessage({ action: 'get_funnel', payload: { vacancy_id: vacancyId } });
    if (response?.ok) {
      currentFunnelStatus = response.data?.status || null;
      // Пропуск зафиксирован в бэкенде (ручной/авто) — отражаем done-state и после перезагрузки.
      // Причину раньше не подтягивали — done-state «Пропущено» на новой вкладке/после очистки
      // storage показывался без неё (skipReasonCache пуст, пока пользователь не пропустит заново).
      if (response.data?.skipped && vacancyId) {
        skippedCache.add(vacancyId);
        if (response.data?.skip_reason) skipReasonCache[vacancyId] = response.data.skip_reason;
      }
      return currentFunnelStatus;
    }
  } catch {
    /* backend недоступен */
  }
  return currentFunnelStatus;
}

function updatePanelFunnelStatus(status) {
  currentFunnelStatus = status;
  if (!panelEl || panelEl.classList.contains('hidden')) return;
  const existing = shadowRoot.getElementById('jh-funnel-pill');
  if (existing) existing.remove();
  if (!status) return;
  const row = shadowRoot.querySelector('.jh-pills-row');
  if (!row) return;
  const wrapper = document.createElement('div');
  wrapper.innerHTML = funnelPillHtml(status);
  const node = wrapper.firstElementChild;
  if (node) row.appendChild(node);
}

function bindPanelActions() {
  const closeBtn = shadowRoot.querySelector('[data-action="close"]');
  if (closeBtn) {
    closeBtn.addEventListener('click', hidePanel);
  }

  const markAppliedBtn = shadowRoot.querySelector('[data-action="mark-applied"]');
  if (markAppliedBtn) {
    markAppliedBtn.addEventListener('click', onMarkAppliedClick);
  }

  const openChatBtn = shadowRoot.querySelector('[data-action="open-chat"]');
  if (openChatBtn) {
    openChatBtn.addEventListener('click', onOpenChatClick);
  }

  // EX-4: on-page быстрые действия
  const coverBtn = shadowRoot.querySelector('[data-action="cover-letter"]');
  if (coverBtn) {
    coverBtn.addEventListener('click', onCoverLetterClick);
  }

  // Э4.4: переключалка RU/EN сопроводительного.
  shadowRoot.querySelectorAll('[data-action="cover-lang"]').forEach((btn) => {
    btn.addEventListener('click', () => onCoverLangClick(btn.getAttribute('data-lang')));
  });

  // Статичная кнопка «Избегать компанию» (во 2 ряду) — отдельная от LLM-чипов пропуска.
  const dodgyBtn = shadowRoot.querySelector('[data-action="dodgy-company"]');
  if (dodgyBtn) {
    dodgyBtn.addEventListener('click', onDodgyCompanyClick);
  }

  const skipToggleBtn = shadowRoot.querySelector('[data-action="skip-toggle"]');
  if (skipToggleBtn) {
    skipToggleBtn.addEventListener('click', onSkipToggle);
  }

  const unskipBtn = shadowRoot.querySelector('[data-action="unskip"]');
  if (unskipBtn) {
    unskipBtn.addEventListener('click', onUnskipClick);
  }

  shadowRoot.querySelectorAll('[data-skip-reason]').forEach((btn) => {
    btn.addEventListener('click', () => onSkipReasonClick(btn.getAttribute('data-skip-reason')));
  });

  // Решение 3: удалить тезис (кнопка справа от каждого пункта Плюсы/Минусы/Красные флаги).
  shadowRoot.querySelectorAll('[data-action="thesis-delete"]').forEach((btn) => {
    btn.addEventListener('click', () => onThesisDeleteClick(btn));
  });

  // навесить действия письма, если оно уже в кэше (после re-render панели)
  bindCoverActions();

  const retryBtn = shadowRoot.querySelector('[data-action="retry-score"]');
  if (retryBtn) {
    retryBtn.addEventListener('click', () => {
      void runScoringFlow({ auto: false });
    });
  }
}

// ── Шаги 1+2: поток «Есть отклик» + автоподстановка письма на getmatch ──
// getmatch монтирует React-модалку `.b-apply-modal` только после клика по нативной кнопке
// «Откликнуться» (её нет в DOM до клика). Глобальный observer ловит появление модалки —
// неважно, открыл её пользователь сам или через кнопку расширения — подставляет сгенерированное
// письмо в `textarea[name="cover_letter"]`, ставит метку «Сгенерировано Copilot» и следит за
// отправкой, чтобы зафиксировать статус воронки только после подтверждения getmatch.

/** Тайм-аут поллинг-ожиданий (появление модалки / textarea / закрытие), мс. */
const GETMATCH_APPLY_WAIT_TIMEOUT = 15000;

/** Неблокирующая метка рядом с полем письма — подсказка, что текст подставил Copilot. */
const GM_LETTER_HINT_TEXT = 'Сгенерировано Copilot';

/** Глобальный наблюдатель появления `.b-apply-modal` (живёт, пока активна вакансия getmatch). */
let gmGlobalModalObserver: MutationObserver | null = null;

/** Наблюдатель ошибок внутри текущей модалки (`.error` / `[class*="error"]`). */
let gmModalErrorObserver: MutationObserver | null = null;

/** Наблюдатель закрытия модалки (backdrop удаляется из DOM) — сигнал подтверждения отправки. */
let gmApplyCloseObserver: MutationObserver | null = null;

/** Привязка submit-обработчика к форме `.b-apply-modal__form`. */
let gmApplySubmitClickListener: ((e: Event) => void) | null = null;

/** Ошибка в модалке — отклик НЕ считается отправленным, даже если модалка закрылась. */
let gmApplyErrorSeen = false;

/** Намерение отправки: true после submit формы, снимается после фиксации статуса/закрытия. */
let gmApplySubmitIntent = false;

/** Фаза 2.3: пока раннер автооткликов ждёт исход getmatch-флоу, здесь — колбэк вместо обычного
 *  setFunnelStatus (раннер сам зовёт /api/pipeline/auto-apply/report с меткой auto_apply_getmatch
 *  — ручной клик продолжает писать через /funnel как раньше, это ортогональный путь). */
let gmAutoApplyResolve: ((result: { outcome: string; letter: string }) => void) | null = null;

function gmApplyModal(): Element | null {
  return document.querySelector('.b-apply-modal')
}

function gmApplyCoverTextarea(root: ParentNode = document): HTMLTextAreaElement | null {
  return root.querySelector(gmApplySel('coverLetterTextarea')) as HTMLTextAreaElement | null
}

/** Ждёт, пока probe вернёт непустое значение — поллинг с паузой, до timeout. */
async function gmWaitFor<T>(probe: () => T | null | undefined, timeoutMs = GETMATCH_APPLY_WAIT_TIMEOUT): Promise<T | null> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const value = probe()
    if (value) return value
    await new Promise((r) => setTimeout(r, 200))
  }
  return null
}

/** Ставит значение в React-контролируемую textarea: нативный value-setter + input-событие
 *  (просто `textarea.value = ...` React не подхватит и перезапишет при re-render). */
function gmSetTextareaValue(textarea: HTMLTextAreaElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set
  if (setter) setter.call(textarea, text)
  else textarea.value = text
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

/** Вставляет письмо в textarea модалки (React монтирует форму чуть позже — поллим textarea). */
async function gmInsertLetterIntoModal(modal: Element, text: string): Promise<HTMLTextAreaElement | null> {
  const textarea = await gmWaitFor(() => gmApplyCoverTextarea(modal))
  if (!textarea) return null
  if (!textarea.value) gmSetTextareaValue(textarea, text)
  return textarea
}

/** Неблокирующая метка «Сгенерировано Copilot» сразу после поля письма. */
function gmAddLetterHint(textarea: HTMLTextAreaElement) {
  if (textarea.parentElement?.querySelector('.gm-copilot-letter-hint')) return
  const hint = document.createElement('span')
  hint.className = 'gm-copilot-letter-hint'
  hint.textContent = GM_LETTER_HINT_TEXT
  Object.assign(hint.style, {
    display: 'inline-block',
    marginTop: '4px',
    fontSize: '12px',
    lineHeight: '1.4',
    color: '#7c3aed',
    fontWeight: '500',
  })
  textarea.insertAdjacentElement('afterend', hint)
}

/** Снимает наблюдатель закрытия модалки. */
function gmStopApplyCloseObserver() {
  if (gmApplyCloseObserver) {
    gmApplyCloseObserver.disconnect()
    gmApplyCloseObserver = null
  }
}

function gmStopModalErrorObserver() {
  if (gmModalErrorObserver) {
    gmModalErrorObserver.disconnect()
    gmModalErrorObserver = null
  }
}

function gmDetachSubmitTracking() {
  if (gmApplySubmitClickListener) {
    document.removeEventListener('submit', gmApplySubmitClickListener, true)
    gmApplySubmitClickListener = null
  }
}

/** Генерирует письмо через `cover_letter` action (нужна уже проскоренная вакансия) и кэширует. */
async function gmGenerateLetter(vacancyId: string | null): Promise<string> {
  const jobId = currentScoreRecord?.id || (vacancyId ? jobIdCache[vacancyId] : null)
  if (!jobId) return ''
  try {
    const response = await sendMessage({ action: 'cover_letter', payload: { job_id: jobId } })
    if (!response?.ok) return ''
    const text = response.data?.cover_letter_text || ''
    if (vacancyId && text) coverLetterCache[vacancyId] = text
    return text
  } catch (err) {
    console.warn('[Job Hunter] генерация письма не удалась:', err)
    return ''
  }
}

/** Наблюдает ошибки внутри модалки: `.error` / `.b-apply-modal__error` / `[class*="error"]`. */
function gmWatchModalErrors(modal: Element) {
  gmStopModalErrorObserver()
  gmModalErrorObserver = new MutationObserver(() => {
    const err = modal.querySelector('.error, .b-apply-modal__error, [class*="error"]')
    if (err) gmApplyErrorSeen = true
  })
  gmModalErrorObserver.observe(modal, { childList: true, subtree: true })
}

/** Показывает в панели предупреждение, что отклик getmatch не подтверждён (ошибка формы). */
function gmShowApplyError(vacancyId: string | null) {
  if (gmAutoApplyResolve) {
    const resolve = gmAutoApplyResolve
    gmAutoApplyResolve = null
    resolve({ outcome: 'error', letter: '' })
    return
  }
  if (!vacancyId) return
  const box = shadowRoot?.getElementById('jh-cover-result')
  const msg =
    '<p class="jh-cover-error">Отклик не подтверждён — проверьте форму getmatch (возможно, ошибка валидации).</p>'
  if (box) box.innerHTML = msg
  else if (currentScoreRecord) {
    // Поля результата ещё нет (панель не перерисована) — просто перерисуем ошибкой триажа не будем,
    // предупреждение достаточно увидеть в консоли; UI-бейдж появится при следующем re-render.
    console.warn('[Job Hunter] getmatch: отклик не подтверждён (ошибка в форме)')
  }
}

/**
 * Фиксирует APPLIED после подтверждённой отправки. Вызывается только когда `gmApplySubmitIntent`
 * уже true и модалка закрылась БЕЗ ошибки.
 */
async function gmConfirmApplied(vacancyId: string | null) {
  gmApplySubmitIntent = false
  gmStopApplyCloseObserver()
  gmStopModalErrorObserver()
  gmDetachSubmitTracking()
  if (!vacancyId) return
  const finalLetter = readCoverLetterFromPage() || coverLetterCache[vacancyId] || ''

  // Фаза 2.3: раннер автооткликов ждёт этот исход и сам зовёт /api/pipeline/auto-apply/report
  // (source=auto_apply_getmatch) — здесь НЕ трогаем /funnel, иначе стадия уйдёт с меткой
  // api_funnel и не попадёт в дневной лимит (2.7) площадки.
  if (gmAutoApplyResolve) {
    const resolve = gmAutoApplyResolve
    gmAutoApplyResolve = null
    resolve({ outcome: 'applied', letter: finalLetter })
    return
  }

  await setFunnelStatus(vacancyId, FUNNEL_STATUS.APPLIED, {
    cover_letter: finalLetter || undefined,
  })
  if (currentScoreRecord) {
    renderScore(currentScoreRecord, FUNNEL_STATUS.APPLIED)
  }
}

/**
 * Перехватывает отправку формы модалки (submit в capture-фазе): ставит `gmApplySubmitIntent` и
 * вешает observer на закрытие модалки — когда `.b-apply-modal` исчезнет из DOM, проверяем, была
 * ли ошибка, и фиксируем APPLIED (или показываем предупреждение).
 */
function gmAttachSubmitTracking(vacancyId: string | null) {
  gmDetachSubmitTracking()
  gmApplySubmitClickListener = (e: Event) => {
    const form = (e.target as Element | null)?.closest?.('.b-apply-modal__form')
    if (!form) return
    if (gmApplySubmitIntent) return
    gmApplySubmitIntent = true

    // Наблюдаем закрытие модалки (backdrop/`.b-apply-modal` удаляется из DOM).
    gmStopApplyCloseObserver()
    gmApplyCloseObserver = new MutationObserver(() => {
      if (gmApplyModal()) return // ещё открыта
      gmApplyCloseObserver?.disconnect()
      gmApplyCloseObserver = null
      if (gmApplyErrorSeen) {
        console.warn('[Job Hunter] getmatch: отклик не подтверждён (ошибка в форме)')
        gmApplySubmitIntent = false
        gmShowApplyError(vacancyId)
        return
      }
      void gmConfirmApplied(vacancyId)
    })
    gmApplyCloseObserver.observe(document.body, { childList: true, subtree: true })
  }
  document.addEventListener('submit', gmApplySubmitClickListener, true)
}

/**
 * Обработчик появления модалки: письмо (из кэша или генерация) → вставка + метка → наблюдение
 * ошибок → перехват отправки. Срабатывает один раз на каждую модалку (метка на самом элементе).
 */
async function gmHandleModalAppeared(modal: HTMLElement, vacancyId: string | null) {
  gmApplyErrorSeen = false

  let letter = vacancyId ? coverLetterCache[vacancyId] || '' : ''
  if (!letter) letter = await gmGenerateLetter(vacancyId)

  if (letter) {
    const textarea = await gmInsertLetterIntoModal(modal, letter)
    if (textarea) gmAddLetterHint(textarea)
  }

  gmWatchModalErrors(modal)
  gmAttachSubmitTracking(vacancyId)

  // Раннер (2.3 fix): живая проверка 2026-08-18 показала реальную модалку — форма с полем
  // города, textarea письма и кнопкой «Отправить отклик» (не 5-шаговый визард — тот был
  // артефактом разлогиненной сессии). В ручном режиме владелец кликает эту кнопку сам —
  // здесь только для `runnerMode` (сигнал — активный `gmAutoApplyResolve`), иначе фоновая
  // вкладка без человека держит письмо в модалке вечно и раннер уходит в таймаут (20с).
  if (gmAutoApplyResolve) {
    const submitBtn = gmFindModalSubmitButton(modal)
    if (submitBtn) {
      await new Promise((r) => setTimeout(r, 300 + Math.random() * 400))
      submitBtn.click()
    }
  }
}

/** Кнопка «Отправить отклик» внутри модалки — финальный submit формы отклика getmatch. */
function gmFindModalSubmitButton(modal: HTMLElement): HTMLElement | null {
  const buttons = Array.from(modal.querySelectorAll('button'))
  const match = buttons.find((b) =>
    /^отправить отклик$/i.test((b.textContent || '').replace(/\s+/g, ' ').trim())
  )
  return (match as HTMLElement) || null
}

/** Глобальный observer модалки — вешается один раз на страницу вакансии getmatch. */
function gmEnsureGlobalModalObserver() {
  if (gmGlobalModalObserver) return
  gmGlobalModalObserver = new MutationObserver(() => {
    const modal = gmApplyModal()
    if (!modal) return
    const el = modal as HTMLElement
    if (el.dataset.gmHandled === '1') return
    el.dataset.gmHandled = '1'
    const vacancyId = vacancyExtractor.extractVacancyId(location.href)
    void gmHandleModalAppeared(el, vacancyId)
  })
  gmGlobalModalObserver.observe(document.body, { childList: true, subtree: true })
}

/** Полная остановка глобального observer + связанных обработчиков (teardown адаптера). */
function gmStopGlobalModalObserver() {
  if (gmGlobalModalObserver) {
    gmGlobalModalObserver.disconnect()
    gmGlobalModalObserver = null
  }
  gmStopApplyCloseObserver()
  gmStopModalErrorObserver()
  gmDetachSubmitTracking()
  gmApplySubmitIntent = false
}

/**
 * Поток «Откликнуться» на getmatch: генерируем письмо (если ещё нет) ДО открытия модалки, кликаем
 * нативную кнопку «Откликнуться»; модалку ловит глобальный observer (вставка письма + отправка).
 * setFunnelStatus — только после подтверждения getmatch (закрытие модалки без ошибки).
 *
 * Раннер автооткликов (2.3) зовёт с `runnerMode: true` — функция дожидается исхода (успех/ошибка/
 * таймаут) вместо fire-and-forget манильного клика, и при `dryRun: true` вообще не кликает
 * нативную кнопку (2.2: дойти до финального клика, залогировать «кликнул бы», не кликая).
 */
async function onGetmatchApplyFlow(
  vacancyId: string,
  opts: { dryRun?: boolean; runnerMode?: boolean } = {},
): Promise<{ outcome: string; letter: string } | void> {
  const btn = shadowRoot?.querySelector('[data-action="mark-applied"]');

  // Письмо ещё не сгенерировано — генерируем ДО открытия модалки, чтобы поле не пустовало.
  let letter = coverLetterCache[vacancyId];
  if (!letter) {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Генерируем письмо…</span>`;
    }
    letter = await gmGenerateLetter(vacancyId);
  }

  if (opts.dryRun) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = MARK_APPLIED_HTML;
    }
    return { outcome: 'dry_run', letter: letter || '' };
  }

  // Кнопка в расширении становится «Ожидание отправки» до подтверждения getmatch.
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Ожидаем отправку…</span>`;
  }

  // Кликаем нативную кнопку «Откликнуться» на странице getmatch — дальше глобальный observer.
  const native = findGetmatchApplyButton();
  if (!native) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = MARK_APPLIED_HTML;
    }
    renderError('Не удалось найти кнопку «Откликнуться» на странице getmatch');
    return opts.runnerMode ? { outcome: 'no_button', letter: '' } : undefined;
  }

  if (!opts.runnerMode) {
    (native as HTMLElement).click();
    return;
  }

  return new Promise<{ outcome: string; letter: string }>((resolve) => {
    gmAutoApplyResolve = resolve;
    (native as HTMLElement).click();
    // Страховочный таймаут — если getmatch поменяет DOM и модалка не появится, раннер не должен
    // зависнуть навсегда (2.1: раннер переходит к следующему кандидату по очереди/дневному лимиту).
    setTimeout(() => {
      if (gmAutoApplyResolve === resolve) {
        gmAutoApplyResolve = null;
        resolve({ outcome: 'timeout', letter: letter || '' });
      }
    }, 20000);
  });
}

/** Нативная кнопка «Откликнуться» на getmatch: `.b-apply-block button` или из селекторов. */
function findGetmatchApplyButton(): Element | null {
  const candidates = [
    '.b-apply-block button',
    ...GM_RESPONSE_LINK_SELECTORS,
  ];
  for (const sel of candidates) {
    for (const el of Array.from(document.querySelectorAll(sel))) {
      const label = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (/^откликнуться$/i.test(label)) return el;
    }
  }
  return null;
}

async function onMarkAppliedClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  if (!vacancyId) return;

  // getmatch: «Откликнуться» = сгенерировать письмо → кликнуть нативную кнопку → дождаться
  // модалки → вставить письмо → ждать отправки. `setFunnelStatus` вызывается только после
  // подтверждения getmatch (закрытие модалки без ошибки) в gmStartApplyTracking.
  if (getSite() === 'getmatch') {
    await onGetmatchApplyFlow(vacancyId);
    return;
  }

  const btn = shadowRoot?.querySelector('[data-action="mark-applied"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = SAVING_HTML;
  }

  try {
    const coverLetter = readCoverLetterFromPage();
    // Идентичность + текст JD из DOM — чтобы stub (клик без /score) не писал пустую карточку
    // и мог сгенерировать сопроводительное без предварительного скоринга.
    let identity: { title?: string; company?: string; vacancy_text?: string } = {};
    try {
      const parsed = vacancyExtractor.parseVacancyFromDom(location.href);
      if (parsed.title) identity.title = parsed.title;
      if (parsed.company) identity.company = parsed.company;
      if (parsed.text) identity.vacancy_text = parsed.text;
    } catch { /* identity подтянется скорингом */ }
    // Retry: иногда POST /funnel фейлится из-за transient-сети/503 — было «не регистрирует».
    // 3 попытки с нарастающей паузой (1с/2с/4с); последняя ошибка — наружу.
    let lastErr = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        await setFunnelStatus(vacancyId, FUNNEL_STATUS.APPLIED, {
          cover_letter: coverLetter || undefined,
          ...identity,
        });
        if (currentScoreRecord) {
          renderScore(currentScoreRecord, FUNNEL_STATUS.APPLIED);
        }
        return;
      } catch (err) {
        lastErr = err;
        // Последняя попытка — не ждём.
        if (attempt < 2) {
          await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        }
      }
    }
    throw lastErr || new Error('Не удалось обновить статус');
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = MARK_APPLIED_HTML;
    }
    renderError(String(err.message || err));
  }
}

/** EX-4: сгенерировать черновик сопроводительного (LLM) и показать на странице. */
async function onCoverLetterClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  const jobId = currentScoreRecord?.id || (vacancyId ? jobIdCache[vacancyId] : null);
  if (!jobId) {
    const box = shadowRoot?.getElementById('jh-cover-result');
    if (box) {
      box.innerHTML =
        `<p class="jh-cover-error">Сначала оцените вакансию — письмо пишется в её запись</p>`;
    }
    return;
  }

  const btn = shadowRoot?.querySelector('[data-action="cover-letter"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Генерируем…</span>`;
  }
  const box = shadowRoot?.getElementById('jh-cover-result');

  try {
    const lang = vacancyId ? coverLetterLangCache[vacancyId] : null;
    const response = await sendMessage({
      action: 'cover_letter',
      payload: { job_id: jobId, lang: lang || undefined },
    });
    if (!response?.ok) {
      throw new Error(response?.error || 'Не удалось сгенерировать письмо');
    }
    const text = response.data?.cover_letter_text || '';
    if (vacancyId) {
      coverLetterCache[vacancyId] = text;
      if (response.data?.lang) {
        coverLetterLangCache[vacancyId] = response.data.lang;
        updateLangToggleUI(vacancyId);
      }
    }
    if (box) {
      box.innerHTML = coverLetterResultHtml(text);
      bindCoverActions();
    }
  } catch (err) {
    if (box) {
      box.innerHTML = `<p class="jh-cover-error">${escapeHtml(String(err.message || err))}</p>`;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = COVER_LETTER_HTML;
    }
  }
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

async function onCoverCopyClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  const text = vacancyId ? coverLetterCache[vacancyId] : null;
  if (!text) return;
  const ok = await copyToClipboard(text);
  const btn = shadowRoot?.querySelector('[data-action="cover-copy"]');
  if (!btn) return;
  btn.innerHTML = ok
    ? `${iconMarkup('check', { size: 14 })}<span>Скопировано</span>`
    : `${iconMarkup('copy', { size: 14 })}<span>Не удалось</span>`;
  setTimeout(() => {
    const b = shadowRoot?.querySelector('[data-action="cover-copy"]');
    if (b) b.innerHTML = `${iconMarkup('copy', { size: 14 })}<span>Копировать</span>`;
  }, 1800);
}

/** Клик по тексту письма — режим правки на месте (правка 2026-08-20, замена «Править в вебе»). */
function onCoverEditStartClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  const text = (vacancyId ? coverLetterCache[vacancyId] : null) || '';
  const box = shadowRoot?.getElementById('jh-cover-result');
  if (!box) return;
  box.innerHTML = coverLetterEditHtml();
  const textarea = shadowRoot?.getElementById('jh-cover-textarea');
  if (textarea) {
    textarea.value = text;
    textarea.focus();
    textarea.setSelectionRange(text.length, text.length);
  }
  bindCoverEditActions();
}

function onCoverCancelClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  const text = (vacancyId ? coverLetterCache[vacancyId] : null) || '';
  const box = shadowRoot?.getElementById('jh-cover-result');
  if (!box) return;
  box.innerHTML = coverLetterResultHtml(text);
  bindCoverActions();
}

async function onCoverSaveClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  const jobId = currentScoreRecord?.id || (vacancyId ? jobIdCache[vacancyId] : null);
  const textarea = shadowRoot?.getElementById('jh-cover-textarea');
  const text = (textarea?.value || '').trim();
  if (!jobId || !textarea) return;

  const btn = shadowRoot?.querySelector('[data-action="cover-save"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Сохраняем…</span>`;
  }
  try {
    const response = await sendMessage({
      action: 'cover_letter_save',
      payload: { job_id: jobId, cover_letter_text: text },
    });
    if (!response?.ok) {
      throw new Error(response?.error || 'Не удалось сохранить письмо');
    }
    if (vacancyId) coverLetterCache[vacancyId] = text;
    const box = shadowRoot?.getElementById('jh-cover-result');
    if (box) {
      box.innerHTML = coverLetterResultHtml(text);
      bindCoverActions();
    }
  } catch (err) {
    // Не `renderError` — та подменяет ВСЮ панель на экран «Не удалось оценить», уместный для
    // провала скоринга, но не для сохранения письма (потерялась бы правка владельца в textarea).
    // Вместо этого — компактная строка ошибки под кнопками, textarea остаётся как есть.
    const coverBox = shadowRoot?.querySelector('#jh-cover-result .jh-cover-box');
    let errEl = coverBox?.querySelector('.jh-cover-error');
    if (coverBox && !errEl) {
      errEl = document.createElement('p');
      errEl.className = 'jh-cover-error';
      coverBox.appendChild(errEl);
    }
    if (errEl) errEl.textContent = String(err.message || err);
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `${iconMarkup('check', { size: 14 })}<span>Сохранить</span>`;
    }
  }
}

function bindCoverEditActions() {
  const saveBtn = shadowRoot?.querySelector('[data-action="cover-save"]');
  if (saveBtn) saveBtn.addEventListener('click', onCoverSaveClick);
  const cancelBtn = shadowRoot?.querySelector('[data-action="cover-cancel"]');
  if (cancelBtn) cancelBtn.addEventListener('click', onCoverCancelClick);
}

function bindCoverActions() {
  const copyBtn = shadowRoot?.querySelector('[data-action="cover-copy"]');
  if (copyBtn) copyBtn.addEventListener('click', onCoverCopyClick);
  const textBox = shadowRoot?.querySelector('[data-action="cover-edit-start"]');
  if (textBox) textBox.addEventListener('click', onCoverEditStartClick);
}

/** EX-4: показать/скрыть чипы причин пропуска. */
function onSkipToggle() {
  const box = shadowRoot?.getElementById('jh-skip-reasons');
  if (box) box.classList.toggle('hidden');
}

/** EX-4: зафиксировать пропуск с выбранной причиной (POST /skip). */
async function onSkipReasonClick(reason) {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  if (!vacancyId || !reason) return;
  const s = currentScoreRecord?.score;
  const btn = shadowRoot?.querySelector('[data-skip-reason="' + cssEscape(reason) + '"]');
  if (btn) {
    btn.disabled = true;
    btn.classList.add('jh-skip-reason-pending');
  }
  try {
    const canonical = btn?.getAttribute('data-skip-canonical') || reason;
    const response = await sendMessage({
      action: 'skip',
      payload: {
        vacancy_id: vacancyId,
        skip_reason: canonical,
        url: currentScoreRecord?.url,
        title: currentScoreRecord?.title,
        company: currentScoreRecord?.company,
        overall_score: s?.overall_score,
        recommendation: s?.recommendation,
      },
    });
    if (!response?.ok) {
      throw new Error(response?.error || 'Не удалось записать пропуск');
    }
    skippedCache.add(vacancyId);
    skipReasonCache[vacancyId] = canonical;
    if (currentScoreRecord) {
      renderScore(currentScoreRecord, currentFunnelStatus);
    }
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('jh-skip-reason-pending');
    }
    renderError(String(err.message || err));
  }
}

/** Статичная кнопка «Избегать компанию» — добавляет компанию в список «Избегать» резюме
 *  и фиксирует пропуск с причиной «Избегать компанию» (POST /skip). Не зависит от LLM-чипов. */
async function onDodgyCompanyClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  if (!vacancyId) return;
  const s = currentScoreRecord?.score;
  const btn = shadowRoot?.querySelector('[data-action="dodgy-company"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Добавляем…</span>`;
  }
  try {
    const response = await sendMessage({
      action: 'skip',
      payload: {
        vacancy_id: vacancyId,
        skip_reason: DODGY_COMPANY_REASON,
        url: currentScoreRecord?.url,
        title: currentScoreRecord?.title,
        company: currentScoreRecord?.company,
        overall_score: s?.overall_score,
        recommendation: s?.recommendation,
      },
    });
    if (!response?.ok) {
      throw new Error(response?.error || 'Не удалось добавить компанию в «Избегать»');
    }
    skippedCache.add(vacancyId);
    skipReasonCache[vacancyId] = DODGY_COMPANY_REASON;
    if (currentScoreRecord) {
      renderScore(currentScoreRecord, currentFunnelStatus);
    }
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = DODGY_COMPANY_HTML;
    }
    renderError(String(err.message || err));
  }
}

/** Экранирование значения для CSS-селектора [attr="..."]. */
function cssEscape(s) {
  return String(s).replace(/"/g, '\\"');
}

/** Снять пропуск (DELETE /skip): вернуть вакансию в воронку и восстановить активный триаж.
 *  Кнопка «Вернуть» живёт в done-state «Пропущено» — та же высота/стиль, что у «Пропустить». */
async function onUnskipClick() {
  const vacancyId = currentVacancyId || currentScoreRecord?.vacancy_id;
  if (!vacancyId) return;

  const btn = shadowRoot?.querySelector('[data-action="unskip"]');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Возвращаем…</span>`;
  }

  try {
    const response = await sendMessage({ action: 'unskip', payload: { vacancy_id: vacancyId } });
    if (!response?.ok) {
      throw new Error(response?.error || 'Не удалось снять пропуск');
    }
    skippedCache.delete(vacancyId);
    delete skipReasonCache[vacancyId];
    if (currentScoreRecord) {
      renderScore(currentScoreRecord, currentFunnelStatus);
    }
  } catch (err) {
    renderError(String(err.message || err));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = UNSKIP_HTML;
    }
  }
}

function readCoverLetterFromPage(root = document) {
  return vacancyExtractor.readCoverLetterFromPage?.(root) ?? ''
}

async function setFunnelStatus(vacancyId, status, extras: { cover_letter?: string; published_at?: string; offer_at?: string; title?: string; company?: string; vacancy_text?: string } = {}) {
  const key = `${vacancyId}:${status}:${extras.cover_letter || ''}`;
  const pending = _funnelStatusInFlight.get(key);
  if (pending) return pending;

  const run = (async () => {
    const payload: any = { vacancy_id: vacancyId, status };
    if (extras.cover_letter) payload.cover_letter = extras.cover_letter;
    if (extras.published_at) payload.published_at = extras.published_at;
    if (extras.offer_at) payload.offer_at = extras.offer_at;
    if (extras.title) payload.title = extras.title;
    if (extras.company) payload.company = extras.company;
    if (extras.vacancy_text) payload.vacancy_text = extras.vacancy_text;
    const response = await sendMessage({
      action: 'update_status',
      payload,
    });
    if (!response?.ok) {
      throw new Error(response?.error || 'Не удалось обновить статус');
    }
    // Запомнить job_id — чтобы «Сопроводительное» работало и по stub-вакансии (клик
    // «Откликнуться» без /score). Без id кнопка упиралась в «Сначала оцените вакансию».
    if (response.data?.job_id) {
      jobIdCache[vacancyId] = response.data.job_id;
      if (currentScoreRecord && !currentScoreRecord.id) {
        currentScoreRecord.id = response.data.job_id;
      }
    }
    currentFunnelStatus = status;
    if (currentScoreRecord) {
      currentScoreRecord.status = status;
    }
    updatePanelFunnelStatus(status);

    const cacheKey = `score:${vacancyId}`;
    chrome.storage.local.get(cacheKey, (result) => {
      const cached = result[cacheKey];
      if (cached) {
        cached.status = status;
        void writeScoreCache(vacancyId, cached);
      }
    });
    return response;
  })().finally(() => {
    _funnelStatusInFlight.delete(key);
  });

  _funnelStatusInFlight.set(key, run);
  return run;
}

/** Если на HH виден отклик, а в воронке ещё «Просмотрено» — подтянуть «Отклик».
 *
 * Работает ТОЛЬКО для hh.ru: там «отклик отправлен» рендерится в SSR-разметку страницы и
 * детектится надёжно (`detectAlreadyAppliedOnPage`). На getmatch состояние «уже откликался»
 * приходит клиентским XHR уже после загрузки DOM, а `detectGetmatchAlreadyApplied` видит только
 * разрозненные i18n-строки из Flight Stream — раньше это давало ложный «Отклик» на каждой
 * просмотренной вакансии (баг 2026-08-15: на все вакансии проставлялся статус «Есть отклик»).
 * getmatch-отклики корректно попадают в воронку через синк `/applications`, не через DOM здесь. */
async function syncAppliedFromDomIfNeeded(vacancyId) {
  if (!vacancyId || vacancyExtractor.detectVacancyArchived?.(document)) return;
  if (vacancyExtractor.site !== 'hh') return;
  if (!vacancyExtractor.detectAlreadyAppliedOnPage?.(document)) return;
  if (_appliedSyncInFlight.has(vacancyId)) return;

  let status = currentFunnelStatus;
  if (!status) {
    status = await refreshFunnelStatus(vacancyId);
  }
  if (status === FUNNEL_STATUS.APPLIED) return;
  if (status && status !== FUNNEL_STATUS.VIEWED) return;

  _appliedSyncInFlight.add(vacancyId);
  try {
    await setFunnelStatus(vacancyId, FUNNEL_STATUS.APPLIED);
    console.log('[Job Hunter] авто-синх: HH → статус «Отклик»');
    if (currentScoreRecord && !panelEl?.classList.contains('hidden')) {
      renderScore(currentScoreRecord, FUNNEL_STATUS.APPLIED);
    }
  } catch (err) {
    console.warn('[Job Hunter] авто-синх отклика не удался:', err);
  } finally {
    _appliedSyncInFlight.delete(vacancyId);
  }
}

function sendMessage(message): Promise<any> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

function onCancelScoreClick() {
  if (!isLoading) return;
  cancelScoreOperation();
  restoreAfterCancel();
}

function onExpandPanelClick() {
  expandPanel();
}

function parseHealthMeta(parsed?: { parse_method?: string } | null) {
  const method = parsed?.parse_method;
  if (getSite() !== 'hh') return method ? { method } : {};
  const pack = getSelectors();
  return {
    method,
    config_version: pack.version,
    config_origin: pack.origin,
  };
}

async function runScoringFlow({ auto = false } = {}) {
  if (isLoading) return;

  void ensureExtConfig();
  void ensureScoreBreakdownMax();
  ensureVacancyExtractor();
  snapshotBeforeScore = takeUiSnapshot();
  const runId = beginScoreOperation();
  setLoading(true);
  panelCollapsed = false;
  renderSkeleton(
    auto ? 'Ждём полную загрузку вакансии…' : 'Ждём загрузку вакансии…'
  );

  const waitOpts = {
    extractor: vacancyExtractor,
    shouldCancel: () => !isScoreRunActive(runId),
  };

  try {
    const waitResult = auto
      ? await waitForVacancyStable(waitOpts)
      : await waitForVacancyDomReady(waitOpts);
    const { ready, parsed, timedOut, cancelled } = waitResult;

    if (cancelled || !isScoreRunActive(runId)) {
      restoreAfterCancel();
      return;
    }

    console.log('[Job Hunter] parsed:', {
      title: parsed.title,
      company: parsed.company,
      salary: parsed.salary,
      textLen: parsed.text.length,
      vacancy_id: parsed.vacancy_id,
      letter_required: parsed.letter_required,
      total_responses_count: parsed.total_responses_count,
      competition: parsed.competition,
      page_type: parsed.page_type,
      parse_method: parsed.parse_method,
      domReady: ready,
      timedOut,
    });

    if (!ready) {
      // FR2-71: пустой парсинг вакансии → WARNING в «Логи» (редизайн hh/getmatch).
      reportParseHealth({
        site: getSite() === 'getmatch' ? 'getmatch' : getSite() === 'habr' ? 'habr' : 'hh',
        page: 'vacancy',
        reason: timedOut ? 'vacancy_timeout' : 'vacancy_empty',
        detail: `textLen=${parsed?.text?.length ?? 0}`,
        ...parseHealthMeta(parsed),
      });
      setLoading(false);
      renderError(
        timedOut
          ? 'Страница не успела загрузиться за 8 с. Обновите вакансию (F5) и нажмите «Оценить» снова.'
          : 'Не удалось распарсить вакансию: текст слишком короткий или селекторы не сработали.'
      );
      return;
    }

    // E-02/Этап 6 §6.1: площадка формально умеет показывать счётчик (supportsResponsesCount),
    // страница не в архиве, а счётчика всё равно нет — на живом hh.ru (2026-08-18) это норма,
    // не поломка селектора: страница вакансии больше не отдаёт это поле вовсе. WARNING остаётся
    // как канарейка на случай, если hh вернёт счётчик на эту страницу.
    if (
      vacancyExtractor?.supportsResponsesCount &&
      !parsed.is_archived &&
      parsed.total_responses_count == null
    ) {
      reportParseHealth({
        site: getSite() === 'getmatch' ? 'getmatch' : getSite() === 'habr' ? 'habr' : 'hh',
        page: 'vacancy',
        reason: 'responses_count_missing',
        detail: `vacancy_id=${parsed.vacancy_id ?? ''}`,
        ...parseHealthMeta(parsed),
      });
    }

    if (!isScoreRunActive(runId)) {
      restoreAfterCancel();
      return;
    }

    renderSkeleton('Оцениваем вакансию через LLM…', {
      company: parsed.company,
      title: parsed.title,
    });

    const response = await sendMessage({
      action: 'score',
      payload: vacancyExtractor.buildScorePayload(parsed),
    });

    if (!isScoreRunActive(runId)) {
      restoreAfterCancel();
      return;
    }

    if (!response?.ok) {
      throw new Error(response?.error || 'Неизвестная ошибка backend');
    }

    const record = mergeParsedJobMeta(
      {
        ...response.data,
        letter_required: response.data.letter_required ?? parsed.letter_required,
        total_responses:
          response.data.total_responses ?? parsed.total_responses_count ?? null,
        total_responses_count:
          response.data.total_responses ?? parsed.total_responses_count ?? null,
        competition: parsed.competition,
        is_archived: Boolean(parsed.is_archived || response.data.is_archived),
      },
      parsed,
    );
    const funnelStatus =
      record.status ||
      (record.is_archived ? FUNNEL_STATUS.REJECTED : FUNNEL_STATUS.VIEWED);
    snapshotBeforeScore = null;
    if (record.vacancy_id) {
      await ensureScoreBreakdownMax(true);
      await loadQaHistory(record.vacancy_id);
    }
    renderScore(record, funnelStatus);
    setSeenBadge(true);
    currentFunnelStatus = funnelStatus;
    await syncAppliedFromDomIfNeeded(parsed.vacancy_id);

    if (parsed.vacancy_id) {
      void writeScoreCache(parsed.vacancy_id, record);
      if (shouldPollSalary(record)) {
        void pollSalaryEstimateIntoRecord(parsed.vacancy_id, record, funnelStatus);
      }
      // LLM-причины пропуска: поллим, пока фон не сгенерирует чипы.
      void pollSkipReasonsIntoCache(parsed.vacancy_id, funnelStatus);
    }
  } catch (err) {
    if (!isScoreRunActive(runId) || isScoreCancelledError(err)) {
      restoreAfterCancel();
      return;
    }
    const msg = String(err.message || err);
    renderError(msg);
  } finally {
    if (isScoreRunActive(runId)) {
      setLoading(false);
    } else {
      updateToolbar();
    }
  }
}

function onScoreClick() {
  return runScoringFlow({ auto: false });
}

/** Пока открыт экран «Аккаунт», свои кнопки действий из бара прячем — они к вакансии,
 *  а не к настройкам. */
function onDockAccountToggle() {
  updateBarActions();
}

/**
 * Автоскоринг при открытии вакансии на hh.ru: как будто владелец нажал «Оценить»,
 * но только для вакансий, которых ещё нет в системе (не seen) и без закешированного
 * скоринга. Ручной перескор всегда доступен кнопкой — автоскоринг не блокирует его.
 *
 * Гарантия полной загрузки текста: runScoringFlow({auto:true}) использует
 * waitForVacancyStable (текст стабилен 700мс подряд), а не быстрый waitForVacancyDomReady.
 */
async function maybeAutoScore(vacancyId) {
  if (!vacancyId) return;
  if (isLoading) return;

  // Вакансии, которых ещё нет в системе — только для них автоскоринг.
  let seen = false;
  try {
    const resp = await sendMessage({
      action: 'check_seen',
      payload: { vacancy_id: vacancyId },
    });
    seen = Boolean(resp?.ok && resp.data?.seen);
  } catch {
    seen = false;
  }
  if (seen) return;

  // Был ли уже скоринг в этой сессии — не дублируем (владелец перешёл и вернулся).
  const cacheKey = `score:${vacancyId}`;
  try {
    const result = await chrome.storage.local.get(cacheKey);
    if (result[cacheKey]?.score) return;
  } catch {
    /* storage недоступен — продолжаем, лучше перескорить, чем потерять */
  }

  // Навигация могла сменить URL за время проверок — не пускаем автоскоринг по
  // ушедшей странице.
  if (vacancyExtractor.extractVacancyId(location.href) !== vacancyId) return;

  void runScoringFlow({ auto: true });
}

function resetForNavigation() {
  ensureVacancyExtractor();
  const vacancyId = vacancyExtractor.extractVacancyId(location.href);
  if (vacancyId === currentVacancyId) return;

  cancelScoreOperation();
  currentVacancyId = vacancyId;
  hidePanel();
  hideToast();
  setLoading(false);
  panelCollapsed = false;
  snapshotBeforeScore = null;
  currentFunnelStatus = null;
  currentSeen = false;

  if (!vacancyId) {
    setSeenBadge(false);
    return;
  }

  refreshSeenBadge(vacancyId);

  chrome.storage.local.get(`score:${vacancyId}`, async (result) => {
    const cacheKey = `score:${vacancyId}`;
    const cached = result[cacheKey];
    await ensureExtConfig();
    await ensureScoreBreakdownMax(true);
    await loadQaHistory(vacancyId);
    const funnelStatus = await refreshFunnelStatus(vacancyId);
    const parsed = ensureVacancyExtractor().parseVacancyFromDom();
    // На форме «доп. вопрос при отклике» (isVacancyResponseFormPage) DOM — не вакансийный: общий
    // фолбэк `h1` в HH_FALLBACKS.title подхватывает заголовок формы вместо названия вакансии,
    // и сверка с кэшем по заголовку ложно бракует валидный скор (FR2-79 — «мёртвый путь»,
    // приходилось возвращаться на саму вакансию за чатом). Тут сверяем только vacancy_id.
    const onResponseForm = isVacancyResponseFormPage();
    const cacheUsable = cached?.score && (onResponseForm || scoreCacheMatchesDom(cached, parsed));
    if (cacheUsable) {
      // На форме отклика тот же мусорный DOM (см. коммент выше) испортил бы заголовок/компанию
      // при мерже поверх кэша («Отклик на вакансию» вместо реального названия) — берём кэш как есть.
      const hydrated = onResponseForm ? cached : mergeParsedJobMeta(cached, parsed);
      renderScore(hydrated, funnelStatus);
      // Кэш мог быть снят в момент estimate_pending=true (фон ещё считал вилку) — без поллера
      // здесь «оценка…» висела бы навсегда, пока пользователь не нажмёт «Обновить».
      if (shouldPollSalary(hydrated)) {
        void pollSalaryEstimateIntoRecord(vacancyId, hydrated, funnelStatus);
      }
      // LLM-причины пропуска: если их ещё нет в кэше сессии — поллим (фон мог уже сгенерировать
      // после скоринга, но до того как пользователь вернулся на вкладку).
      if (!skipReasonsLlmCache[vacancyId]) {
        void pollSkipReasonsIntoCache(vacancyId, funnelStatus);
      }
    } else if (cached?.score) {
      chrome.storage.local.remove(cacheKey);
      void maybeAutoScore(vacancyId);
    } else {
      // Нет закешированного скоринга. Вакансия может быть уже проскорена (seen), но кэш
      // расширения очищен / это новая вкладка — тогда тянем запись с бэкенда и сразу
      // показываем результаты, без кнопки «Оценить ещё раз». Если не seen — автоскоринг.
      let seenConfirmed = false;
      try {
        const seenResp = await sendMessage({
          action: 'check_seen',
          payload: { vacancy_id: vacancyId },
        });
        if (seenResp?.ok && seenResp.data?.seen) {
          seenConfirmed = true;
          const recResp = await sendMessage({
            action: 'get_vacancy_record',
            payload: { vacancy_id: vacancyId },
          });
          if (recResp?.ok && recResp.data?.score) {
            const record = mergeParsedJobMeta(recResp.data, parsed);
            const status =
              record.status ||
              (record.is_archived ? FUNNEL_STATUS.REJECTED : FUNNEL_STATUS.VIEWED);
            renderScore(record, status);
            setSeenBadge(true);
            currentFunnelStatus = status;
            void writeScoreCache(vacancyId, record);
            if (shouldPollSalary(record)) {
              void pollSalaryEstimateIntoRecord(vacancyId, record, status);
            }
            if (!skipReasonsLlmCache[vacancyId]) {
              void pollSkipReasonsIntoCache(vacancyId, status);
            }
            return;
          }
        }
      } catch {
        // seen/record недоступны — падаем на автоскоринг.
      }
      if (onResponseForm) {
        // На форме вопросов парсить и скорить нечего (нет текста JD) — тихо остаёмся без скора
        // вместо автоскоринга по мусорному DOM; настоящая скоринг-попытка идёт со страницы вакансии.
      } else if (seenConfirmed) {
        // Бэкенд подтвердил, что вакансия уже проскорена, но запись/скор не отдались (сеть,
        // гонка) — maybeAutoScore() тут не поможет: он сам перепроверит seen=true и молча
        // выйдет, оставив панель пустой («тупик»). Дотягиваем реальный скоринг напрямую.
        void runScoringFlow({ auto: true });
      } else {
        void maybeAutoScore(vacancyId);
      }
    }
    await syncAppliedFromDomIfNeeded(vacancyId);
  });
}

/** Отправить обновление статуса воронки (fire-and-forget); панель — если ещё открыта на той же
 *  вакансии — перерисовываем сразу, иначе кнопка «Откликнуться» остаётся в старом состоянии до
 *  следующей навигации: setFunnelStatus сам обновляет только пилюлю статуса, не блок триажа. */
function reportStatus(vacancyId, status, extras = {}) {
  if (!vacancyId) return;
  setFunnelStatus(vacancyId, status, extras)
    .then(() => {
      console.log(`[Job Hunter] статус '${status}' → vacancy ${vacancyId}`);
      if (vacancyId === currentVacancyId && currentScoreRecord && !panelEl?.classList.contains('hidden')) {
        renderScore(currentScoreRecord, status);
      }
    })
    .catch(() => { /* backend недоступен */ });
}

let appliedDomObserver = null;
let appliedDomDebounce = null;

function isActiveVacancyRoute(route = resolveRoute()): boolean {
  return (
    (route.site === 'hh' && route.pageType === HH_PAGE_TYPE.VACANCY) ||
    (route.site === 'getmatch' && route.pageType === GETMATCH_PAGE_TYPE.VACANCY) ||
    (route.site === 'habr' && route.pageType === HABR_PAGE_TYPE.VACANCY)
  );
}

function watchAppliedBlockOnPage() {
  if (appliedDomObserver) {
    appliedDomObserver.disconnect();
    appliedDomObserver = null;
  }
  const vacancyId = vacancyExtractor.extractVacancyId(location.href);
  if (!vacancyId || !isActiveVacancyRoute()) return;

  appliedDomObserver = new MutationObserver(() => {
    clearTimeout(appliedDomDebounce);
    appliedDomDebounce = setTimeout(() => {
      syncAppliedFromDomIfNeeded(vacancyId);
    }, 600);
  });
  appliedDomObserver.observe(document.body, { childList: true, subtree: true });
}

/**
 * Перехват кликов на кнопку «Откликнуться» (все варианты на странице).
 * Используем capture-фазу чтобы поймать до HH-обработчиков.
 */
// Кнопки «Откликнуться»: на hh — актуальный pack из getSelectors() (Шаг 2).

document.addEventListener('click', (e) => {
  const vacancyId = vacancyExtractor.extractVacancyId(location.href);
  if (!vacancyId) return;

  const site = getSite();
  const selectors =
    site === 'getmatch' ? GM_RESPONSE_LINK_SELECTORS : getSelectors().responseLinks;

  for (const sel of selectors) {
    const target = (e.target as Element | null)?.closest?.(sel);
    if (!target) continue;
    if (site === 'getmatch') {
      const label = (target.textContent || '').replace(/\s+/g, ' ').trim();
      if (!/^откликнуться$/i.test(label)) continue;
      // getmatch: нативный клик только открывает модалку — статус фиксируем после подтверждения
      // отправки (см. gmAttachSubmitTracking / gmEnsureGlobalModalObserver). Здесь ничего не делаем.
      return;
    }
    const coverLetter = readCoverLetterFromPage();
    // Заполняем identity + текст JD из DOM, чтобы stub в БД не был пустой карточкой
    // (title/company=None) до того, как вакансия попадёт в /score. parseVacancyFromDom
    // безопасен на странице вакансии.
    let identity: { title?: string; company?: string; vacancy_text?: string } = {};
    try {
      const parsed = vacancyExtractor.parseVacancyFromDom(location.href);
      if (parsed.title) identity.title = parsed.title;
      if (parsed.company) identity.company = parsed.company;
      if (parsed.text) identity.vacancy_text = parsed.text;
    } catch { /* DOM мог не успеть — identity подтянется скорингом */ }
    reportStatus(vacancyId, FUNNEL_STATUS.APPLIED, {
      cover_letter: coverLetter || undefined,
      ...identity,
    });
    return;
  }
}, true /* capture */);

/** Сброс состояния vacancy-адаптера при уходе со страницы вакансии. Общий shadow-host дока не
 *  трогаем (им владеет dock.ts) — только освобождаем ссылки/останавливаем наблюдатель/отменяем
 *  текущую оценку, как раньше делал removeVacancyShadow() перед сносом собственного host. */
function teardownVacancyAdapter() {
  if (appliedDomObserver) {
    appliedDomObserver.disconnect();
    appliedDomObserver = null;
  }
  gmStopGlobalModalObserver();
  cancelScoreOperation();
  hideTip();
  panelEl?.removeEventListener('keydown', onPanelKeydown);
  document.removeEventListener('jh-account-toggle', onDockAccountToggle);
  shadowRoot = null;
  panelEl = null;
  barActionsEl = null;
  dockSlots = null;
  scoreBtn = null;
  cancelBtn = null;
  expandBtn = null;
  toastEl = null;
  currentVacancyId = null;
}

function mountVacancyAdapter(slots) {
  ensureVacancyExtractor();
  ensureUi(slots);
  void ensureExtConfig();
  void ensureScoreBreakdownMax();
  resetForNavigation();
  watchAppliedBlockOnPage();
  // Шаг 2: глобальный observer модалки отклика — автоподстановка письма, если её открыл сам
  // пользователь (вне кнопки расширения), и фиксация отправки.
  if (getSite() === 'getmatch') gmEnsureGlobalModalObserver();
}

/** EX-7: dock зовёт на каждый тик MutationObserver/popstate, пока vacancy-адаптер активен — ровно
 *  как раньше срабатывал собственный observer main.ts, но тот дёргал init() только при реальной
 *  смене URL (лишний DOM-мусор на странице вакансии не триггерил повторный resetForNavigation). */
function onVacancyNavigate(_slots, ctx) {
  if (!ctx.urlChanged) return;
  resetForNavigation();
  watchAppliedBlockOnPage();
}

const vacancyAdapter = {
  key: 'vacancy',
  matches: (route: SiteRoute) => isActiveVacancyRoute(route),
  mount: mountVacancyAdapter,
  onNavigate: onVacancyNavigate,
  teardown: teardownVacancyAdapter,
};

bootDock([
  vacancyAdapter,
  negotiationsAdapter,
  hrThreadAdapter,
  resumesAdapter,
  hhStatsAdapter,
  serpAdapter,
  getmatchApplicationsAdapter,
  getmatchCatalogAdapter,
  habrApplicationsAdapter,
  getmatchProfileStatsAdapter,
  getmatchProfilePageAdapter,
  getmatchIdleAdapter,
  idleAdapter,
]);

void pruneScoreCache();
// Рантайм-конфиг расширения (флаги/тюнинг/селекторы отклика) — из chrome.storage.local в память
// + watch на обновления; сеть тянет service worker. Нужен и на hh, и на getmatch (селекторы
// отклика обеих площадок), поэтому вне site-гейта ниже.
void initRuntimeConfig();

if (getSite() === 'hh') {
  void initSelectors();
  startNegotiationsHeartbeat();
}
if (getSite() === 'getmatch') {
  startGetmatchHeartbeat();
}

/**
 * Фаза 2.1/2.3/2.4: раннер автооткликов (background/auto-apply-runner.ts) открывает вкладку с
 * вакансией и шлёт `auto_apply_run` сюда, в уже смонтированный content-script этой вкладки.
 * Вакансия уже проскорена (иначе не попала бы в очередь auto) — тот же bootstrap-путь, что у
 * обычного визита (resetForNavigation → get_vacancy_record), заполняет `currentScoreRecord`
 * без дополнительного кода здесь; ждём его готовности, не переизобретаем скоринг.
 *
 * Дефолт 65с — с запасом над job_search budget_ms=60000 (core/domains/opportunities/llm.py):
 * ждать МЕНЬШЕ, чем бэк реально может скорить, — гарантированный ложный провал, не настоящая
 * ошибка чтения (правка 2026-08-20: старый дефолт 15/20с давал «Ошибка чтения» на вакансиях,
 * которые бэк доскоривал секундами позже, уже после того как расширение сдалось ждать и закрыло
 * вкладку).
 */
async function waitForVacancyReady(
  vacancyId: string,
  timeoutMs = getRuntimeConfig().tuning.vacancy_ready_timeout_ms,
): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (currentVacancyId === vacancyId && currentScoreRecord) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return currentVacancyId === vacancyId && Boolean(currentScoreRecord);
}

async function runAutoApplyForCurrentPage(
  vacancyId: string,
  dryRun: boolean,
  anketaAnswers?: AnketaAnswerInput[],
  approvedLetter?: string,
): Promise<{ outcome: string; letter: string; anketa?: { questions: AnketaQuestionDom[] } }> {
  const ready = await waitForVacancyReady(vacancyId);
  if (!ready) {
    return { outcome: 'not_ready', letter: '' };
  }

  // Фаза 3.4: повторный визит за подтверждённым письмом (режим «Тест») — используем текст,
  // который владелец видел и одобрил в вебе, БЕЗ новой LLM-генерации (мог отредактировать).
  if (approvedLetter != null) {
    coverLetterCache[vacancyId] = approvedLetter;
  }

  const site = getSite();
  if (site === 'getmatch') {
    const result = await onGetmatchApplyFlow(vacancyId, { dryRun, runnerMode: true });
    return result || { outcome: 'error', letter: '' };
  }
  if (site === 'hh') {
    return runHhApplyFlow({
      dryRun,
      generateLetter: () =>
        approvedLetter != null ? Promise.resolve(approvedLetter) : gmGenerateLetter(vacancyId),
      anketaAnswers,
    });
  }
  // Habr (2.6) ещё не реализован — раннер помечает как ошибку, не молчит.
  return { outcome: 'unsupported', letter: '' };
}

type DiscoveryCandidate = {
  vacancy_id: string;
  url: string;
  title?: string;
  company?: string;
};

/** Фаза discovery (background/discovery-runner.ts): карточки текущей страницы листинга
 *  (SERP hh.ru / каталог getmatch.ru) + ссылка на следующую, если есть. Раннер шлёт это
 *  сообщение вкладке сразу после того, как сам открыл/перезагрузил её на search_url из настроек
 *  «Расширения» — это ВСЕГДА первая (после навигации) страница листинга, не продолжение.
 *
 *  getmatch (Этап 4 редизайна «Расширения», живая разведка DOM 2026-08-19): пагинация каталога
 *  реальна (до 41 страницы), но НЕ адресуется URL — `nextPageUrl` для неё не настоящая ссылка,
 *  а признак «есть куда листать» (текущий `location.href`, раннер сравнивает со следующим вызовом
 *  побайтово, см. discovery-runner.ts::ensureWorkerTab); честная `null`, если стрелка «вправо»
 *  задизейблена или её вовсе нет (не притворяемся, что «Продолжить» даст что-то новое). */
function listDiscoveryCandidates(): { cards: DiscoveryCandidate[]; nextPageUrl: string | null } {
  const site = getSite();
  if (site === 'hh') {
    const cards = parseSerpListingFromDom().items.map((c) => ({
      vacancy_id: c.vacancy_id,
      url: c.url,
      title: c.title,
      company: c.company,
    }));
    return { cards, nextPageUrl: getSerpNextPageUrl() };
  }
  if (site === 'getmatch') {
    const cards = parseGetmatchCatalogCardsFromDom().map((c) => ({
      vacancy_id: c.vacancy_id,
      url: c.url,
      title: c.title,
    }));
    return { cards, nextPageUrl: hasGetmatchNextPage() ? location.href : null };
  }
  if (site === 'habr') {
    const { cards, nextPageUrl } = parseHabrListingFromDom();
    return {
      cards: cards.map((c) => ({
        vacancy_id: c.vacancy_id,
        url: c.url,
        title: c.title,
        company: c.company,
      })),
      nextPageUrl,
    };
  }
  return { cards: [], nextPageUrl: null };
}

/** Продолжение той же вкладки каталога getmatch на следующую страницу (Этап 4) — клик по стрелке
 *  «вправо» + ожидание перерисовки списка, БЕЗ повторной навигации (навигация на тот же URL
 *  сбросила бы React-состояние обратно на страницу 1). Раннер шлёт это сообщение вместо повторного
 *  `discovery_list_page`, когда рабочая вкладка каталога уже открыта и это не начало новой сессии
 *  (см. `freshStart` в discovery-runner.ts). hh сюда не попадает — у него каждая страница отдаёт
 *  свою настоящую ссылку, продолжать «на месте» незачем. */
async function listDiscoveryCandidatesAdvance(): Promise<{
  cards: DiscoveryCandidate[];
  nextPageUrl: string | null;
}> {
  if (getSite() !== 'getmatch') return listDiscoveryCandidates();
  const previousFirstId = parseGetmatchCatalogCardsFromDom()[0]?.vacancy_id ?? null;
  if (!clickGetmatchNextPage()) return { cards: [], nextPageUrl: null };
  await waitForCatalogPageChange(previousFirstId);
  const cards = parseGetmatchCatalogCardsFromDom().map((c) => ({
    vacancy_id: c.vacancy_id,
    url: c.url,
    title: c.title,
  }));
  return { cards, nextPageUrl: hasGetmatchNextPage() ? location.href : null };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action === 'discovery_list_page') {
    try {
      sendResponse({ ok: true, data: listDiscoveryCandidates() });
    } catch (err) {
      sendResponse({ ok: false, error: String((err as Error)?.message || err) });
    }
    return false;
  }
  if (message?.action === 'discovery_list_page_advance') {
    listDiscoveryCandidatesAdvance()
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String((err as Error)?.message || err) }));
    return true;
  }
  if (message?.action === 'discovery_wait_for_score') {
    const vacancyId: string | undefined = message.payload?.vacancy_id;
    if (!vacancyId) {
      sendResponse({ ok: false, error: 'vacancy_id обязателен' });
      return false;
    }
    // Навигация уже сама запустила обычный путь скоринга (resetForNavigation →
    // maybeAutoScore/runScoringFlow) — здесь только ждём готовности, никакой отдельной логики
    // скоринга не заводим (тот же приём, что у auto-apply-runner-а выше). Таймаут — дефолт
    // waitForVacancyReady (см. её комментарий: запас над job_search budget_ms=60000).
    waitForVacancyReady(vacancyId)
      .then((ready) => {
        sendResponse({
          ok: true,
          data: ready
            ? {
                outcome: 'scored',
                title: currentScoreRecord?.title,
                company: currentScoreRecord?.company,
              }
            : { outcome: 'parse_error' },
        });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  }
  return false;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action !== 'auto_apply_run') return false;
  const vacancyId: string | undefined = message.payload?.vacancy_id;
  const dryRun: boolean = message.payload?.dry_run !== false;
  // Фаза 3.3: второй визит раннера за подтверждённой анкетой — ответы владельца, заполнить и
  // досдать форму вместо повторной парковки на подтверждение.
  const anketaAnswers: AnketaAnswerInput[] | undefined = message.payload?.anketa_answers;
  // Фаза 3.4: второй визит за подтверждённым письмом (режим «Тест», без анкеты) — готовый
  // текст вместо новой генерации.
  const approvedLetter: string | undefined = message.payload?.approved_letter;
  if (!vacancyId) {
    sendResponse({ ok: false, error: 'vacancy_id обязателен' });
    return false;
  }
  runAutoApplyForCurrentPage(vacancyId, dryRun, anketaAnswers, approvedLetter)
    .then((result) => sendResponse({ ok: true, data: result }))
    .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
  return true;
});
