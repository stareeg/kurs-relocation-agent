/**
 * E-03: индекс рынка «резюме на вакансию» со страницы stats.hh.ru — текстовый якорь «hh.индекс»,
 * не хешированные CSS-модули (план market_redesign_v3, п.2.6.3).
 * Запуск: cd extension && npx tsx tests/hh-market-index-parse.test.ts
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import { getHhPageType, isStatsPage, parseMarketIndexFromDom } from '../src/dom/selectors.ts'

// Урезанная копия реальной структуры бейджа (hashed CSS-modules — план п.2.6, свежий снимок
// plans/hh_Статистика.html): заголовок «hh.индекс» и значение — общий предок на 3-м уровне вверх.
const BADGE_HTML = `<!doctype html><html><body>
  <div class="_badge_1pga6_131 _hhIndex_1pga6_190">
    <div class="_shortInfo_1pga6_194">
      <div class="_titleBlock_1pga6_286">
        <div class="_title_1pga6_259"><div class="_text_1dgql_1">hh.индекс</div></div>
      </div>
      <div class="_valueBlock_1pga6_319">
        <span class="_value_1pga6_292">8.3</span>
        <span class="_valueSub_1pga6_334">по стране</span>
      </div>
    </div>
  </div>
</body></html>`

const { document } = parseHTML(BADGE_HTML)

const parsed = parseMarketIndexFromDom(document)
assert.ok(parsed, 'ожидалось значение индекса')
assert.equal(parsed.value, 8.3)

// Блок ещё не дорисован (SPA) — не падаем, отдаём null.
const { document: emptyDoc } = parseHTML('<!doctype html><html><body></body></html>')
assert.equal(parseMarketIndexFromDom(emptyDoc), null)

// stats.hh.ru — отдельный хост-тип страницы независимо от пути.
assert.equal(getHhPageType('https://stats.hh.ru/'), 'stats_index')
assert.ok(isStatsPage('https://stats.hh.ru/some/path'))
assert.ok(!isStatsPage('https://hh.ru/vacancy/123'))

console.log('hh-market-index-parse.test.ts OK')
console.log('  parsed:', parsed)
