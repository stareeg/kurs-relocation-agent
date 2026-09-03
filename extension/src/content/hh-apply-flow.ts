/**
 * Флоу «Откликнуться» на hh.ru (Фаза 2.4/3, plans/auto_apply_roadmap_2026_08_17.md).
 *
 * DOM разведан вживую через Playwright + владельца: кнопка «Откликнуться» — 2026-08-17
 * (реальный отклик, письмо ушло в Selecty), анкета — 2026-08-18 (реальный отклик с анкетой,
 * plans/hh_integration/anketa_example_bankssoft.md, фикстура
 * tests/fixtures/hh_anketa/vacancy_response_bankssoft_136348378.html). Не предположения.
 *
 * Ключевое отличие от getmatch (main.ts, onGetmatchApplyFlow): кнопка «Откликнуться» —
 * обычная ссылка `<a href>`, не JS-модалка. Без анкеты клик отправляет резюме МГНОВЕННО, без
 * формы, сопроводительное — ОТДЕЛЬНЫЙ шаг ПОСЛЕ отклика (кнопка «Приложить сопроводительное
 * письмо» открывает свою модалку). С анкетой — SPA-переход (URL меняется на
 * `/applicant/vacancy_response?vacancyId=...`, без полной перезагрузки страницы, тот же
 * React-шелл, что и у обычного поиска) на отдельную страницу с вопросами + резюме +
 * опциональным письмом + одним submit — резюме доставляется только после этого сабмита, не
 * после первого клика по «Откликнуться».
 */

import { getRuntimeConfig } from '../dom/extension-runtime-config'
import { waitForCondition } from '../dom/wait-for-condition'

// Селекторы отклика hh — с сервера (`apply_selectors.hh` в рантайм-конфиге расширения), чтобы
// смена `data-qa` на hh.ru чинилась без переустановки zip. `getRuntimeConfig()` всегда отдаёт
// полный набор (зашитый дефолт смержен), поэтому фолбэк не нужен. Дефолты (разведано вживую
// 2026-08-17..18, plans/hh_integration/anketa_example_bankssoft.md) — в
// `core/domains/opportunities/sources/extension_runtime_config.json`.
function hhSel(key: string): string {
  return getRuntimeConfig().apply_selectors.hh?.[key] ?? ''
}

/** Кнопка «Откликнуться» — верхняя или нижняя, какая есть в DOM (обе ведут на один и тот же
 *  отклик, hh.ru рендерит обе на длинных описаниях). */
export function findHhApplyButton(root: ParentNode = document): HTMLElement | null {
  return (
    (root.querySelector(hhSel('responseLinkTop')) as HTMLElement | null) ||
    (root.querySelector(hhSel('responseLinkBottom')) as HTMLElement | null)
  )
}

/** Уже откликались — площадка источник истины по факту клика, не наша БД: кнопка пропадает из
 *  DOM после отклика, заменяется ссылкой на чат/тред (`vacancy-response-link-view-topic`). */
export function isHhAlreadyApplied(root: ParentNode = document): boolean {
  return !findHhApplyButton(root) && !!root.querySelector(hhSel('alreadyApplied'))
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min)
}

/** Синтетическая mouseenter → mousedown → mouseup → click с координатами от
 *  getBoundingClientRect() кнопки — дешёвая защита (2.4), даже если сам клик по настоящему
 *  `<a href>` с высокой вероятностью проходит и без неё (SPA слушает обычный onClick, не строго
 *  event.isTrusted). */
async function humanLikeClick(el: HTMLElement): Promise<void> {
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  await sleep(randomBetween(400, 900))
  const rect = el.getBoundingClientRect()
  const opts = {
    bubbles: true,
    cancelable: true,
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
  }
  el.dispatchEvent(new MouseEvent('mouseenter', opts))
  await sleep(randomBetween(50, 150))
  el.dispatchEvent(new MouseEvent('mousedown', opts))
  await sleep(randomBetween(30, 80))
  el.dispatchEvent(new MouseEvent('mouseup', opts))
  el.dispatchEvent(new MouseEvent('click', opts))
}

/** Вставляет значение в React-контролируемую textarea: нативный value-setter + input-событие
 *  (тот же приём, что gmSetTextareaValue в main.ts — плоское `.value = ...` React не подхватит). */
function setTextareaValue(textarea: HTMLTextAreaElement, text: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )?.set
  if (setter) setter.call(textarea, text)
  else textarea.value = text
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

