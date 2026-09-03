/**
 * Раннер автооткликов (Фаза 2.1, plans/auto_apply_roadmap_2026_08_17.md): по тику `chrome.alarms`
 * опрашивает включённые площадки, открывает фоновые вкладки по очереди `auto` (уже отсортированной
 * бэком), шлёт `auto_apply_run` в content-script вкладки, репортит результат, ждёт рандомизированную
 * паузу, переходит к следующему кандидату — до дневного лимита или пустой очереди.
 *
 * Фаза 8.1 (человеческий паттерн): не выгружает весь дневной лимит залпом в реальном режиме
 * (`MAX_REAL_APPLICATIONS_PER_TICK`); плюс жёсткий пол «не чаще 1 отклика в 2 минуты на
 * площадку» (`awaitRealApplySlot`, owner's spec 2026-08-28). Фаза 8.2 (блокеры площадки): исходы `captcha`/
 * `resume_hidden`/`platform_limit` останавливают тик для площадки немедленно
 * (`STOP_TICK_OUTCOMES`) — бэк решает, что делать дальше (`report_attempt`).
 *
 * Фаза 3.4 (режим «Тест» = `requireConfirmation`): первый визит кандидата площадки в этом
 * режиме ведёт себя как dry-run (не кликает), но репортится бэку как `needs_confirmation`, а
 * не `dry_run` — бэк паркует очередь подтверждения вместо простого лога. Реальный клик по
 * одобренным кандидатам — отдельный `runAnketaResumeCycle` (тот же alarm-тик, следующий проход).
 *
 * `runAutoApplyCycle` — чистая оркестрация поверх инжектируемых зависимостей (без прямого
 * chrome.tabs / fetch внутри) — так тестируется мок-chrome.tabs/chrome.runtime без реального браузера.
 * `createRealDeps` — единственное место, где эта функция встречается с настоящим chrome.tabs.
 */

import { getRuntimeConfig } from '../dom/extension-runtime-config'
import { keepAliveSleep } from './keep-alive'

export type AutoApplyPlatform = 'hh' | 'getmatch' | 'habr'

export interface AutoApplyCandidate {
  job_id: number
  vacancy_id: string
  url: string
}

// Фаза 3.1-3.3 (анкета работодателя, hh.ru) — распознавание/заполнение живёт в
// hh-apply-flow.ts, здесь только форма сообщения между content-script и раннером.
export interface AnketaOptionInput {
  id: string
  label: string
}

export interface AnketaQuestionInput {
  id: string
  text: string
  type: 'text' | 'single_choice' | 'multi_choice'
  options: AnketaOptionInput[]
}

export interface AnketaAnswerInput {
  question_id: string
  value: string
}

/** Одна вакансия из очереди подтверждения, одобренная владельцем (status=approved) — раннер
 *  заново открывает вкладку и досдаёт форму. `answers` — анкета (Фаза 3.3, пусто, если её не
 *  было); `letter` — сопроводительное из `jobs.cover_letter_text` (Фаза 3.4, режим «Тест») —
 *  используется как есть, БЕЗ повторной LLM-генерации (владелец мог отредактировать текст,
 *  который видел при подтверждении). */
export interface AnketaResumeCandidate {
  platform: AutoApplyPlatform
  jobId: number
  vacancyId: string
  url: string
  answers: AnketaAnswerInput[]
  letter: string
}

export interface AutoApplyPlatformState {
  platform: AutoApplyPlatform
  dryRun: boolean
  /** Фаза 3.4: режим «Тест» — реально отправляет (dry_run=False на бэке), но КАЖДЫЙ отклик
   *  ждёт подтверждения владельца перед фактическим кликом. На первом визите раннер ведёт
   *  себя как dry-run (генерирует письмо, не кликает) и репортит `needs_confirmation` вместо
   *  `dry_run`, чтобы бэк запарковал очередь подтверждения; независимо от `dryRun`. */
  requireConfirmation: boolean
  /** Очередь `auto` одной площадки, уже отсортированная бэком по `config.order`. */
  candidates: AutoApplyCandidate[]
  dailyCap: number
  /** Сколько реальных (не dry-run) откликов этой площадки уже ушло сегодня. */
  dailyCount: number
  /** Ручная отправка из UI: игнорировать dry_run/require_confirmation и отправлять в реальном
   *  режиме, не дожидаясь следующего планового тика. */
  manualSend: boolean
}

