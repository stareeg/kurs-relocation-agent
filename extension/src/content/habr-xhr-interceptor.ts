/**
 * S13: MAIN-world content script (career.habr.com, document_start).
 * Список «Ваши отклики» (/profile/responses) подгружается клиентским API `/api/frontend/responses`
 * — в SSR-JSON его нет (только `hhImport`). Поэтому перехватываем fetch/XHR страницы и
 * пересылаем распарсенный JSON в isolated world двумя путями:
 *   1) скрытый <script type="application/json" id="__jh_habr_responses__"> — буфер, который
 *      isolated world читает на mount (страховка от гонки: MAIN world стартует раньше,
 *      document_start < document_idle);
 *   2) window.postMessage — live-обновления при пагинации/фильтрах.
 * В MAIN world chrome.* недоступны — файл самодостаточен и не импортирует ничего.
 */

const RESPONSES_PATH_RE = /\/api\/frontend\/responses(?:\?|$)/

const BUFFER_ID = '__jh_habr_responses__'

function bufferPayload(payload: unknown): void {
  let raw = ''
  try {
    raw = JSON.stringify(payload)
  } catch {
    return
  }
  try {
    let el = document.getElementById(BUFFER_ID) as HTMLScriptElement | null
    if (!el) {
      el = document.createElement('script')
      el.type = 'application/json'
      el.id = BUFFER_ID
      ;(el as HTMLScriptElement).dataset.jhHabrResponses = '1'
      document.documentElement.appendChild(el)
    }
    el.textContent = raw
  } catch {
    /* ignore */
  }
}

function notify(payload: unknown): void {
  bufferPayload(payload)
  try {
    window.postMessage({ __jh_habr_responses: true, payload }, '*')
  } catch {
    /* ignore */
  }
}

function handleText(raw: unknown): void {
  if (typeof raw !== 'string' || !raw) return
  let payload: unknown
  try {
    payload = JSON.parse(raw)
  } catch {
    return
  }
  notify(payload)
}

function matchesUrl(url: unknown): boolean {
  if (url == null) return false
  return RESPONSES_PATH_RE.test(String(url))
}

// Патченные функции лежат в MAIN world рядом с оригиналом сайта — Function.prototype.toString
// на них должен выглядеть как на нативную функцию, иначе тривиально ловится проверкой
// `window.fetch.toString().includes('native code')` (тот же приём, что антидетект-браузеры
// используют против fingerprint-скриптов). Оригинал не трогаем — оборачиваем только новую.
function spoofNativeToString(fn: (...args: unknown[]) => unknown, original: unknown): void {
  try {
    fn.toString = () => Function.prototype.toString.call(original)
  } catch {
    /* toString неперезаписываем — не критично, основная функция всё равно работает */
  }
}

// ── fetch ──
const origFetch = window.fetch.bind(window)
window.fetch = function (...args: Parameters<typeof fetch>): Promise<Response> {
  const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request)?.url
  const result = origFetch(...args)
  if (matchesUrl(url)) {
    result
      .then((resp) => resp.clone().text().then(handleText))
      .catch(() => {
        /* ignore */
      })
  }
  return result
}
spoofNativeToString(window.fetch, origFetch)

// ── XMLHttpRequest ──
const origXhrOpen = XMLHttpRequest.prototype.open
const origXhrSend = XMLHttpRequest.prototype.send

XMLHttpRequest.prototype.open = function (
  this: XMLHttpRequest,
  method: string,
  url: string | URL,
  ...rest: unknown[]
): void {
  ;(this as XMLHttpRequest & { __jh_url?: unknown }).__jh_url = url
  return origXhrOpen.call(this, method, url, ...(rest as [boolean])) as void
}
spoofNativeToString(XMLHttpRequest.prototype.open, origXhrOpen)

XMLHttpRequest.prototype.send = function (this: XMLHttpRequest, ...args: unknown[]): void {
  this.addEventListener('load', () => {
    const url = (this as XMLHttpRequest & { __jh_url?: unknown }).__jh_url
    if (matchesUrl(url)) handleText(this.responseText)
  })
  return origXhrSend.apply(this, args) as void
}
spoofNativeToString(XMLHttpRequest.prototype.send, origXhrSend)

export {}
