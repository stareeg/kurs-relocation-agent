/**
 * Last-line hh vacancy parse: semantic DOM, no network, no data-qa.
 * Chain in parseVacancyFromDom: config → default → structural.
 * Yields title / company / salary / description only — not work format or employment type.
 */

export type StructuralVacancyFields = {
  title: string
  company: string
  salary: string
  description: string
}

const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'NAV', 'HEADER', 'FOOTER', 'SVG'])
const MONEY_RE =
  /\d[\d\s\u00a0]{2,}\s*(?:₽|р\.|руб|RUB|USD|EUR|\$|€)/i
const SALARY_MAX_LEN = 120
const STRUCTURAL_SKIP = 'h1, nav, header, footer, script, style, noscript, svg'

function innerTextOf(el: Element | null | undefined): string {
  if (!el) return ''
  return ((el as HTMLElement).innerText || el.textContent || '').replace(/\s+/g, ' ').trim()
}

function parseStructuralTitle(root: ParentNode): string {
  for (const h1 of Array.from(root.querySelectorAll('h1'))) {
    const text = innerTextOf(h1)
    if (text) return text
  }
  return ''
}

function parseStructuralCompany(root: ParentNode): string {
  const scope = (root as Element).querySelector?.('main') || root
  const link =
    scope.querySelector('a[href*="/employer/"]') ||
    root.querySelector('a[href*="/employer/"]')
  return innerTextOf(link)
}

function walkSalary(node: Element, best: { text: string }): void {
  if (SKIP_TAGS.has(node.tagName)) return
  const children = Array.from(node.children)
  for (const child of children) walkSalary(child, best)
  const childHasMoney = children.some((child) =>
    MONEY_RE.test(innerTextOf(child)),
  )
  if (childHasMoney) return
  const text = innerTextOf(node)
  if (!text || text.length > SALARY_MAX_LEN) return
  if (!MONEY_RE.test(text)) return
  if (!best.text || text.length < best.text.length) best.text = text
}

function parseStructuralSalary(root: ParentNode): string {
  const scope =
    (root as Document).body ||
    ((root as Element).matches?.('body') ? (root as Element) : null) ||
    (root as Element).querySelector?.('body') ||
    (root as Element)
  const best = { text: '' }
  if (scope && (scope as Element).tagName) walkSalary(scope as Element, best)
  else {
    for (const child of Array.from((root as ParentNode).querySelectorAll('body, main, p, span, div'))) {
      walkSalary(child, best)
    }
  }
  return best.text
}

function parseStructuralDescription(root: ParentNode): string {
  const scope =
    (root as Element).querySelector?.('main') ||
    (root as Element).querySelector?.('article') ||
    (root as Document).body ||
    (root as Element)
  if (!scope) return ''
  const clone = scope.cloneNode(true) as Element
  clone.querySelectorAll(STRUCTURAL_SKIP).forEach((el) => el.remove())
  let best = ''
  for (const el of Array.from(clone.querySelectorAll('div, article, section, p'))) {
    const text = innerTextOf(el)
    if (!text) continue
    if (MONEY_RE.test(text) && text.length <= SALARY_MAX_LEN) continue
    if (text.length > best.length) best = text
  }
  if (!best) {
    const fallback = innerTextOf(clone)
    if (fallback && !(MONEY_RE.test(fallback) && fallback.length <= SALARY_MAX_LEN)) {
      best = fallback
    }
  }
  return best
}

/**
 * Semantic parse of an already-rendered vacancy page.
 * Returns null when even a heading is missing — do not invent a vacancy.
 */
export function parseVacancyStructural(
  root: ParentNode = document,
): StructuralVacancyFields | null {
  const title = parseStructuralTitle(root)
  if (!title) return null
  return {
    title,
    company: parseStructuralCompany(root),
    salary: parseStructuralSalary(root),
    description: parseStructuralDescription(root),
  }
}