export interface AutoApplyRunResult {
  platform: AutoApplyPlatform
  vacancyId: string
  jobId: number
  outcome: string
  letter: string
  /** Фаза 3.1: распарсенные вопросы анкеты — заполнено только когда `outcome === 'anketa'` и
   *  это ПЕРВАЯ встреча (ответов ещё не было). Бэк генерирует по ним черновик ответов. */
  anketaQuestions?: AnketaQuestionInput[]
}

export interface AutoApplyRunnerDeps {
  /** Состояние каждой ВКЛЮЧЁННОЙ площадки за один сбор — раннер сам не решает, что включено. */
  loadPlatformStates: () => Promise<AutoApplyPlatformState[]>
  /** Фаза 3.3: анкеты, подтверждённые владельцем — раннер должен заново открыть вкладку и
   *  досдать форму этими ответами (второй, отдельный проход, `runAnketaResumeCycle`). */
  loadApprovedAnketas: () => Promise<AnketaResumeCandidate[]>
  openTab: (url: string) => Promise<number>
  waitForTabLoad: (tabId: number) => Promise<void>
  /** `anketaAnswers` передаётся только при повторном визите за подтверждённой анкетой
   *  (Фаза 3.3) — на первой встрече анкеты без ответов content-script парсит вопросы и
   *  паркует их в ответе (`anketa.questions`), не кликая дальше. `approvedLetter` (Фаза 3.4) —
   *  готовое сопроводительное с повторного визита за подтверждённым письмом; при заполнении
   *  content-script использует его как есть вместо новой LLM-генерации. */
  sendAutoApplyRun: (
    tabId: number,
    vacancyId: string,
    dryRun: boolean,
    anketaAnswers?: AnketaAnswerInput[],
    approvedLetter?: string,
  ) => Promise<{ outcome: string; letter: string; anketa?: { questions: AnketaQuestionInput[] } }>
  closeTab: (tabId: number) => Promise<void>
  /** `dryRun` здесь — настройка площадки (`state.dryRun`), не «удался ли клик». Бэк по
   *  `outcome` решает: applied → воронка, failure → ручной разбор, dry_run-площадка → только лог. */
  reportResult: (result: AutoApplyRunResult, dryRun: boolean) => Promise<void>
  sleep: (ms: number) => Promise<void>
  /** Рандомизированная пауза между кандидатами (2.1) — окно задаётся реализацией. */
  randomDelayMs: () => number
  /** Жёсткий пол паузы между РЕАЛЬНЫМИ откликами одной площадки (не чаще 1 в 2 мин) —
   *  `tuning.auto_apply_min_real_interval_ms`. Опционально: чистые юнит-тесты цикла его
   *  не задают (тогда действует зашитый `DEFAULT_MIN_REAL_INTERVAL_MS`). */
  minRealIntervalMs?: () => number
  /** Heartbeat: итог тика (все результаты обоих проходов) → одна строка в журнал бэка.
   *  Опционально — юнит-тесты чистого цикла его не задают. Зовётся из background.ts. */
  reportTickSummary?: (allResults: AutoApplyRunResult[]) => Promise<void>
  /** Снять флаг ручной отправки после успешной обработки очереди. */
  clearManualSend?: () => Promise<void>
}

/** Исходы DOM-флоу, требующие немедленно остановить площадку на этот тик (8.2) — капча/
 *  скрытое резюме уже отключили площадку на бэке (report_attempt → disable_platform), но и в
 *  рамках текущего тика не пытаемся продолжить по следующим кандидатам той же площадки;
 *  `platform_limit` — своя (не наша) дневная квота площадки, пытаться ещё раз бессмысленно. */