export type HhApplyOutcome =
  | 'applied'
  | 'already_applied'
  | 'dry_run'
  | 'anketa'
  | 'no_button'
  | 'timeout'
  | 'error'
  | 'captcha'
  | 'platform_limit'
  | 'resume_hidden'

// Фаза 8.2 (owner's spec — план допускает "распознать текст ошибки", не требует точных
// селекторов как у самой кнопки 2.4: hh.ru не показывал ни один из этих экранов за время живой
// разведки DOM, паттерны — эвристика по тексту страницы, не проверенные вживую селекторы).
// Порядок проверки важен: капча важнее лимита (если оба паттерна почему-то совпали, капча —
// более срочный сигнал остановиться и звать владельца).
const CAPTCHA_PATTERNS =
  /капч|проверьте,?\s*что\s*вы\s*не\s*робот|подозрительн\w*\s+актив|признаки?\s+автоматизирован|unusual traffic|captcha/i
const PLATFORM_LIMIT_PATTERNS =
  /исчерпали.{0,20}отклик|достигли.{0,20}лимит\w*.{0,20}отклик|лимит откликов на сегодня|максимальное количество откликов/i
const RESUME_HIDDEN_PATTERNS = /резюме\s+скрыт\w*|резюме\s+не\s+видно\s+работодател|видимость резюме/i

/** Best-effort сканирование текста страницы на известные блокеры площадки (8.2) — зовётся
 *  только когда обычный флоу не дошёл до ожидаемого состояния (не тратим время на сканирование
 *  текста всей страницы на happy path). `textContent`, не `innerText` — не зависит от layout
 *  (`innerText` требует реального рендера, недоступного в юнит-тестах на linkedom).
 *
 *  Живой факт (2026-08-18): текстовое предупреждение «поменяйте видимость резюме» на странице
 *  анкеты НЕ блокирует отправку (кнопка активна, сабмит прошёл) — этот детектор всё равно
 *  срабатывает только когда обычный флоу НЕ дошёл до успеха, так что ложных остановок на живом
 *  прошедшем сабмите не будет; трактовать `resume_hidden` здесь как «стоит проверить», не как
 *  подтверждённый жёсткий блокер каждый раз. */
export function detectHhBlocker(root: ParentNode = document): HhApplyOutcome | null {
  const text = (root as Document).body?.textContent || ''
  if (CAPTCHA_PATTERNS.test(text)) return 'captcha'
  if (PLATFORM_LIMIT_PATTERNS.test(text)) return 'platform_limit'
  if (RESUME_HIDDEN_PATTERNS.test(text)) return 'resume_hidden'
  return null
}

export type AnketaQuestionType = 'text' | 'single_choice' | 'multi_choice'

export interface AnketaOptionDom {
  id: string
  label: string
}

export interface AnketaQuestionDom {
  id: string
  text: string
  type: AnketaQuestionType
  options: AnketaOptionDom[]
}

export interface AnketaAnswerInput {
  question_id: string
  value: string
}

function optionLabel(input: HTMLInputElement): string {
  return input.closest('label')?.textContent?.trim() || input.value
}

/** Распарсить вопросы анкеты (Фаза 3.1) из текущего DOM (страница
 *  `/applicant/vacancy_response`). Один вопрос = один `apply_selectors.hh.anketaQuestionBody`,
 *  текст — `anketaQuestionText` внутри. Тип по инпутам: radio → single_choice, checkbox →
 *  multi_choice, textarea → text. `id`/`for` у инпутов ПУСТЫЕ в реальной разметке — текст
 *  варианта достаётся только через `input.closest('label')`. */
export function parseHhAnketaQuestions(root: ParentNode = document): AnketaQuestionDom[] {
  const bodies = Array.from(
    root.querySelectorAll<HTMLElement>(hhSel('anketaQuestionBody')),
  )
  return bodies.map((body, index) => {
    const text = body.querySelector(hhSel('anketaQuestionText'))?.textContent?.trim() || ''
    const radios = Array.from(body.querySelectorAll<HTMLInputElement>('input[type="radio"]'))
    const checkboxes = Array.from(
      body.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    )
    const textarea = body.querySelector<HTMLTextAreaElement>('textarea')

    if (radios.length) {
      return {
        id: radios[0].name || String(index),
        text,
        type: 'single_choice' as const,
        options: radios.map((r) => ({ id: r.value, label: optionLabel(r) })),
      }
    }
    if (checkboxes.length) {
      return {
        id: checkboxes[0].name || String(index),
        text,
        type: 'multi_choice' as const,
        options: checkboxes.map((c) => ({ id: c.value, label: optionLabel(c) })),
      }
    }
    return {
      id: (textarea?.name || '').replace(/_text$/, '') || String(index),
      text,
      type: 'text' as const,
      options: [],
    }
  })
}

