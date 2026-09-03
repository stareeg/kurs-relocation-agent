/**
 * Этап 4 редизайна «Расширения» (`plans/extension_pipeline_redesign_2026_08_18.md`): фолбэк
 * `getSerpNextPageUrl` для случая, когда `[data-qa="pager-next"]` не рендерится вовсе — живой
 * снимок hh.ru (2026-08-19) показал, что текущий Magritte-пагинатор отдаёт только пронумерованные
 * `[data-qa="pager-page"]` с `aria-current`, без отдельной стрелки «следующая».
 * Запуск: cd extension && npx tsx tests/hh-serp-pager.test.ts
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import { getSerpNextPageUrl } from '../src/dom/selectors.ts'

// Урезанный снимок реальной вёрстки hh.ru (2026-08-19, поиск «python», страница 1 из 10) — без
// data-qa="pager-next", только пронумерованные ссылки с aria-current на текущей.
const PAGER_PAGES_HTML = `<!doctype html><html><body>
  <nav data-qa="pager-block">
    <a data-qa="pager-page" aria-current="true" href="/search/vacancy?text=python&page=0">1</a>
    <a data-qa="pager-page" aria-current="false" href="/search/vacancy?text=python&page=1">2</a>
    <a data-qa="pager-page" aria-current="false" href="/search/vacancy?text=python&page=2">3</a>
  </nav>
</body></html>`

const { document: pagerPagesDoc } = parseHTML(PAGER_PAGES_HTML)
const next = getSerpNextPageUrl(pagerPagesDoc)
assert.ok(next, 'ожидалась ссылка на следующую страницу через фолбэк pager-page')
assert.match(next!, /page=1$/, 'следующая после активной (page=0) — page=1')

// Последняя страница (aria-current на последней ссылке) — дальше листать некуда.
const LAST_PAGE_HTML = `<!doctype html><html><body>
  <nav data-qa="pager-block">
    <a data-qa="pager-page" aria-current="false" href="/search/vacancy?text=python&page=0">1</a>
    <a data-qa="pager-page" aria-current="true" href="/search/vacancy?text=python&page=1">2</a>
  </nav>
</body></html>`
const { document: lastPageDoc } = parseHTML(LAST_PAGE_HTML)
assert.equal(getSerpNextPageUrl(lastPageDoc), null, 'на последней странице — null, листать некуда')

// Старая вёрстка с явной стрелкой pagerNext — используется в первую очередь, фолбэк не трогается.
const PAGER_NEXT_HTML = `<!doctype html><html><body>
  <a data-qa="pager-next" href="/search/vacancy?text=python&page=5">Дальше</a>
</body></html>`
const { document: pagerNextDoc } = parseHTML(PAGER_NEXT_HTML)
assert.match(getSerpNextPageUrl(pagerNextDoc) || '', /page=5$/, 'явный pagerNext — приоритет над фолбэком')

// Ни pagerNext, ни pager-page, ни aria-current — честный null, не падаем.
const { document: emptyDoc } = parseHTML('<!doctype html><html><body></body></html>')
assert.equal(getSerpNextPageUrl(emptyDoc), null)

console.log('hh-serp-pager.test.ts OK')