const STOP_TICK_OUTCOMES = new Set(['captcha', 'resume_hidden', 'platform_limit'])

/** Не выгружать весь daily_cap одним тиком в РЕАЛЬНОМ режиме — раскидывать отклики по дню
 *  (8.1), а не бить их залпом, как только открылось окно активности. Dry-run не оставляет
 *  следов кликов на площадке, поэтому лимит на тик к нему не применяется. Значение — из
 *  рантайм-конфига (`tuning.max_real_applications_per_tick`), чтобы замедлить/ускорить темп
 *  с сервера без переустановки zip. */
function maxRealApplicationsPerTick(): number {
  return getRuntimeConfig().tuning.max_real_applications_per_tick
}

/** Дефолт пола паузы между реальными откликами, если `deps.minRealIntervalMs` не задан
 *  (чистые юнит-тесты цикла). 2 минуты ⇒ не чаще 1 автоотклика в 2 минуты на площадку
 *  (owner's spec 2026-08-28). */
const DEFAULT_MIN_REAL_INTERVAL_MS = 120_000

/** Момент последней РЕАЛЬНОЙ отправки по площадке — переживает границы тиков и оба прохода
 *  (`runAutoApplyCycle` + `runAnketaResumeCycle`), пока жив service worker. После перезапуска
 *  SW первый отклик уйдёт сразу, но следующий тик — минимум через `auto_apply_tick_minutes`. */
const realApplyClockMs = new Map<AutoApplyPlatform, number>()

/** Сброс клока частоты — только для unit-тестов. */
export function _resetRealApplyClockForTests(): void {
  realApplyClockMs.clear()
}

/** Дождаться, пока с последней реальной отправки по этой площадке пройдёт минимум
 *  `minRealIntervalMs` (жёсткий потолок «не чаще 1 в 2 мин»). Вызывать ПЕРЕД `sendAutoApplyRun` в боевом
 *  режиме и в `runAnketaResumeCycle`. */
async function awaitRealApplySlot(
  platform: AutoApplyPlatform,
  deps: AutoApplyRunnerDeps,
): Promise<void> {
  const gap = deps.minRealIntervalMs?.() ?? DEFAULT_MIN_REAL_INTERVAL_MS
  const last = realApplyClockMs.get(platform)
  if (last === undefined) return
  const wait = gap - (Date.now() - last)
  if (wait > 0) await deps.sleep(wait)
}

/**
 * Один тик раннера по всем включённым площадкам. Кандидат считается «реально отправленным»
 * только при `outcome === 'applied'` — это единственное, что двигает дневной счётчик; любой
 * другой исход в реальном режиме репортится как dry-run (лог без стадии), чтобы не потерять
 * попытку молча, но и не соврать воронке об успехе, которого не было.
 *
 * Бюджет тика ограничен `dailyCap` в ОБОИХ режимах: в реальном — это фактический лимит на день
 * (счётчик персистится в application_stages), в dry-run — персиста нет, поэтому лимит защищает
 * от повторной LLM-генерации писем по всей очереди на каждый тик (см. README auto_apply).
 *
 * Фаза 3.4 (`requireConfirmation`): первый визит любого кандидата ведёт себя как dry-run
 * (`effectiveDryRun` ниже) — генерирует письмо, не кликает, независимо от `state.dryRun` (в
 * режиме «Тест» он уже `False` на бэке). Исход `dry_run` в этом случае репортится бэку как
 * `needs_confirmation`, а не `dry_run`, — только тогда бэк паркует очередь подтверждения
 * (`_park_pending_confirmation`); настоящий `dry_run` площадки (`state.dryRun`, силуэт-режим
 * без очереди) остаётся просто логом, как раньше. Реальный клик по подтверждённым кандидатам
 * делает отдельный `runAnketaResumeCycle`, не этот цикл.
 */
