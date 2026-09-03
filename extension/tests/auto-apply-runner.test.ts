/**
 * Раннер автооткликов (2.1, 8.1, 8.2) — оркестрация поверх мок-зависимостей, без реального
 * chrome.tabs. Проверка по плану: дневной лимит, рандомизированные паузы, не более 1 реального
 * отклика за тик и немедленная остановка тика на блокерах площадки (капча/скрытое резюме/
 * собственный лимит площадки).
 * Запуск: cd extension && npx tsx tests/auto-apply-runner.test.ts
 */
import assert from 'node:assert/strict'

import {
  _resetRealApplyClockForTests,
  createRealDeps,
  runAnketaResumeCycle,
  runAutoApplyCycle,
  type AnketaResumeCandidate,
  type AutoApplyPlatformState,
  type AutoApplyRunResult,
  type AutoApplyRunnerDeps,
} from '../src/background/auto-apply-runner.ts'

function candidates(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    job_id: i + 1,
    vacancy_id: String(i + 1),
    url: `https://hh.ru/vacancy/${i + 1}`,
  }))
}

function candidateState(overrides: Partial<AutoApplyPlatformState> = {}): AutoApplyPlatformState {
  return {
    platform: 'hh',
    dryRun: false,
    requireConfirmation: false,
    candidates: [],
    dailyCap: 5,
    dailyCount: 0,
    manualSend: false,
    ...overrides,
  }
}

function makeDeps(
  overrides: Partial<AutoApplyRunnerDeps> & {
    states: AutoApplyPlatformState[]
    anketas?: AnketaResumeCandidate[]
  },
) {
  // Клок частоты живёт на уровне модуля — чистим перед каждым сбором зависимостей, иначе
  // метка реального отклика из прошлого теста заставит `awaitRealApplySlot` спать.
  _resetRealApplyClockForTests()
  const opened: string[] = []
  const closed: number[] = []
  const reported: { result: AutoApplyRunResult; dryRun: boolean }[] = []
  const delays: number[] = []
  const sendCalls: {
    tabId: number
    vacancyId: string
    dryRun: boolean
    answers?: unknown
    letter?: string
  }[] = []
  let nextTabId = 1

  const defaultSend: AutoApplyRunnerDeps['sendAutoApplyRun'] = async (
    tabId,
    vacancyId,
    dryRun,
    anketaAnswers,
    approvedLetter,
  ) => {
    sendCalls.push({ tabId, vacancyId, dryRun, answers: anketaAnswers, letter: approvedLetter })
    return { outcome: 'applied', letter: 'письмо' }
  }

  const clearedManualSend: boolean[] = []
  const deps: AutoApplyRunnerDeps = {
    loadPlatformStates: async () => overrides.states,
    loadApprovedAnketas: async () => overrides.anketas || [],
    openTab: async (url) => {
      opened.push(url)
      return nextTabId++
    },
    waitForTabLoad: async () => {},
    sendAutoApplyRun: overrides.sendAutoApplyRun || defaultSend,
    closeTab: async (tabId) => {
      closed.push(tabId)
    },
    reportResult: async (result, dryRun) => {
      reported.push({ result, dryRun })
    },
    sleep: async (ms) => {
      delays.push(ms)
    },
    randomDelayMs: overrides.randomDelayMs || (() => 42),
    minRealIntervalMs: overrides.minRealIntervalMs || (() => 0),
    clearManualSend: async () => {
      clearedManualSend.push(true)
    },
  }
  return { deps, opened, closed, reported, delays, sendCalls, clearedManualSend }
}

async function testRealModeCapsAtOnePerTick() {
  // 8.1: реальный режим не выгружает весь daily_cap залпом — не больше одного отклика за тик,
  // даже если бюджет (cap - count) позволяет больше.
  const state = candidateState({ candidates: candidates(3), dailyCap: 5, dailyCount: 0 })
  const { deps, opened, reported } = makeDeps({ states: [state] })

  const results = await runAutoApplyCycle(deps)

  assert.equal(opened.length, 1, 'реальный режим: не больше 1 вкладки за тик, даже с запасом cap')
  assert.equal(results.length, 1)
  assert.equal(reported.length, 1)
  assert.equal(reported[0].dryRun, false, 'реальный режим + outcome=applied -> dry_run=false в репорте')
}

