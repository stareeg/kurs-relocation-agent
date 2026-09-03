/**
 * Фаза D редизайна «Расширения»: парсинг листинга career.habr.com/vacancies (discovery) —
 * тот же SSR-JSON, что у страницы вакансии, только ключ `vacancies` вместо `vacancy`
 * (`vacancies.list[]` + `vacancies.meta`). Живая разведка (Playwright, 2026-08-19, залогинен)
 * подтвердила структуру и URL-адресуемую пагинацию (`?page=N`).
 * Запуск: cd extension && npx tsx tests/habr-listing-parse.test.ts
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import { parseHabrListingFromDom } from '../src/dom/extractors/habr.ts'

function ssrHtml(vacancies: unknown): string {
  const json = JSON.stringify({ vacancies }).replace(/</g, '\\u003c')
  return `<!doctype html><html><body>
    <script type="application/json" data-ssr-state="true">${json}</script>
  </body></html>`
}

// --- Есть следующая страница ---
{
  const html = ssrHtml({
    list: [
      { id: 1000168310, href: '/vacancies/1000168310', title: 'IT Product менеджер', company: { title: 'Вкусно - и точка' } },
      { id: 1000167763, href: '/vacancies/1000167763', title: 'Backend разработчик', company: { title: 'Acme' } },
    ],
    meta: { totalResults: 1306, perPage: 25, currentPage: 1, totalPages: 43 },
  })
  const { document } = parseHTML(html)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).document = document

  const url = 'https://career.habr.com/vacancies?type=all'
  const result = parseHabrListingFromDom(url)

  assert.equal(result.cards.length, 2)
  assert.equal(result.cards[0].vacancy_id, 'habr_1000168310')
  assert.equal(result.cards[0].url, 'https://career.habr.com/vacancies/1000168310')
  assert.equal(result.cards[0].title, 'IT Product менеджер')
  assert.equal(result.cards[0].company, 'Вкусно - и точка')
  assert.equal(result.cards[1].vacancy_id, 'habr_1000167763')

  assert.ok(result.nextPageUrl, 'currentPage(1) < totalPages(43) — ожидается ссылка на страницу 2')
  const next = new URL(result.nextPageUrl!)
  assert.equal(next.searchParams.get('page'), '2')
  assert.equal(next.searchParams.get('type'), 'all', 'прочие query-параметры (фильтры) сохраняются')
}

// --- Последняя страница — дальше листать некуда ---
{
  const html = ssrHtml({
    list: [{ id: 1, href: '/vacancies/1', title: 'X', company: { title: 'Y' } }],
    meta: { totalResults: 43, perPage: 25, currentPage: 2, totalPages: 2 },
  })
  const { document } = parseHTML(html)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).document = document
  const result = parseHabrListingFromDom('https://career.habr.com/vacancies?page=2')
  assert.equal(result.nextPageUrl, null)
}

// --- Нет SSR-JSON вовсе — честный пустой результат, не падаем ---
{
  const { document } = parseHTML('<!doctype html><html><body></body></html>')
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).document = document
  const result = parseHabrListingFromDom('https://career.habr.com/vacancies')
  assert.deepEqual(result, { cards: [], nextPageUrl: null })
}

console.log('habr-listing-parse.test.ts OK')
