/**
 * Флоу «Откликнуться» hh.ru (Фаза 2.4) — селекторы + детерминированные ветки (already_applied /
 * no_button / dry_run). Реальный клик+таймауты — не автотест (DOM-таймингов такого рода в
 * плане, тестируются глазами), покрываем только логику, не тайминги.
 * Запуск: cd extension && npx tsx tests/hh-apply-flow.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import {
  detectHhBlocker,
  fillHhAnketaAnswers,
  findHhApplyButton,
  isHhAlreadyApplied,
  parseHhAnketaQuestions,
  runHhApplyFlow,
} from '../src/content/hh-apply-flow.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function applyDom(dom: any) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).document = dom.document
  // `HTMLTextAreaElement` — с самого объекта parseHTML() (лениво резолвящийся геттер, не
  // enumerable), не с globalThis: тот пуст в чистом node-скрипте, setTextareaValue иначе падает
  // с "Cannot read properties of undefined" при первом реальном вызове (заполнение анкеты/письма).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).window = { HTMLTextAreaElement: dom.HTMLTextAreaElement }
  // Node-глобальный `Event` несовместим с dispatchEvent() элементов linkedom (падает на
  // "eventPhase has only a getter") — нужен именно Event ИЗ этого realm'а parseHTML().
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).Event = dom.Event
  // linkedom НЕ реализует нативное activation-поведение input.click() (toggle checked для
  // radio/checkbox) — в реальном браузере оно есть по спецификации независимо от JS-обработчиков,
  // fillAnketaQuestionBody() полагается именно на него. Патчим только для теста, не меняя
  // production-код (там .click() и так корректен в настоящем браузере).
  // `HTMLInputElement.prototype` живёт дольше одного parseHTML() (переиспользуется linkedom
  // между вызовами) — патчить один раз за весь прогон (флаг на прототипе), иначе повторный
  // setDom()/setFullDom() оборачивает уже пропатченный click ЕЩЁ раз и checked дважды
  // тогглится (true -> false) вместо однократного false -> true.
  const InputProto = dom.HTMLInputElement.prototype
  if (!InputProto.__anketaClickPatched) {
    const originalClick = InputProto.click
    InputProto.click = function (this: HTMLInputElement) {
      if (this.type === 'radio' && this.name) {
        for (const el of this.ownerDocument!.querySelectorAll<HTMLInputElement>(
          `input[type="radio"][name="${this.name}"]`,
        )) {
          el.checked = el === this
        }
      } else if (this.type === 'checkbox') {
        this.checked = !this.checked
      }
      originalClick?.call(this)
    }
    InputProto.__anketaClickPatched = true
  }
  return dom.document
}

function setDom(html: string) {
  // <html> явно нужен: без него linkedom принимает сам <body> за documentElement, и
  // `document.body` (используется detectHhBlocker) резолвится в пустой синтетический body.
  return applyDom(parseHTML(`<!doctype html><html><body>${html}</body></html>`))
}

/** Для фикстур, которые уже полный документ (`<html>...</html>`, снятый через
 *  `document.documentElement.outerHTML`) — не оборачивать повторно, иначе linkedom получит
 *  вложенный `<html>` внутри `<body>` и часть контента развалится. */
function setFullDom(html: string) {
  return applyDom(parseHTML(html))
}

// --- findHhApplyButton / isHhAlreadyApplied ---

setDom('<a data-qa="vacancy-response-link-top" href="/applicant/vacancy_response">Откликнуться</a>')
assert.ok(findHhApplyButton(), 'верхняя кнопка найдена')
assert.equal(isHhAlreadyApplied(), false)

setDom('<a data-qa="vacancy-response-link-bottom" href="/applicant/vacancy_response">Откликнуться</a>')
assert.ok(findHhApplyButton(), 'нижняя кнопка найдена, если верхней нет')

setDom('<a data-qa="vacancy-response-link-view-topic" href="/chat/1">Перейти к переписке</a>')
assert.equal(findHhApplyButton(), null, 'кнопки отклика нет после отклика')
assert.equal(isHhAlreadyApplied(), true, 'распознали "уже откликались"')

setDom('<div>ничего релевантного</div>')
assert.equal(findHhApplyButton(), null)
assert.equal(isHhAlreadyApplied(), false, 'нет ни кнопки, ни признака отклика - не "уже откликались"')

// --- runHhApplyFlow: детерминированные ветки ---

async function run() {
  // already_applied - не вызывает generateLetter вовсе.
  setDom('<a data-qa="vacancy-response-link-view-topic" href="/chat/1">Перейти</a>')
  let letterCalls = 0
  let result = await runHhApplyFlow({
    dryRun: false,
    generateLetter: async () => {
      letterCalls += 1
      return 'письмо'
    },
    readingDelayMs: [1, 2],
  })
  assert.equal(result.outcome, 'already_applied')
  assert.equal(result.letter, '')
  assert.equal(letterCalls, 0)

  // no_button - вакансия без кнопки отклика вообще (архив/не то состояние DOM).
  setDom('<div>нет кнопки</div>')
  result = await runHhApplyFlow({
    dryRun: false,
    generateLetter: async () => 'письмо',
    readingDelayMs: [1, 2],
  })
  assert.equal(result.outcome, 'no_button')
  assert.equal(result.letter, '')

  // dry_run - доходит до генерации письма, не кликает (кнопка остаётся в DOM нетронутой).
  setDom('<a data-qa="vacancy-response-link-top" href="/applicant/vacancy_response">Откликнуться</a>')
  let clicked = false
  const doc = (globalThis as any).document
  doc.querySelector('[data-qa="vacancy-response-link-top"]').addEventListener('click', () => {
    clicked = true
  })
  result = await runHhApplyFlow({
    dryRun: true,
    generateLetter: async () => 'сгенерированное письмо',
    readingDelayMs: [1, 2],
  })
  assert.equal(result.outcome, 'dry_run')
  assert.equal(result.letter, 'сгенерированное письмо')
  assert.equal(clicked, false, 'dry-run не должен кликать по кнопке')

  // dry_run + генерация письма упала - не роняет весь флоу, просто letter=''.
  setDom('<a data-qa="vacancy-response-link-top" href="/applicant/vacancy_response">Откликнуться</a>')
  result = await runHhApplyFlow({
    dryRun: true,
    generateLetter: async () => {
      throw new Error('LLM недоступен')
    },
    readingDelayMs: [1, 2],
  })
  assert.equal(result.outcome, 'dry_run')
  assert.equal(result.letter, '')
}