export async function runAutoApplyCycle(deps: AutoApplyRunnerDeps): Promise<AutoApplyRunResult[]> {
  const results: AutoApplyRunResult[] = []
  const states = await deps.loadPlatformStates()
  let anyManualSend = false

  for (const state of states) {
    const manualSend = state.manualSend === true
    if (manualSend) anyManualSend = true
    const effectiveDryRun = (state.dryRun || state.requireConfirmation) && !manualSend
    let budget = effectiveDryRun ? state.dailyCap : Math.max(state.dailyCap - state.dailyCount, 0)
    if (!effectiveDryRun && !manualSend) budget = Math.min(budget, maxRealApplicationsPerTick())

    for (const candidate of state.candidates) {
      if (budget <= 0) break

      // Жёсткий потолок «не чаще 1 реального отклика в 2 мин на площадку» — ДО openTab: пауза
      // тут до 2 мин, а MV3 усыпляет service worker на длинном setTimeout. Смерть SW во сне
      // ПОСЛЕ openTab оставляла бы висячую вкладку job-сайта (finally не доезжает) и теряла
      // кандидата. dry-run / первый визит режима «Тест» отклик не шлют — их не тормозим.
      if (!effectiveDryRun) await awaitRealApplySlot(state.platform, deps)

      let tabId: number
      try {
        tabId = await deps.openTab(candidate.url)
      } catch (err) {
        // chrome.tabs.create кинул (лимит вкладок, гонка с закрытием окна) — пропускаем
        // кандидата, не роняем весь тик (и не тратим на него бюджет — вернёмся к нему).
        void err
        continue
      }
      let outcome = 'error'
      let letter = ''
      let anketaQuestions: AnketaQuestionInput[] | undefined
      try {
        await deps.waitForTabLoad(tabId)
        const response = await deps.sendAutoApplyRun(tabId, candidate.vacancy_id, effectiveDryRun)
        if (!effectiveDryRun) realApplyClockMs.set(state.platform, Date.now())
        outcome = response.outcome
        letter = response.letter
        anketaQuestions = response.anketa?.questions
      } catch (err) {
        outcome = 'error'
        letter = ''
        void err // причина уже недоступна вкладке после закрытия — сам факт ошибки важнее текста
      } finally {
        await deps.closeTab(tabId)
      }

      // Режим «Тест» (не платформенный dry_run): "кликнул бы" на самом деле значит "жду
      // подтверждения" — бэк должен запарковать очередь, а не просто залогировать.
      if (state.requireConfirmation && !state.dryRun && outcome === 'dry_run') {
        outcome = 'needs_confirmation'
      }

      const result: AutoApplyRunResult = {
        platform: state.platform,
        vacancyId: candidate.vacancy_id,
        jobId: candidate.job_id,
        outcome,
        letter,
        anketaQuestions,
      }
      results.push(result)

      // dry_run в репорте = настройка площадки, кроме ручного триггера (тогда false).
      // Бэк смотрит на outcome: applied → воронка, failure → ручной разбор с причиной.
      await deps.reportResult(result, manualSend ? false : state.dryRun)
      budget -= 1

      if (STOP_TICK_OUTCOMES.has(outcome)) break

      if (budget > 0) {
        await deps.sleep(deps.randomDelayMs())
      }
    }
  }

  if (anyManualSend) {
    try {
      await deps.clearManualSend?.()
    } catch {
      // clearing is best-effort
    }
  }

  return results
}

