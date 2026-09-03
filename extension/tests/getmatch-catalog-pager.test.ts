/**
 * Этап 4 редизайна «Расширения» (`plans/extension_pipeline_redesign_2026_08_18.md`) — пагинация
 * каталога getmatch.ru реальна (до 41 страницы), но не адресуется URL (`?page=2` сервер молча
 * отбрасывает) — единственный рабочий сигнал: стрелка «вправо» внутри уже открытой вкладки,
 * `disabled` на последней странице. Живой снимок DOM (Playwright, 2026-08-19).
 * Запуск: cd extension && npx tsx tests/getmatch-catalog-pager.test.ts
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import { clickGetmatchNextPage, hasGetmatchNextPage } from '../src/dom/selectors-getmatch-catalog.ts'

// Урезанный снимок реальной вёрстки (хеш CSS-модулей — `lWbP4a` — меняется от деплоя к деплою,
// сознательно взят другой хеш, чем в живом снимке, чтобы тест не завязывался на конкретный билд).
const MID_PAGE_HTML = `<!doctype html><html><body>
  <div class="Pagination-module__x7q2ab__pagination">
    <button type="button" class="Pagination-module__x7q2ab__left"><img alt="left" src="/icon-left.svg"></button>
    <div class="Pagination-module__x7q2ab__page">1</div>
    <div class="Pagination-module__x7q2ab__page Pagination-module__x7q2ab__pageActive">2</div>
    <div class="Pagination-module__x7q2ab__page">3</div>
    <button type="button" class="Pagination-module__x7q2ab__right"><img alt="right" src="/icon-right.svg"></button>
  </div>
</body></html>`

const { document: midDoc } = parseHTML(MID_PAGE_HTML)
assert.equal(hasGetmatchNextPage(midDoc), true, 'страница 2 из N>2 — есть куда листать дальше')
assert.equal(clickGetmatchNextPage(midDoc), true, 'клик по активной стрелке — успех')

// Последняя страница — стрелка задизейблена.
const LAST_PAGE_HTML = `<!doctype html><html><body>
  <div class="Pagination-module__x7q2ab__pagination">
    <button type="button" class="Pagination-module__x7q2ab__left"><img alt="left" src="/icon-left.svg"></button>
    <div class="Pagination-module__x7q2ab__page Pagination-module__x7q2ab__pageActive">41</div>
    <button type="button" disabled class="Pagination-module__x7q2ab__right"><img alt="right" src="/icon-right.svg"></button>
  </div>
</body></html>`
const { document: lastDoc } = parseHTML(LAST_PAGE_HTML)
assert.equal(hasGetmatchNextPage(lastDoc), false, 'последняя страница — дальше листать некуда')
assert.equal(clickGetmatchNextPage(lastDoc), false, 'клик по задизейбленной стрелке — no-op')

// Класс переименован/CSS-модуль пересобран без «__right» вовсе, но alt текста иконки остался —
// текстовый фолбэк должен найти кнопку через alt, не через класс.
const ALT_FALLBACK_HTML = `<!doctype html><html><body>
  <div class="SomethingElse-module__zz9__wrapper">
    <button type="button"><img alt="right" src="/icon-right.svg"></button>
  </div>
</body></html>`
const { document: altDoc } = parseHTML(ALT_FALLBACK_HTML)
assert.equal(hasGetmatchNextPage(altDoc), true, 'фолбэк по alt="right" находит кнопку без опоры на класс')

// Ни класса, ни alt — честно «дальше некуда», не падаем.
const { document: emptyDoc } = parseHTML('<!doctype html><html><body></body></html>')
assert.equal(hasGetmatchNextPage(emptyDoc), false)
assert.equal(clickGetmatchNextPage(emptyDoc), false)

console.log('getmatch-catalog-pager.test.ts OK')