async function testDailyCapStillEnforcedAcrossTicks() {
  // Дневной лимит — про суммарный дневной счётчик (dailyCount из /daily-count), не про тик:
  // когда cap уже исчерпан прошлыми тиками, следующий тик ничего не делает.
  const state = candidateState({ candidates: candidates(3), dailyCap: 2, dailyCount: 2 })
  const { deps, opened } = makeDeps({ states: [state] })

  const results = await runAutoApplyCycle(deps)

  assert.equal(opened.length, 0, 'dailyCount уже == dailyCap -> бюджет 0, тик ничего не открывает')
  assert.equal(results.length, 0)
}

async function testRandomizedPauseWithinWindowForDryRun() {
  // Пауза между кандидатами (2.1) проверяется в dry-run: реальный режим теперь ограничен 1
  // кандидатом за тик (8.1) и не даёт увидеть паузу между несколькими подряд в одном вызове.
  const state = candidateState({
    platform: 'getmatch',
    dryRun: true,
    candidates: candidates(3),
    dailyCap: 3,
  })
  let call = 0
  const { deps, delays } = makeDeps({
    states: [state],
    randomDelayMs: () => {
      call += 1
      return 20_000 + call * 1000 // разные значения на каждый вызов - не константа
    },
  })

  await runAutoApplyCycle(deps)

  // Пауза - между кандидатами, не после последнего: 3 кандидата -> 2 паузы.
  assert.equal(delays.length, 2)
  for (const d of delays) {
    assert.ok(d >= 20_000 && d <= 90_000, `пауза ${d} вне ожидаемого окна`)
  }
  assert.notEqual(delays[0], delays[1], 'паузы рандомизированы, не константа')
}

async function testDryRunNeverMovesStageAndBudgetsByCap() {
  const state = candidateState({ dryRun: true, candidates: candidates(5), dailyCap: 2 })
  const { deps, opened, reported } = makeDeps({ states: [state] })

  await runAutoApplyCycle(deps)

  assert.equal(opened.length, 2, 'dry-run тоже бюджетируется по dailyCap на тик (не всей очередью)')
  assert.ok(reported.every((r) => r.dryRun === true), 'dry-run площадка -> report всегда dry_run=true')
}

async function testFailedRealAttemptReportsPlatformDryRunFalse() {
  // Сбой в боевом режиме репортится с dry_run=false + outcome=timeout — бэк перенесёт в
  // «Ручной разбор». Раньше dry_run=true маскировал сбой под «кликнул бы» и вакансия крутилась.
  const state = candidateState({ candidates: candidates(1), dailyCap: 5 })
  const { deps, reported } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => ({ outcome: 'timeout', letter: '' }),
  })

  const results = await runAutoApplyCycle(deps)

  assert.equal(results[0].outcome, 'timeout')
  assert.equal(reported[0].dryRun, false, 'боевой режим: dry_run в репорте = настройка площадки')
}

async function testDisabledPlatformNeverAppearsInLoadedStates() {
  // loadPlatformStates уже фильтрует по enabled на своей стороне (createRealDeps) - раннер
  // просто не получает выключенные площадки. Пустой список states -> ничего не делает.
  const { deps, opened, reported } = makeDeps({ states: [] })
  const results = await runAutoApplyCycle(deps)
  assert.equal(results.length, 0)
  assert.equal(opened.length, 0)
  assert.equal(reported.length, 0)
}

