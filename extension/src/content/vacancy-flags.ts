/**
 * EXT-F1: цветовая подсказка рекомендации прямо на карточках SERP/каталога — читает уже
 * собранный локальный кэш `score:{vacancy_id}` (тот же, что использует автоскоринг
 * `maybeAutoScore`/`runScoringFlow` в `content/main.ts`), без единого нового backend-вызова.
 * Красит РЕАЛЬНЫЙ DOM-узел карточки на странице (не shadow-host) namespaced-классом —
 * безопасно откатывается при следующем ре-рендере hh/getmatch (карточка просто исчезает вместе
 * с классом, стиль остаётся мёртвым правилом в <head>).
 */

type FlaggableCard = { vacancy_id: string; el?: Element | null }

const FLAG_STYLE_ID = 'jh-flag-style'
const RECOMMENDATIONS = ['strong_apply', 'apply', 'maybe', 'skip'] as const
const FLAG_CLASSES = RECOMMENDATIONS.map((r) => `jh-flag-${r}`)

function ensureFlagStyles() {
  if (document.getElementById(FLAG_STYLE_ID)) return
  const style = document.createElement('style')
  style.id = FLAG_STYLE_ID
  style.textContent = `
    .jh-flag-strong_apply { box-shadow: inset 3px 0 0 #10b981 !important; }
    .jh-flag-apply        { box-shadow: inset 3px 0 0 #0369a1 !important; }
    .jh-flag-maybe        { box-shadow: inset 3px 0 0 #b45309 !important; }
    .jh-flag-skip         { box-shadow: inset 3px 0 0 #94a3b8 !important; }
  `
  document.head.appendChild(style)
}

/** Полные записи `score:{id}` из локального кэша (не только счётчик известных id). */
function getScoreRecords(ids: string[]): Promise<Record<string, any>> {
  return new Promise((resolve) => {
    if (!ids.length) {
      resolve({})
      return
    }
    chrome.storage.local.get(
      ids.map((id) => `score:${id}`),
      (result) => {
        const out: Record<string, any> = {}
        for (const id of ids) {
          const rec = result?.[`score:${id}`]
          if (rec) out[id] = rec
        }
        resolve(out)
      },
    )
  })
}

/** Красит карточки цветом рекомендации; карточки без записи в кэше — не трогает. */
function applyRecommendationFlags(items: FlaggableCard[], records: Record<string, any>) {
  if (!items.length) return
  ensureFlagStyles()
  for (const item of items) {
    if (!item.el) continue
    const recommendation = records[item.vacancy_id]?.score?.recommendation
    const flagClass = recommendation ? `jh-flag-${recommendation}` : ''
    item.el.classList.remove('jh-flag', ...FLAG_CLASSES)
    if (flagClass && FLAG_CLASSES.includes(flagClass)) {
      item.el.classList.add('jh-flag', flagClass)
    }
  }
}

export { getScoreRecords, applyRecommendationFlags }