await run()

// --- detectHhBlocker (8.2) — эвристика по тексту страницы ---

setDom('<div>Пожалуйста, введите капчу, чтобы продолжить</div>')
assert.equal(detectHhBlocker(), 'captcha')

setDom('<div>Вы исчерпали лимит откликов на сегодня</div>')
assert.equal(detectHhBlocker(), 'platform_limit')

setDom('<div>Ваше резюме скрыто от работодателей</div>')
assert.equal(detectHhBlocker(), 'resume_hidden')

setDom('<div>Резюме доставлено</div>')
assert.equal(detectHhBlocker(), null, 'обычный успех — не блокер')

// --- Фаза 3.1: парсинг анкеты на реальной фикстуре ---
// tests/fixtures/hh_anketa/vacancy_response_bankssoft_136348378.html — реальный снимок
// страницы /applicant/vacancy_response, разведано вживую 2026-08-18 (реальный отклик,
// «Резюме доставлено» подтверждено). См. plans/hh_integration/anketa_example_bankssoft.md.
const anketaHtml = fs.readFileSync(
  path.resolve(__dirname, '../../tests/fixtures/hh_anketa/vacancy_response_bankssoft_136348378.html'),
  'utf8',
)
setFullDom(anketaHtml)
const questions = parseHhAnketaQuestions()
assert.equal(questions.length, 11, 'на реальной анкете 11 вопросов')

const singleChoice = questions.find((q) => q.text.startsWith('Какой у вас коммерческий опыт'))
assert.ok(singleChoice, 'нашли вопрос про коммерческий опыт Python')
assert.equal(singleChoice!.type, 'single_choice')
assert.deepEqual(
  singleChoice!.options.map((o) => o.label),
  ['Менее 3 лет', '3–5 лет', 'Более 5 лет'],
)

const multiChoice = questions.find((q) => q.text.startsWith('С какими Python-пакетами'))
assert.ok(multiChoice, 'нашли вопрос про пакеты Python')
assert.equal(multiChoice!.type, 'multi_choice')
assert.ok(multiChoice!.options.some((o) => o.label === 'FastAPI'))
assert.ok(multiChoice!.options.some((o) => o.label === 'Asyncio'))

const textQuestion = questions.find((q) => q.text.startsWith('Какой уровень дохода'))
assert.ok(textQuestion, 'нашли вопрос про доход')
assert.equal(textQuestion!.type, 'text')
assert.equal(textQuestion!.options.length, 0)

// Каждый вопрос имеет непустой id (используется для сопоставления ответов при заполнении).
assert.ok(questions.every((q) => q.id.length > 0))
// id вопросов уникальны — иначе fillHhAnketaAnswers перепутает, куда какой ответ вписывать.
assert.equal(new Set(questions.map((q) => q.id)).size, questions.length)

// --- Фаза 3.3: заполнение анкеты подтверждёнными ответами ---

setFullDom(anketaHtml)
const toFill = parseHhAnketaQuestions()
const single = toFill.find((q) => q.type === 'single_choice')!
const multi = toFill.find((q) => q.type === 'multi_choice')!
const text = toFill.find((q) => q.type === 'text')!

fillHhAnketaAnswers([
  { question_id: single.id, value: single.options[1].label },
  { question_id: multi.id, value: `${multi.options[0].label}; ${multi.options[1].label}` },
  { question_id: text.id, value: 'Собрал сервис на FastAPI, снизил задержку на 40 процентов.' },
])

// linkedom не реактивно матчит CSS `:checked` на JS-присвоенное свойство (только на атрибут) —
// проверяем `.checked` напрямую, не через селектор.
const doc2 = (globalThis as any).document
const singleInputs = Array.from(
  doc2.querySelectorAll(`input[name="${single.id}"]`),
) as unknown as HTMLInputElement[]
const checkedSingle = singleInputs.filter((i) => i.checked)
assert.equal(checkedSingle.length, 1, 'single_choice — ровно один вариант отмечен')
assert.equal(checkedSingle[0].value, single.options[1].id)

const multiInputs = Array.from(
  doc2.querySelectorAll(`input[name="${multi.id}"]`),
) as unknown as HTMLInputElement[]
const checkedMulti = multiInputs.filter((i) => i.checked)
assert.equal(checkedMulti.length, 2, 'multi_choice — два варианта отмечены')

const filledTextarea = doc2.querySelector(`textarea[name="${text.id}_text"]`) as any
assert.equal(filledTextarea.value, 'Собрал сервис на FastAPI, снизил задержку на 40 процентов.')

// Неизвестный question_id — молча игнорируется, не должен падать.
assert.doesNotThrow(() => fillHhAnketaAnswers([{ question_id: 'nope', value: 'x' }]))

console.log('hh-apply-flow.test.ts: OK')