async function testOpenTabFailureSkipsCandidateWithoutAbortingTick() {
  // chrome.tabs.create кинул на первом кандидате (лимит вкладок / гонка закрытия окна) — раннер
  // не роняет весь тик, переходит к следующему кандидату, бюджет на упавшую вкладку не тратит.
  const state = candidateState({ candidates: candidates(2), dailyCap: 5, dailyCount: 0 })
  const { deps, opened, reported } = makeDeps({ states: [state] })
  let firstOpen = true
  deps.openTab = async (url: string) => {
    if (firstOpen) {
      firstOpen = false
      throw new Error('Tab limit reached')
    }
    opened.push(url)
    return 99
  }

  const results = await runAutoApplyCycle(deps)

  assert.equal(opened.length, 1, 'первый openTab упал — второй кандидат всё равно обработан')
  assert.equal(results.length, 1)
  assert.equal(reported[0].result.jobId, 2, 'отчёт ушёл по второму кандидату, не по упавшему первому')
}

// --- 8.2: блокеры площадки останавливают тик немедленно ---

async function testCaptchaOutcomeStopsTickImmediately() {
  const state = candidateState({ dryRun: true, candidates: candidates(3), dailyCap: 5 })
  let calls = 0
  const { deps, reported } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => {
      calls += 1
      return { outcome: 'captcha', letter: '' }
    },
  })

  const results = await runAutoApplyCycle(deps)

  assert.equal(calls, 1, 'капча на первом кандидате -> остальные 2 в этот тик не трогаем')
  assert.equal(results.length, 1)
  assert.equal(reported.length, 1)
  assert.equal(reported[0].result.outcome, 'captcha', 'исход долетает до report для бэка (disable_platform)')
}

async function testPlatformLimitOutcomeStopsTickImmediately() {
  const state = candidateState({ dryRun: true, candidates: candidates(3), dailyCap: 5 })
  let calls = 0
  const { deps } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => {
      calls += 1
      return { outcome: 'platform_limit', letter: '' }
    },
  })

  const results = await runAutoApplyCycle(deps)

  assert.equal(calls, 1, 'собственный лимит площадки на первом кандидате -> тик останавливается')
  assert.equal(results.length, 1)
  assert.equal(results[0].outcome, 'platform_limit')
}

// --- Фаза 3.1: outcome='anketa' на первой встрече несёт вопросы в report ---

async function testAnketaOutcomeCarriesQuestionsToReport() {
  const state = candidateState({ candidates: candidates(1), dailyCap: 5 })
  const questions = [{ id: 'q1', text: 'Опыт с Python?', type: 'single_choice' as const, options: [] }]
  const { deps, reported } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => ({ outcome: 'anketa', letter: '', anketa: { questions } }),
  })

  await runAutoApplyCycle(deps)

  assert.equal(reported.length, 1)
  assert.deepEqual(reported[0].result.anketaQuestions, questions)
  assert.equal(reported[0].dryRun, false, 'анкета — dry_run в репорте = настройка площадки (false)')
}

// --- Фаза 3.4: режим «Тест» (requireConfirmation) — первый визит ведёт себя как dry-run,
// но репортится как needs_confirmation, а не dry_run ---

async function testRequireConfirmationSendsEffectiveDryRunAndRemapsOutcome() {
  const state = candidateState({
    dryRun: false,
    requireConfirmation: true,
    candidates: candidates(1),
    dailyCap: 5,
    dailyCount: 0,
  })
  const seenDryRun: boolean[] = []
  const { deps, reported } = makeDeps({
    states: [state],
    sendAutoApplyRun: async (_tabId, _vacancyId, dryRun) => {
      seenDryRun.push(dryRun)
      return { outcome: 'dry_run', letter: 'черновик письма' }
    },
  })

  const results = await runAutoApplyCycle(deps)

  assert.equal(seenDryRun.length, 1)
  assert.equal(seenDryRun[0], true, 'requireConfirmation без platform dry_run — визит идёт как dry-run')
  assert.equal(results[0].outcome, 'needs_confirmation', 'dry_run-исход remapится в needs_confirmation бэку')
  assert.equal(reported.length, 1)
  assert.equal(reported[0].result.outcome, 'needs_confirmation')
  assert.equal(reported[0].dryRun, false, 'requireConfirmation: dry_run площадки false — бэк смотрит на outcome')
}