/**
 * «Доведение до реальной отправки» — отдельный проход (тот же alarm-тик, после
 * `runAutoApplyCycle`) по вакансиям, чью очередь подтверждения владелец одобрил в вебе
 * (status=approved) — анкета (Фаза 3.3) ИЛИ простое подтверждение письма без анкеты
 * (Фаза 3.4, `answers=[]`). Открывает вкладку заново и повторяет клик по «Откликнуться» —
 * отклик ЕЩЁ НЕ был отправлен на первом визите (вкладка была просто закрыта после парковки на
 * подтверждение), поэтому повтор с начала идентичен первому разу, просто на этот раз с готовыми
 * ответами анкеты (если были) и/или готовым письмом вместо новой парковки/генерации
 * (`hh-apply-flow.ts::runHhApplyFlow` с `deps.anketaAnswers`, `main.ts` с `approvedLetter`).
 *
 * Всегда `dryRun=false` — подтверждение владельца УЖЕ было решением отправить по-настоящему,
 * платформенный dry_run/requireConfirmation сюда не относятся (в отличие от обычного цикла).
 */
export async function runAnketaResumeCycle(deps: AutoApplyRunnerDeps): Promise<AutoApplyRunResult[]> {
  const results: AutoApplyRunResult[] = []
  const candidates = await deps.loadApprovedAnketas()

  for (let i = 0; i < candidates.length; i++) {
    const candidate = candidates[i]
    // Досыл подтверждённых — всегда боевой: тот же потолок «1 в 2 мин», и так же ДО openTab
    // (длинный сон + смерть SW = висячая вкладка), что и в основном цикле.
    await awaitRealApplySlot(candidate.platform, deps)

    let tabId: number
    try {
      tabId = await deps.openTab(candidate.url)
    } catch (err) {
      void err // не удалось открыть вкладку — пропускаем, тик не роняем
      continue
    }
    let outcome = 'error'
    let letter = ''
    try {
      await deps.waitForTabLoad(tabId)
      const response = await deps.sendAutoApplyRun(
        tabId,
        candidate.vacancyId,
        false,
        candidate.answers,
        candidate.letter || undefined,
      )
      realApplyClockMs.set(candidate.platform, Date.now())
      outcome = response.outcome
      letter = response.letter
    } catch (err) {
      outcome = 'error'
      letter = ''
      void err
    } finally {
      await deps.closeTab(tabId)
    }

    const result: AutoApplyRunResult = {
      platform: candidate.platform,
      vacancyId: candidate.vacancyId,
      jobId: candidate.jobId,
      outcome,
      letter,
    }
    results.push(result)
    // Резюме-визит всегда боевой (подтверждение владельца уже было) — dry_run=false.
    await deps.reportResult(result, false)

    if (STOP_TICK_OUTCOMES.has(outcome)) break

    if (i < candidates.length - 1) {
      await deps.sleep(deps.randomDelayMs())
    }
  }

  return results
}

/** Окно рандомизированной паузы между кандидатами — человекоподобный темп, не залп подряд.
 *  Границы окна — из рантайм-конфига (`tuning.auto_apply_delay_ms`), правятся с сервера. */
export function randomAutoApplyDelayMs(): number {
  const [min, max] = getRuntimeConfig().tuning.auto_apply_delay_ms
  return min + Math.random() * (max - min)
}

const PLATFORMS: AutoApplyPlatform[] = ['hh', 'getmatch', 'habr']

export interface HttpDeps {
  apiFetch: (action: string, url: string, options?: RequestInit) => Promise<Response>
  apiUrl: (path: string) => string
  apiHeaders: (json: boolean) => Record<string, string>
}

/** Единственное место в модуле, трогающее настоящий chrome.tabs/fetch — вся логика цикла выше
 *  тестируется без него. */
