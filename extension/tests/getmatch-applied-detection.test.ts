/**
 * EXT-R1 (regression, 2026-08-15): `detectGetmatchAlreadyApplied` не должен давать ложный
 * «отклик отправлен» на вакансии, где единственный disabled-элемент — посторонняя кнопка
 * (пагинация/фильтр), а не кнопка отклика. Раньше селектор `button[aria-disabled="true"]`
 * ловил ЛЮБУЮ такую кнопку и проставлял статус «Отклик» всем просмотренным вакансиям getmatch.
 * Запуск: cd extension && npx tsx tests/getmatch-applied-detection.test.ts
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import { detectGetmatchAlreadyApplied } from '../src/dom/selectors-getmatch.ts'

function detect(html: string): boolean {
  const { document } = parseHTML(html)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).document = document
  return detectGetmatchAlreadyApplied(document)
}

// 1. Посторонняя disabled-кнопка (без .b-notification, без текста отклика) → false.
assert.equal(
  detect(
    '<main><section class="b-vacancy-v2">' +
      '<h1>Data Engineer</h1>' +
      '<button aria-disabled="true" class="pagination__next">Дальше</button>' +
      '<button disabled class="filter__apply">Применить</button>' +
      '</section></main>',
  ),
  false,
  'посторонние disabled-кнопки не должны считаться откликом',
)

// 2. Реальный бейдж «вы откликнулись» → true.
assert.equal(
  detect(
    '<main><section class="b-vacancy-v2">' +
      '<h1>Data Engineer</h1>' +
      '<div class="b-notification b-notification_primary">✅ Вы откликнулись на эту вакансию</div>' +
      '</section></main>',
  ),
  true,
  'бейдж «вы откликнулись» детектится',
)

// 3. Кнопка «Откликнуться» (не отправленный отклик) → false.
assert.equal(
  detect(
    '<main><section class="b-vacancy-v2">' +
      '<h1>Data Engineer</h1>' +
      '<button class="b-apply-block__response">Откликнуться</button>' +
      '</section></main>',
  ),
  false,
  'кнопка «Откликнуться» не считается откликом',
)

console.log('getmatch-applied-detection.test.ts OK')