async function testRequireConfirmationBudgetsLikeDryRunNotCappedAtOne() {
  // 8.1 (MAX_REAL_APPLICATIONS_PER_TICK=1) не должен применяться, пока идут только
  // dry-run-визиты за подтверждением — иначе очередь на подтверждение наполнялась бы по 1 в тик.
  const state = candidateState({
    dryRun: false,
    requireConfirmation: true,
    candidates: candidates(3),
    dailyCap: 5,
    dailyCount: 0,
  })
  const { deps, opened } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => ({ outcome: 'dry_run', letter: '' }),
  })

  await runAutoApplyCycle(deps)

  assert.equal(opened.length, 3, 'requireConfirmation бюджетируется как dry-run — весь dailyCap за тик')
}

async function testRequireConfirmationAnketaOutcomeStaysAnketaNotRemapped() {
  // Анкета уже своя собственная очередь подтверждения (3.3) независимо от requireConfirmation —
  // remap только для исхода 'dry_run', не трогает 'anketa'.
  const state = candidateState({
    dryRun: false,
    requireConfirmation: true,
    candidates: candidates(1),
    dailyCap: 5,
  })
  const questions = [{ id: 'q1', text: '?', type: 'text' as const, options: [] }]
  const { deps, reported } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => ({ outcome: 'anketa', letter: '', anketa: { questions } }),
  })

  await runAutoApplyCycle(deps)

  assert.equal(reported[0].result.outcome, 'anketa', 'anketa не должна перетираться needs_confirmation')
}

async function testPlainDryRunPlatformOutcomeNotRemapped() {
  // Платформенный dry_run (силуэт-режим, без очереди подтверждения) остаётся простым логом —
  // remap только когда requireConfirmation реально включён.
  const state = candidateState({ dryRun: true, requireConfirmation: false, candidates: candidates(1) })
  const { deps, reported } = makeDeps({
    states: [state],
    sendAutoApplyRun: async () => ({ outcome: 'dry_run', letter: '' }),
  })

  await runAutoApplyCycle(deps)

  assert.equal(reported[0].result.outcome, 'dry_run', 'обычный dry_run без requireConfirmation не remapится')
}

// --- Фаза 3.3: runAnketaResumeCycle — второй визит за подтверждённой анкетой ---

function anketaCandidate(overrides: Partial<AnketaResumeCandidate> = {}): AnketaResumeCandidate {
  return {
    platform: 'hh',
    jobId: 1,
    vacancyId: '1',
    url: 'https://hh.ru/vacancy/1',
    answers: [{ question_id: 'q1', value: '3-5 лет' }],
    letter: '',
    ...overrides,
  }
}

async function testAnketaResumeCycleFillsAndReportsApplied() {
  const { deps, opened, closed, reported, sendCalls } = makeDeps({
    states: [],
    anketas: [anketaCandidate()],
  })

  const results = await runAnketaResumeCycle(deps)

  assert.equal(opened.length, 1, 'открывает вкладку заново под подтверждённую анкету')
  assert.equal(closed.length, 1)
  assert.equal(results[0].outcome, 'applied')
  assert.equal(sendCalls.length, 1)
  assert.equal(sendCalls[0].dryRun, false, 'подтверждение владельца — всегда реальная отправка')
  assert.deepEqual(sendCalls[0].answers, anketaCandidate().answers, 'ответы владельца доходят до content-script')
  assert.equal(reported.length, 1)
  assert.equal(reported[0].dryRun, false, 'outcome=applied -> report как реальная отправка (двигает воронку)')
}

async function testAnketaResumeCycleMultipleCandidatesSleepsBetween() {
  const { deps, opened, delays } = makeDeps({
    states: [],
    anketas: [anketaCandidate({ jobId: 1, vacancyId: '1' }), anketaCandidate({ jobId: 2, vacancyId: '2' })],
  })

  await runAnketaResumeCycle(deps)

  assert.equal(opened.length, 2)
  assert.equal(delays.length, 1, 'пауза между кандидатами, не после последнего')
}