/** Заполнить один вопрос ответом владельца: choice-типы — клик по инпуту(ам), чей видимый
 *  label совпадает с текстом ответа (сопоставление на СТОРОНЕ расширения, бэк присылает
 *  человекочитаемый label, не числовой DOM-`value` — см. anketa.py::_resolve_choice_answer).
 *  Несовпавший фрагмент просто не кликается — лучше неполный ответ, чем клик мимо. */
function fillAnketaQuestionBody(body: HTMLElement, answer: string): void {
  const radios = Array.from(body.querySelectorAll<HTMLInputElement>('input[type="radio"]'))
  const checkboxes = Array.from(body.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))
  const inputs = radios.length ? radios : checkboxes
  if (inputs.length) {
    const wanted = new Set(
      answer
        .split(/[;,\n]/)
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    )
    for (const input of inputs) {
      if (wanted.has(optionLabel(input).trim().toLowerCase()) && !input.checked) {
        input.click()
      }
    }
    return
  }
  const textarea = body.querySelector<HTMLTextAreaElement>('textarea')
  if (textarea) setTextareaValue(textarea, answer)
}

/** Заполнить всю анкету подтверждёнными ответами (Фаза 3.3, второй визит раннера после
 *  approve) — сопоставление по `question_id` (тот же `name` группы инпутов/textarea без
 *  суффикса `_text`, что вернул `parseHhAnketaQuestions`). */
export function fillHhAnketaAnswers(
  answers: AnketaAnswerInput[],
  root: ParentNode = document,
): void {
  const bodies = Array.from(
    root.querySelectorAll<HTMLElement>(hhSel('anketaQuestionBody')),
  )
  const byQuestionId = new Map<string, HTMLElement>()
  for (const body of bodies) {
    const radio = body.querySelector<HTMLInputElement>('input[type="radio"]')
    const checkbox = body.querySelector<HTMLInputElement>('input[type="checkbox"]')
    const textarea = body.querySelector<HTMLTextAreaElement>('textarea')
    const qid = radio?.name || checkbox?.name || (textarea?.name || '').replace(/_text$/, '')
    if (qid) byQuestionId.set(qid, body)
  }
  for (const answer of answers) {
    const body = byQuestionId.get(answer.question_id)
    if (body) fillAnketaQuestionBody(body, answer.value)
  }
}

export interface HhApplyResult {
  outcome: HhApplyOutcome
  /** Приложенное (или, в dry-run, только сгенерированное) письмо — '' если не дошли до письма. */
  letter: string
  /** Распарсенные вопросы анкеты — заполнено только когда outcome === 'anketa' и ответов ещё
   *  не было (первая встреча, паркуем на подтверждение). При заполнении готовыми ответами
   *  (deps.anketaAnswers) сюда ничего не кладём — вопросы уже известны бэку. */
  anketa?: { questions: AnketaQuestionDom[] }
}

export interface HhApplyDeps {
  dryRun: boolean
  /** Сопроводительное на hh.ru — отдельный шаг ПОСЛЕ подтверждённого отклика (не до, как у
   *  getmatch), поэтому письмо генерируем по колбэку, а не заранее. Dry-run тоже генерирует —
   *  2.2 требует «дойти до финального клика», включая реальный текст письма в логе. */
  generateLetter: () => Promise<string>
  /** Окно задержки чтения перед первым действием (мс) — параметризовано, чтобы тесты не ждали
   *  реальных 1.5-4с (owner's spec, README «Поверхность обнаружения»). */
  readingDelayMs?: [number, number]
  /** Таймаут ожидания подтверждения после клика (мс) — параметризовано для тестов. */
  confirmTimeoutMs?: number
  /** Фаза 3.3, второй визит раннера: анкета уже подтверждена владельцем, эти ответы нужно
   *  вписать в форму и досдать её, а не парковать заново. Отсутствует/пусто → первая встреча
   *  (парковка вопросов на подтверждение). */
  anketaAnswers?: AnketaAnswerInput[]
}

