/**
 * EXT-G1/G2/G3 investigation tool: opens a real Chromium window against getmatch.ru and passively
 * records everything the owner does — navigation, clicks, scroll, and any DOM element that looks
 * interesting (textareas, dialogs, "сопроводительное"/"обязательно" text) — into a JSONL event log
 * plus small screenshots. Never clicks or submits anything itself — pure observation.
 *
 * Runs until the Chrome window is closed by hand, then writes a summary.json and exits.
 *
 * Usage: node tools/capture-getmatch-apply.mjs [startUrl]
 *
 * Run this yourself in your own terminal (it blocks until you close the browser window):
 *   cd extension && node tools/capture-getmatch-apply.mjs
 */
import { chromium } from 'playwright'
import { mkdirSync, appendFileSync, writeFileSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const profileDir = path.join(__dirname, '.playwright-getmatch-profile')
const sessionId = new Date().toISOString().replace(/[:.]/g, '-')
const outDir = path.join(__dirname, 'capture-output', sessionId)
mkdirSync(outDir, { recursive: true })
const logFile = path.join(outDir, 'events.jsonl')

const startUrl = process.argv[2] || 'https://getmatch.ru/vacancies'

function record(event) {
  event.ts = Date.now()
  appendFileSync(logFile, JSON.stringify(event) + '\n', 'utf-8')
}

const INIT_SCRIPT = `
(() => {
  if (window.__jhRecorderInstalled) return
  window.__jhRecorderInstalled = true

  function describe(el) {
    if (!el || el.nodeType !== 1) return null
    let rect = { x: 0, y: 0, w: 0, h: 0 }
    try {
      const r = el.getBoundingClientRect()
      rect = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
    } catch {}
    return {
      tag: el.tagName,
      id: el.id || null,
      class: typeof el.className === 'string' ? el.className.slice(0, 200) : null,
      dataQa: el.getAttribute ? el.getAttribute('data-qa') : null,
      role: el.getAttribute ? el.getAttribute('role') : null,
      text: (el.textContent || '').trim().slice(0, 150),
      rect,
      outerHtml: (el.outerHTML || '').slice(0, 1500),
    }
  }

  function ancestorChain(el, depth) {
    const chain = []
    let node = el
    for (let i = 0; i < depth && node; i++) {
      chain.push(describe(node))
      node = node.parentElement
    }
    return chain
  }

  document.addEventListener('click', (e) => {
    window.__jhRecordEvent({
      type: 'click',
      url: location.href,
      target: describe(e.target),
      ancestors: ancestorChain(e.target, 4),
    })
  }, true)

  let scrollTimer = null
  window.addEventListener('scroll', () => {
    clearTimeout(scrollTimer)
    scrollTimer = setTimeout(() => {
      window.__jhRecordEvent({
        type: 'scroll',
        url: location.href,
        scrollY: window.scrollY,
        docHeight: document.documentElement.scrollHeight,
      })
    }, 400)
  }, true)

  const INTERESTING_RE = /сопроводительн|обязательно письм|response|отклик/i
  const seen = new WeakSet()
  const mo = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (!node || node.nodeType !== 1) continue
        if (seen.has(node)) continue
        const isTextarea = node.tagName === 'TEXTAREA' || (node.querySelector && node.querySelector('textarea'))
        const isDialog = (node.getAttribute && node.getAttribute('role') === 'dialog') || /modal|dialog|popup/i.test(node.className || '')
        const hasText = INTERESTING_RE.test(node.textContent || '')
        if (isTextarea || isDialog || hasText) {
          seen.add(node)
          window.__jhRecordEvent({
            type: 'interesting_element',
            url: location.href,
            reason: isTextarea ? 'textarea' : isDialog ? 'dialog' : 'text_match',
            el: describe(node),
          })
        }
      }
    }
  })
  mo.observe(document.documentElement, { childList: true, subtree: true })

  window.addEventListener('load', () => {
    window.__jhRecordEvent({ type: 'navigation', url: location.href, title: document.title })
  })
})();
`

async function main() {
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    viewport: null,
  })

  await context.exposeBinding('__jhRecordEvent', async (source, event) => {
    record(event)
    if (event.type === 'click' || event.type === 'interesting_element') {
      const shotPath = path.join(outDir, `shot-${Date.now()}.jpg`)
      try {
        await source.page.screenshot({ path: shotPath, type: 'jpeg', quality: 40 })
        record({ type: 'screenshot', for: event.type, path: shotPath })
      } catch {}
    }
    if (event.type === 'interesting_element') {
      console.log(`[interesting] ${event.reason} @ ${event.url}`)
    }
  })
  await context.addInitScript(INIT_SCRIPT)

  const page = context.pages()[0] || (await context.newPage())
  await page.goto(startUrl, { waitUntil: 'domcontentloaded' })

  console.log('\n=== Окно Chrome открыто ===')
  console.log('Залогинься, ходи по getmatch как обычно: списки, вакансии, «Откликнуться».')
  console.log('Всё пишется в фоне. Просто закрой окно браузера, когда закончишь.\n')

  await new Promise((resolve) => context.on('close', resolve))

  const lines = readFileSync(logFile, 'utf-8').trim().split('\n').filter(Boolean)
  const events = lines.map((l) => JSON.parse(l))
  const summary = {
    sessionId,
    totalEvents: events.length,
    urlsVisited: [...new Set(events.filter((e) => e.type === 'navigation').map((e) => e.url))],
    clickCount: events.filter((e) => e.type === 'click').length,
    interestingElements: events.filter((e) => e.type === 'interesting_element'),
  }
  writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2), 'utf-8')
  console.log(`\nГотово. События: ${outDir}`)
  console.log(`Найдено "интересных" элементов: ${summary.interestingElements.length}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