async function testAnketaResumeCycleStopsOnBlocker() {
  let calls = 0
  const { deps } = makeDeps({
    states: [],
    anketas: [anketaCandidate({ jobId: 1 }), anketaCandidate({ jobId: 2 })],
    sendAutoApplyRun: async () => {
      calls += 1
      return { outcome: 'captcha', letter: '' }
    },
  })

  const results = await runAnketaResumeCycle(deps)

  assert.equal(calls, 1, 'капча на первом кандидате -> второй в этот тик не трогаем')
  assert.equal(results.length, 1)
}

async function testAnketaResumeCyclePassesApprovedLetterThrough() {
  // Фаза 3.4: подтверждение письма без анкеты — answers=[], letter несёт одобренный текст,
  // который content-script должен использовать как есть (без новой LLM-генерации).
  const { deps, sendCalls } = makeDeps({
    states: [],
    anketas: [anketaCandidate({ answers: [], letter: 'Одобренное владельцем письмо' })],
  })

  await runAnketaResumeCycle(deps)

  assert.equal(sendCalls.length, 1)
  assert.deepEqual(sendCalls[0].answers, [])
  assert.equal(sendCalls[0].letter, 'Одобренное владельцем письмо')
}

async function testAnketaResumeCycleEmptyLetterPassesUndefined() {
  // Пустая строка (анкета без письма, обычный путь 3.3) не должна становиться '' в сообщении —
  // content-script трактует undefined как "генерировать заново", а '' как "заменить на пустое".
  const { deps, sendCalls } = makeDeps({
    states: [],
    anketas: [anketaCandidate({ letter: '' })],
  })

  await runAnketaResumeCycle(deps)

  assert.equal(sendCalls[0].letter, undefined)
}

// --- Троттлинг ≤2 реальных откликов/мин/площадку (жёсткий гвард в раннере) ---

async function testAnketaResumeCycleWaitsMinRealIntervalBetweenSends() {
  // Досыл подтверждённых не имеет пер-тик лимита — единственная защита от разгона это пол
  // паузы между реальными отправками (auto_apply_min_real_interval_ms).
  const { deps, delays, sendCalls } = makeDeps({
    states: [],
    anketas: [anketaCandidate({ jobId: 1, vacancyId: '1' }), anketaCandidate({ jobId: 2, vacancyId: '2' })],
    minRealIntervalMs: () => 5_000,
    randomDelayMs: () => 42,
  })

  await runAnketaResumeCycle(deps)

  assert.equal(sendCalls.length, 2)
  // Первая отправка — сразу (клок пуст). Между первой и второй: randomDelayMs (42) + добор
  // паузы до 5с в awaitRealApplySlot.
  const bigWaits = delays.filter((d) => d >= 4_000)
  assert.equal(bigWaits.length, 1, 'ровно одна пауза ≥4с — добор до min-интервала перед вторым откликом')
  assert.ok(bigWaits[0] <= 5_000, `добор ${bigWaits[0]} не больше самого интервала`)
}

async function testMainCycleRealApplyBlocksImmediateAnketaResume() {
  // Клок общий между проходами одного тика: реальный отклик в основном цикле заставляет
  // следующий за ним runAnketaResumeCycle подождать min-интервал.
  const { deps, delays } = makeDeps({
    states: [candidateState({ platform: 'hh', candidates: candidates(1), dailyCap: 5, dailyCount: 0 })],
    anketas: [anketaCandidate({ platform: 'hh', jobId: 9, vacancyId: '9' })],
    minRealIntervalMs: () => 5_000,
  })

  await runAutoApplyCycle(deps) // 1 реальный отклик hh -> клок взведён
  await runAnketaResumeCycle(deps) // тот же deps, клок не сброшен

  const bigWaits = delays.filter((d) => d >= 4_000)
  assert.equal(bigWaits.length, 1, 'резюме-визит ждёт min-интервал после реального отклика основного цикла')
}

