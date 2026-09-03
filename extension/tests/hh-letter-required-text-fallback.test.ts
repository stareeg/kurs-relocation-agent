/**
 * Этап 6 §6.3 (plans/scoring_precision_2026_08_17.md): `detectLetterRequired` на живой странице
 * вакансии hh.ru (2026-08-18, Playwright) — все DOM-маркеры (toggle/input/попап) рендерятся
 * ТОЛЬКО внутри модалки «Откликнуться», которой на пассивной странице (до клика) в DOM просто
 * нет. Прод: `letter_required = true` не было НИ У ОДНОЙ из 329 вакансий — не потому что письмо
 * не требуется, а потому что детектор смотрел не в то место. Регресс на текстовый фолбэк
 * по описанию вакансии (тот же приём, что serpCardTextHints даёт карточкам SERP).
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import { detectLetterRequired } from '../src/dom/selectors.ts'

// Пассивная страница: НЕТ ни toggle/input/попапа (рендерятся только после клика «Откликнуться»),
// ни блока [data-qa="vacancy-response"] — только заголовок и описание, как на реальном hh.ru.
const htmlWithHint = `<html><body>
  <h1 data-qa="vacancy-title">Backend Developer</h1>
  <div data-qa="vacancy-description">
    Мы ищем сильного бэкенд-разработчика. Обязательно приложите сопроводительное письмо
    с рассказом о релевантном опыте — отклики без него не рассматриваются.
  </div>
</body></html>`

const { document: docWithHint } = parseHTML(htmlWithHint)
assert.equal(detectLetterRequired(docWithHint), true)

// Обычное описание без упоминания сопроводительного — не должно давать ложный true.
const htmlWithoutHint = `<html><body>
  <h1 data-qa="vacancy-title">Backend Developer</h1>
  <div data-qa="vacancy-description">Ищем бэкенд-разработчика со стеком Python/FastAPI.</div>
</body></html>`

const { document: docWithoutHint } = parseHTML(htmlWithoutHint)
assert.equal(detectLetterRequired(docWithoutHint), false)

console.log('hh-letter-required-text-fallback.test.ts OK')
