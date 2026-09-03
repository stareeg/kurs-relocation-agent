/**
 * GM-5.2: парсинг каталога getmatch.ru (`/vacancies`) — список карточек для SERP-счётчика.
 */

import { extractGetmatchVacancyIdFromUrl } from './selectors-getmatch'

export type GetmatchCatalogCard = {
  vacancy_id: string
  title: string
  url: string
  /** EXT-F1: узел карточки на реальной странице (для цветовой подсказки рекомендации). */
  el: Element
}

const GM_CATALOG_SELECTORS = {
  card: '[class*="vacancyCard"], [class*="vacancy-card"], article[class*="vacancy"]',
  titleLink: 'a[href*="/vacancies/"]',
}

function queryAll(root: ParentNode, selector: string): Element[] {
  try {
    return Array.from(root.querySelectorAll(selector))
  } catch {
    return []
  }
}

function parseLinkCard(
  link: HTMLAnchorElement,
  seen: Set<string>,
  el: Element,
): GetmatchCatalogCard | null {
  const href = link.href || ''
  if (!/\/vacancies\/\d+-/.test(href)) return null
  const vacancy_id = extractGetmatchVacancyIdFromUrl(href)
  if (!vacancy_id || seen.has(vacancy_id)) return null
  seen.add(vacancy_id)
  const title = (link.textContent || '').replace(/\s+/g, ' ').trim()
  return {
    vacancy_id,
    title,
    url: href.split('?')[0],
    el,
  }
}

/** Ожидает появления хотя бы одной карточки в каталоге (аналог `waitForApplicationCards`). */
export async function waitForCatalogCards(maxMs = 10000): Promise<void> {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    const n = queryAll(document, GM_CATALOG_SELECTORS.card).length
    if (n > 0) return
    await new Promise((r) => setTimeout(r, 250))
  }
}

/** Карточки вакансий на странице каталога (dedup по gm_{id}). */
export function parseGetmatchCatalogCardsFromDom(
  root: Document | Element = document,
): GetmatchCatalogCard[] {
  const seen = new Set<string>()
  const out: GetmatchCatalogCard[] = []

  for (const card of queryAll(root, GM_CATALOG_SELECTORS.card)) {
    const link = card.querySelector(GM_CATALOG_SELECTORS.titleLink) as HTMLAnchorElement | null
    if (!link) continue
    const item = parseLinkCard(link, seen, card)
    if (item) out.push(item)
  }

  if (!out.length) {
    for (const link of queryAll(root, GM_CATALOG_SELECTORS.titleLink)) {
      const item = parseLinkCard(link as HTMLAnchorElement, seen, link)
      if (item) out.push(item)
    }
  }

  return out
}

/** Ключ страницы каталога для SPA (фильтры/пагинация в query). */
export function getmatchCatalogPageKey(url = location.href): string {
  try {
    const u = new URL(String(url), 'https://getmatch.ru')
    return `${u.pathname}|${u.search}`
  } catch {
    return String(url).split('#')[0]
  }
}

// ── Этап 4 редизайна «Расширения» (plans/extension_pipeline_redesign_2026_08_18.md) ──
// Живая разведка DOM (Playwright, 2026-08-19) закрыла главный открытый вопрос причины #2:
// пагинация каталога РЕАЛЬНО ЕСТЬ (стрелки влево/вправо + пронумерованные страницы, до 41 на
// «/vacancies» без фильтров), но она НЕ адресуется URL — переключение страницы меняет только
// React-состояние (`?page=2` в адресе молча отбрасывается сервером, редиректит обратно на
// «/vacancies»). Единственный рабочий механизм — клик по стрелке «вправо» внутри уже открытой
// вкладки; раннер (`discovery-runner.ts`) обязан держать одну и ту же вкладку каталога живой
// между тиками (см. Этап 4, «рабочий таб») — навигация на тот же URL сбросит React-состояние
// обратно на страницу 1, а не продвинет вперёд.

/** CSS-модули хешированы (`Pagination-module__<хеш>__right`) — хеш меняется от деплоя к деплою,
 *  завязываемся на СУФФИКС класса (`__right`/`__left`), не на класс целиком. Фолбэк — `alt`
 *  текст иконки внутри кнопки (текстовый якорь, «не только CSS-селектор», как требует план). */
function _classEndsWith(el: Element, suffix: string): boolean {
  return Array.from(el.classList).some((c) => c.endsWith(suffix))
}

function _findGetmatchPagerButton(
  root: ParentNode,
  suffix: '__right' | '__left',
  altText: 'right' | 'left',
): HTMLButtonElement | null {
  for (const btn of queryAll(root, 'button')) {
    if (_classEndsWith(btn, suffix)) return btn as HTMLButtonElement
  }
  // Фолбэк — по alt картинки-стрелки внутри кнопки, не по классу.
  for (const img of queryAll(root, `img[alt="${altText}" i]`)) {
    const btn = img.closest('button')
    if (btn) return btn as HTMLButtonElement
  }
  return null
}

/** Есть ли следующая страница каталога — стрелка «вправо» найдена и не задизейблена. null-заключение
 *  (стрелки нет вообще) читаем как «страниц дальше нет» — та же логика, что disabled. */
export function hasGetmatchNextPage(root: Document | Element = document): boolean {
  const btn = _findGetmatchPagerButton(root, '__right', 'right')
  return Boolean(btn) && !btn.disabled
}

/** Клик по стрелке «вправо» — сам факт продвижения на следующую страницу каталога (React-состояние
 *  внутри уже открытой вкладки). false — стрелки нет или она задизейблена (последняя страница). */
export function clickGetmatchNextPage(root: Document | Element = document): boolean {
  const btn = _findGetmatchPagerButton(root, '__right', 'right')
  if (!btn || btn.disabled) return false
  btn.click()
  return true
}

/** Ждём, пока список карточек реально обновится после клика «вправо» (React перерисовывает
 *  асинхронно, без chrome.tabs-события — polling, как `waitForCatalogCards`). `previousFirstId` —
 *  vacancy_id первой карточки ДО клика; как только он меняется (или карточки вообще пропадают на
 *  миг — типично между рендерами), считаем страницу обновлённой. */
export async function waitForCatalogPageChange(
  previousFirstId: string | null,
  maxMs = 6000,
): Promise<void> {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    const cards = parseGetmatchCatalogCardsFromDom(document)
    if (cards.length > 0 && cards[0].vacancy_id !== previousFirstId) return
    await new Promise((r) => setTimeout(r, 200))
  }
}