async function testFirstRealApplyIsImmediate() {
  const { deps, delays } = makeDeps({
    states: [candidateState({ platform: 'hh', candidates: candidates(1), dailyCap: 5, dailyCount: 0 })],
    minRealIntervalMs: () => 60_000,
  })

  await runAutoApplyCycle(deps)

  assert.equal(delays.filter((d) => d >= 1_000).length, 0, 'первый отклик по площадке — без ожидания')
}

async function testAnketaResumeCycleFailureReportsAsNotApplied() {
  const { deps, reported } = makeDeps({
    states: [],
    anketas: [anketaCandidate()],
    sendAutoApplyRun: async () => ({ outcome: 'timeout', letter: '' }),
  })

  const results = await runAnketaResumeCycle(deps)

  assert.equal(results[0].outcome, 'timeout')
  assert.equal(reported[0].dryRun, false, 'резюме-визит всегда боевой: dry_run=false, бэк смотрит на outcome')
}

await testRealModeCapsAtOnePerTick()
await testDailyCapStillEnforcedAcrossTicks()
await testRandomizedPauseWithinWindowForDryRun()
await testDryRunNeverMovesStageAndBudgetsByCap()
await testFailedRealAttemptReportsPlatformDryRunFalse()
await testOpenTabFailureSkipsCandidateWithoutAbortingTick()
await testDisabledPlatformNeverAppearsInLoadedStates()
await testCaptchaOutcomeStopsTickImmediately()
await testPlatformLimitOutcomeStopsTickImmediately()
await testAnketaOutcomeCarriesQuestionsToReport()
await testRequireConfirmationSendsEffectiveDryRunAndRemapsOutcome()
await testRequireConfirmationBudgetsLikeDryRunNotCappedAtOne()
await testRequireConfirmationAnketaOutcomeStaysAnketaNotRemapped()
await testPlainDryRunPlatformOutcomeNotRemapped()
await testAnketaResumeCycleFillsAndReportsApplied()
await testAnketaResumeCycleMultipleCandidatesSleepsBetween()
await testAnketaResumeCycleStopsOnBlocker()
await testAnketaResumeCyclePassesApprovedLetterThrough()
await testAnketaResumeCycleEmptyLetterPassesUndefined()
await testAnketaResumeCycleWaitsMinRealIntervalBetweenSends()
await testMainCycleRealApplyBlocksImmediateAnketaResume()
await testFirstRealApplyIsImmediate()
await testAnketaResumeCycleFailureReportsAsNotApplied()

// --- Heartbeat: createRealDeps.reportTickSummary — итог тика в журнал бэка ---