export function createRealDeps(http: HttpDeps): AutoApplyRunnerDeps {
  // Диагностика последнего сбора состояний — для heartbeat-репорта (почему раннер ничего не
  // сделал: флаг выключен / бэк-ручка отвалилась / просто пустая очередь).
  let lastDiag: { platformsEnabled: string[]; platformsReady: string[]; candidates: number; bailReason: string | null } =
    { platformsEnabled: [], platformsReady: [], candidates: 0, bailReason: null }

  return {
    async loadPlatformStates() {
      const diag = { platformsEnabled: [] as string[], platformsReady: [] as string[], candidates: 0, bailReason: null as string | null }
      lastDiag = diag
      // Серверный аварийный стоп (рантайм-конфиг расширения) — поверх per-account настроек.
      // `false` побеждает: владелец гасит площадку для всех сразу из админки, без пересборки.
      const flags = getRuntimeConfig().flags
      if (!flags.auto_apply_enabled) {
        diag.bailReason = 'flag_auto_apply_disabled'
        return []
      }

      const settingsResp = await http.apiFetch('auto_apply_settings', http.apiUrl('/api/settings'), {
        headers: http.apiHeaders(false),
      })
      if (!settingsResp.ok) {
        diag.bailReason = `settings_http_${settingsResp.status}`
        return []
      }
      const settings = await settingsResp.json()
      const config = settings?.auto_apply_config || {}

      let manualSendPending = false
      const states: AutoApplyPlatformState[] = []
      for (const platform of PLATFORMS) {
        const platformConfig = config[platform] || {}
        if (!platformConfig.enabled) continue
        if (flags[`auto_apply_${platform}_enabled` as keyof typeof flags] === false) continue
        diag.platformsEnabled.push(platform)

        const [previewResp, countResp] = await Promise.all([
          http.apiFetch(
            'auto_apply_preview',
            http.apiUrl(`/api/pipeline/auto-apply/preview?platform=${platform}`),
            { headers: http.apiHeaders(false) },
          ),
          http.apiFetch(
            'auto_apply_daily_count',
            http.apiUrl(`/api/pipeline/auto-apply/daily-count?platform=${platform}`),
            { headers: http.apiHeaders(false) },
          ),
        ])
        if (!previewResp.ok || !countResp.ok) {
          diag.bailReason = `preview_http_${previewResp.ok ? countResp.status : previewResp.status}:${platform}`
          continue
        }
        const preview = await previewResp.json()
        const count = await countResp.json()

        if (!manualSendPending && preview.manual_send_pending) {
          manualSendPending = true
        }

        const serverApplyMs = count.last_real_apply_at ? Date.parse(count.last_real_apply_at) : NaN
        if (Number.isFinite(serverApplyMs) && serverApplyMs > (realApplyClockMs.get(platform) ?? 0)) {
          realApplyClockMs.set(platform, serverApplyMs)
        }

        const candidates = (preview.auto || [])
          .filter((item: { url?: string | null }) => Boolean(item.url))
          .map((item: { job_id: number; vacancy_id: string; url: string }) => ({
            job_id: item.job_id,
            vacancy_id: item.vacancy_id,
            url: item.url,
          }))
        diag.platformsReady.push(platform)
        diag.candidates += candidates.length
        states.push({
          platform,
          dryRun: platformConfig.dry_run !== false,
          requireConfirmation: platformConfig.require_confirmation === true,
          candidates,
          dailyCap: count.cap ?? 0,
          dailyCount: count.count ?? 0,
          // Просьба о ручной отправке относится к площадке, а не к наличию кандидатов: с
          // `&& candidates.length > 0` пустая очередь оставляла флаг взведённым навсегда
          // (снимает его только `runAutoApplyCycle`, увидев хоть один manualSend-state), и
          // «Отправить» при пустой очереди залипало в проде. Пустой список кандидатов и так
          // ничего не отправит — внутренний цикл просто не выполнится ни разу.
          manualSend: manualSendPending,
        })
      }
      return states
    },

    async reportTickSummary(allResults) {
      const has = (o: string) => allResults.filter((r) => r.outcome === o).length
      const blocked = [
        ...new Set(allResults.filter((r) => STOP_TICK_OUTCOMES.has(r.outcome)).map((r) => r.outcome)),
      ]
      const ok = new Set(['applied', 'already_applied', 'dry_run', 'needs_confirmation', 'anketa'])
      const failed = allResults.filter((r) => !ok.has(r.outcome) && !STOP_TICK_OUTCOMES.has(r.outcome))
        .length
      try {
        await http.apiFetch(
          'auto_apply_tick_report',
          http.apiUrl('/api/pipeline/auto-apply/tick-report'),
          {
            method: 'POST',
            headers: http.apiHeaders(true),
            body: JSON.stringify({
              platforms_enabled: lastDiag.platformsEnabled,
              platforms_ready: lastDiag.platformsReady,
              candidates: lastDiag.candidates,
              applied: has('applied') + has('already_applied'),
              needs_confirmation: has('needs_confirmation'),
              anketa: has('anketa'),
              failed,
              blocked,
              bail_reason: lastDiag.bailReason,
            }),
          },
        )
      } catch {
        /* heartbeat не критичен — не роняем тик */
      }
    },

    async loadApprovedAnketas() {
      const flags = getRuntimeConfig().flags
      if (!flags.auto_apply_enabled || !flags.anketa_resume_enabled) return []

      const settingsResp = await http.apiFetch('auto_apply_settings', http.apiUrl('/api/settings'), {
        headers: http.apiHeaders(false),
      })
      if (!settingsResp.ok) return []
      const settings = await settingsResp.json()
      const config = settings?.auto_apply_config || {}

      const candidates: AnketaResumeCandidate[] = []
      for (const platform of PLATFORMS) {
        const platformConfig = config[platform] || {}
        if (!platformConfig.enabled) continue
        if (flags[`auto_apply_${platform}_enabled` as keyof typeof flags] === false) continue

        const resp = await http.apiFetch(
          'auto_apply_anketa_pending',
          http.apiUrl(`/api/pipeline/auto-apply/anketa/pending?platform=${platform}&status=approved`),
          { headers: http.apiHeaders(false) },
        )
        if (!resp.ok) continue
        const data = await resp.json()
        type AnketaPendingItem = {
          job_id: number
          vacancy_id: string
          url?: string | null
          cover_letter_text?: string | null
          anketa?: { answers?: { question_id: string; value: string }[] }
        }
        for (const item of (data.items || []) as AnketaPendingItem[]) {
          if (!item.url) continue
          candidates.push({
            platform,
            jobId: item.job_id,
            vacancyId: item.vacancy_id,
            url: item.url,
            answers: (item.anketa?.answers || []).map((a) => ({
              question_id: a.question_id,
              value: a.value,
            })),
            letter: item.cover_letter_text || '',
          })
        }
      }
      return candidates
    },

    async clearManualSend() {
      await http.apiFetch(
        'auto_apply_clear_manual_send',
        http.apiUrl('/api/pipeline/auto-apply/clear-manual-send'),
        { method: 'POST', headers: http.apiHeaders(true) },
      )
    },

    openTab(url) {
      return new Promise((resolve, reject) => {
        chrome.tabs.create({ url, active: false }, (tab) => {
          if (chrome.runtime.lastError || !tab?.id) {
            reject(new Error(chrome.runtime.lastError?.message || 'Не удалось открыть вкладку'))
            return
          }
          resolve(tab.id)
        })
      })
    },

    waitForTabLoad(tabId) {
      const { tab_load_timeout_ms, post_load_settle_ms } = getRuntimeConfig().tuning
      return new Promise((resolve) => {
        let done = false
        const finish = (settle: boolean) => {
          if (done) return
          done = true
          clearTimeout(timeout)
          chrome.tabs.onUpdated.removeListener(listener)
          if (settle) setTimeout(resolve, post_load_settle_ms)
          else resolve()
        }
        const timeout = setTimeout(() => finish(false), tab_load_timeout_ms)
        function listener(updatedTabId: number, info: chrome.tabs.TabChangeInfo) {
          if (updatedTabId === tabId && info.status === 'complete') finish(true)
        }
        chrome.tabs.onUpdated.addListener(listener)
        // Вкладка могла догрузиться до подписки на onUpdated (кэш / быстрый ответ) — событие
        // 'complete' тогда уже не придёт, без этой проверки ждали бы весь таймаут зря.
        chrome.tabs.get(tabId, (tab) => {
          if (!chrome.runtime.lastError && tab?.status === 'complete') finish(true)
        })
      })
    },

    // content-script висит на document_idle — на свежеоткрытой вкладке слушатель auto_apply_run
    // может ещё не подняться к первому sendMessage, chrome отдаёт lastError «Could not establish
    // connection / Receiving end does not exist». Это гонка загрузки, не отказ флоу — ретраим
    // такие ошибки короткой серией (тот же приём, что в discovery-runner::sendTabMessage);
    // настоящий ответ content-script (`ok:false`) и прочие ошибки уходят наверх сразу.
    sendAutoApplyRun(tabId, vacancyId, dryRun, anketaAnswers, approvedLetter) {
      const RETRY_ATTEMPTS = 6
      const RETRY_DELAY_MS = 500
      const once = () =>
        new Promise<{ outcome: string; letter: string; anketa?: { questions: AnketaQuestionInput[] } }>(
          (resolve, reject) => {
            chrome.tabs.sendMessage(
              tabId,
              {
                action: 'auto_apply_run',
                payload: {
                  vacancy_id: vacancyId,
                  dry_run: dryRun,
                  anketa_answers: anketaAnswers,
                  approved_letter: approvedLetter,
                },
              },
              (response) => {
                if (chrome.runtime.lastError) {
                  reject(new Error(chrome.runtime.lastError.message))
                  return
                }
                if (!response?.ok) {
                  reject(new Error(response?.error || 'auto_apply_run: пустой ответ content-script'))
                  return
                }
                resolve(response.data)
              },
            )
          },
        )
      const isReceiverNotReady = (msg: string) =>
        msg.includes('Receiving end does not exist') ||
        msg.includes('Could not establish connection') ||
        msg.includes('message port closed')
      return (async () => {
        let lastErr: Error = new Error('sendAutoApplyRun: не запускался')
        for (let attempt = 0; attempt < RETRY_ATTEMPTS; attempt++) {
          try {
            return await once()
          } catch (err) {
            lastErr = err as Error
            if (!isReceiverNotReady(lastErr.message)) throw lastErr
            await new Promise((r) => setTimeout(r, RETRY_DELAY_MS))
          }
        }
        throw lastErr
      })()
    },

    closeTab(tabId) {
      return new Promise((resolve) => {
        chrome.tabs.remove(tabId, () => resolve())
      })
    },

    async reportResult(result, dryRun) {
      await http.apiFetch('auto_apply_report', http.apiUrl('/api/pipeline/auto-apply/report'), {
        method: 'POST',
        headers: http.apiHeaders(true),
        body: JSON.stringify({
          platform: result.platform,
          job_id: result.jobId,
          vacancy_id: result.vacancyId,
          dry_run: dryRun,
          // Фаза 8.2: captcha/resume_hidden/platform_limit — бэк сам решает, что с этим делать
          // (остановить площадку / тихо подождать до завтра), раннер только доносит исход.
          outcome: result.outcome,
          // Фаза 3.3: заполняется только при outcome==='anketa' на первой встрече — бэк
          // сгенерирует черновик ответов и запаркует анкету на подтверждение владельца.
          anketa_questions: result.anketaQuestions,
        }),
      })
    },

    // Паузы раннера — минуты (`auto_apply_delay_ms` 2–5 мин, `awaitRealApplySlot` до 2 мин).
    // Голый setTimeout столько в MV3 не живёт: воркер гасится, остаток тика теряется молча
    // (см. keep-alive.ts — из-за этого в проде не было ни одного тика с кандидатами).
    sleep(ms) {
      return keepAliveSleep(ms)
    },

    randomDelayMs: randomAutoApplyDelayMs,

    minRealIntervalMs: () => getRuntimeConfig().tuning.auto_apply_min_real_interval_ms,
  }
}