function confirmTimeoutMs(deps: HhApplyDeps): number {
  return deps.confirmTimeoutMs ?? getRuntimeConfig().tuning.apply_confirm_timeout_ms
}

/** После успеха («Резюме доставлено») — опциональный шаг с сопроводительным письмом, общий
 *  для обычного флоу и флоу «анкета → сабмит → успех». */
async function attachLetterIfOffered(deps: HhApplyDeps): Promise<string> {
  const attachBtn = document.querySelector<HTMLElement>(hhSel('attachLetterButton'))
  if (!attachBtn) return ''

  const letter = await deps.generateLetter().catch(() => '')
  if (!letter) return ''

  attachBtn.click()
  const textarea = await waitForCondition<HTMLTextAreaElement>(
    () => document.querySelector<HTMLTextAreaElement>(hhSel('letterTextarea')),
    { timeoutMs: 4000 },
  )
  if (!textarea) return ''
  setTextareaValue(textarea, letter)
  document.querySelector<HTMLElement>(hhSel('letterSubmit'))?.click()
  return letter
}

async function waitForAppliedOrBlocker(deps: HhApplyDeps): Promise<HhApplyOutcome> {
  const state = await waitForCondition<'applied'>(
    () => {
      if (document.querySelector(hhSel('attachLetterButton')) || isHhAlreadyApplied()) {
        return 'applied'
      }
      return null
    },
    { timeoutMs: confirmTimeoutMs(deps) },
  )
  if (state === 'applied') return 'applied'
  const blocker = detectHhBlocker()
  if (blocker) return blocker
  return findHhApplyButton() ? 'timeout' : 'error'
}

/**
 * Флоу «Откликнуться»: dry-run доходит до финального клика и логирует «кликнул бы» (2.2), не
 * кликая. Реальный режим — клик → ждём «Резюме доставлено» ИЛИ анкету (Фаза 3.1). Анкета без
 * `deps.anketaAnswers` — парсим вопросы и паркуем (outcome='anketa', ответов ещё нет, бэк
 * сгенерирует черновик и запросит подтверждение владельца). Анкета С `deps.anketaAnswers`
 * (второй визит раннера после approve) — заполняем и досылаем анкету, дальше как обычный
 * успех (опциональное письмо).
 */
export async function runHhApplyFlow(deps: HhApplyDeps): Promise<HhApplyResult> {
  if (isHhAlreadyApplied()) {
    return { outcome: 'already_applied', letter: '' }
  }
  const button = findHhApplyButton()
  if (!button) {
    return { outcome: 'no_button', letter: '' }
  }

  const [minMs, maxMs] = deps.readingDelayMs ?? getRuntimeConfig().tuning.apply_reading_delay_ms
  await sleep(randomBetween(minMs, maxMs))

  if (deps.dryRun) {
    const letter = await deps.generateLetter().catch(() => '')
    return { outcome: 'dry_run', letter }
  }

  await humanLikeClick(button)

  const state = await waitForCondition<'applied' | 'anketa'>(
    () => {
      if (document.querySelector(hhSel('attachLetterButton')) || isHhAlreadyApplied()) {
        return 'applied'
      }
      if (document.querySelector(hhSel('anketaQuestionBody'))) {
        return 'anketa'
      }
      return null
    },
    { timeoutMs: confirmTimeoutMs(deps) },
  )

  if (state === 'anketa') {
    if (!deps.anketaAnswers || deps.anketaAnswers.length === 0) {
      return { outcome: 'anketa', letter: '', anketa: { questions: parseHhAnketaQuestions() } }
    }
    fillHhAnketaAnswers(deps.anketaAnswers)
    await sleep(randomBetween(300, 800))
    const submitBtn = document.querySelector<HTMLElement>(hhSel('anketaSubmit'))
    if (!submitBtn) {
      return { outcome: 'error', letter: '' }
    }
    await humanLikeClick(submitBtn)
    const submitOutcome = await waitForAppliedOrBlocker(deps)
    if (submitOutcome !== 'applied') {
      return { outcome: submitOutcome, letter: '' }
    }
    const letter = await attachLetterIfOffered(deps)
    return { outcome: 'applied', letter }
  }

  if (state !== 'applied') {
    const blocker = detectHhBlocker()
    if (blocker) return { outcome: blocker, letter: '' }
    return { outcome: findHhApplyButton() ? 'timeout' : 'error', letter: '' }
  }

  const letter = await attachLetterIfOffered(deps)
  return { outcome: 'applied', letter }
}