async function testReportTickSummaryPostsCountsAndDiagnostics() {
  const posts: { url: string; body: unknown }[] = []
  const http = {
    apiUrl: (p: string) => `http://x${p}`,
    apiHeaders: () => ({}),
    apiFetch: async (_action: string, url: string, options?: { body?: string }) => {
      posts.push({ url, body: options?.body ? JSON.parse(options.body) : null })
      // /api/settings → hh включён; preview → 2 кандидата; daily-count → ok
      if (url.endsWith('/api/settings')) {
        return { ok: true, json: async () => ({ auto_apply_config: { hh: { enabled: true, dry_run: false } } }) }
      }
      if (url.includes('/preview')) {
        return {
          ok: true,
          json: async () => ({ auto: [{ job_id: 1, vacancy_id: '1', url: 'u1' }, { job_id: 2, vacancy_id: '2', url: 'u2' }] }),
        }
      }
      if (url.includes('/daily-count')) return { ok: true, json: async () => ({ cap: 22, count: 0 }) }
      return { ok: true, json: async () => ({}) }
    },
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const deps = createRealDeps(http as any)
  await deps.loadPlatformStates() // наполняет диагностику (platformsReady / candidates)
  await deps.reportTickSummary!([
    { platform: 'hh', vacancyId: '1', jobId: 1, outcome: 'applied', letter: '' },
    { platform: 'hh', vacancyId: '2', jobId: 2, outcome: 'timeout', letter: '' },
  ])

  const report = posts.find((p) => p.url.includes('/tick-report'))
  assert.ok(report, 'tick-report отправлен')
  assert.deepEqual(report!.body, {
    platforms_enabled: ['hh'],
    platforms_ready: ['hh'],
    candidates: 2,
    applied: 1,
    needs_confirmation: 0,
    anketa: 0,
    failed: 1, // timeout — не ok-исход и не stop-tick
    blocked: [],
    bail_reason: null,
  })
}

async function testReportTickSummaryCarriesBailReason() {
  const posts: unknown[] = []
  const http = {
    apiUrl: (p: string) => p,
    apiHeaders: () => ({}),
    apiFetch: async (_a: string, url: string, o?: { body?: string }) => {
      if (url.includes('/tick-report')) posts.push(JSON.parse(o!.body!))
      if (url.endsWith('/api/settings')) return { ok: false, status: 502 }
      return { ok: true, json: async () => ({}) }
    },
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const deps = createRealDeps(http as any)
  await deps.loadPlatformStates()
  await deps.reportTickSummary!([])
  assert.equal((posts[0] as { bail_reason: string }).bail_reason, 'settings_http_502')
}

async function testManualSendOverridesDryRun() {
  const state = candidateState({ dryRun: true, candidates: candidates(2), dailyCap: 5, dailyCount: 0, manualSend: true })
  const { deps, opened, reported } = makeDeps({ states: [state] })

  const results = await runAutoApplyCycle(deps)

  assert.equal(opened.length, 2, 'manual send: открываем всех кандидатов, несмотря на dry_run')
  assert.ok(reported.every((r) => r.dryRun === false), 'manual send: репорт всегда dry_run=false')
}

await testManualSendOverridesDryRun()

/** Прод-баг 2026-08-31: раннер снимал флаг ручной отправки только если реально что-то
 *  отправил. Пустая очередь (всё уже разобрано) оставляла `manual_send_pending` взведённым —
 *  и следующий тик снова считал бы себя ручной отправкой. */
async function testManualSendFlagClearedOnEmptyQueue() {
  const state = candidateState({ candidates: [], manualSend: true })
  const { deps, opened, clearedManualSend } = makeDeps({ states: [state] })

  await runAutoApplyCycle(deps)

  assert.equal(opened.length, 0, 'пустая очередь ничего не открывает')
  assert.equal(clearedManualSend.length, 1, 'флаг ручной отправки обязан сняться и без кандидатов')
}

await testManualSendFlagClearedOnEmptyQueue()

/** `manualSend` строится из флага площадки, а не из «есть ли кандидаты» — иначе флаг залипает
 *  (см. тест выше). Проверяем сборку состояний реальными deps. */
async function testLoadPlatformStatesKeepsManualSendOnEmptyQueue() {
  const http = {
    apiUrl: (p: string) => p,
    apiHeaders: () => ({}),
    apiFetch: async (action: string) => {
      if (action === 'auto_apply_settings')
        return { ok: true, json: async () => ({ auto_apply_config: { hh: { enabled: true } } }) }
      if (action === 'auto_apply_preview')
        return { ok: true, json: async () => ({ auto: [], manual_send_pending: true }) }
      if (action === 'auto_apply_daily_count')
        return { ok: true, json: async () => ({ cap: 150, count: 0 }) }
      return { ok: true, json: async () => ({}) }
    },
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const deps = createRealDeps(http as any)
  const states = await deps.loadPlatformStates()
  assert.equal(states.length, 1)
  assert.equal(states[0].manualSend, true, 'флаг ручной отправки виден и при пустой очереди')
}

await testLoadPlatformStatesKeepsManualSendOnEmptyQueue()

await testReportTickSummaryPostsCountsAndDiagnostics()
await testReportTickSummaryCarriesBailReason()

console.log('auto-apply-runner.test.ts: OK')
