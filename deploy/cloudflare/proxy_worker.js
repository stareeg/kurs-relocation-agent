// Единый прокси-воркер для двух сервисов, недоступных напрямую с рос. хостинга (Selectel):
// - Telegram Bot API (api.telegram.org) — TCP до его IP глушится РКН на уровне пакетов.
// - OpenRouter (openrouter.ai) — свой собственный, отдельный от РКН блок: 403 "Access denied by
//   security policy" на запросы с IP хостинга/России, при этом тот же ключ с другого IP работает
//   штатно (проверено напрямую curl'ом, не догадка) — см. docs/problems.md, 2026-08-05.
// Домены Cloudflare Workers массово не блокируют ни тот, ни другой (слишком много всего на
// Cloudflare, чтобы резать всё подряд), поэтому воркер просто перекладывает hostname на нужный
// апстрим и отдаёт ответ как есть.
//
// Cloudflare сам подставляет в каждый входящий запрос заголовки с реальным IP клиента
// (CF-Connecting-IP, X-Forwarded-For и т.п.) — наивная пересылка `request.headers` как есть
// протаскивает IP заблокированной ВМ прямо в апстрим внутри этих заголовков, и WAF апстрима
// (у OpenRouter — именно так) видит исходный IP и блокирует, даже когда TCP-соединение до
// apstream'а идёт с адреса Cloudflare, не ВМ (баг найден и пофикшен в этот же день — сначала
// воркер отдавал ту же 403, что и напрямую, ровно из-за этой утечки). Поэтому эти заголовки
// явно вырезаются перед пересылкой.
//
// Деплой — deploy/cloudflare/README.md. Секретов внутри нет: воркер не хранит ни токен бота, ни
// ключ OpenRouter, только перекладывает то, что прислал вызывающий (сам бэкенд, с уже настоящими
// credentials в заголовках/пути).

const TELEGRAM_PATH = /^\/(bot\d+:[\w-]+\/\w+|file\/bot\d+:[\w-]+\/.+)$/;
const OPENROUTER_PATH = /^\/api\//;

const STRIP_HEADERS = new Set([
  "cf-connecting-ip",
  "cf-ipcountry",
  "cf-ray",
  "cf-visitor",
  "cf-worker",
  "x-forwarded-for",
  "x-forwarded-proto",
  "x-forwarded-host",
  "x-real-ip",
  "true-client-ip",
  "via",
  "host",
]);

function cleanHeaders(headers) {
  const out = new Headers();
  for (const [key, value] of headers) {
    if (!STRIP_HEADERS.has(key.toLowerCase())) {
      out.set(key, value);
    }
  }
  return out;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    let upstreamHost = null;
    if (TELEGRAM_PATH.test(url.pathname)) {
      upstreamHost = "api.telegram.org";
    } else if (OPENROUTER_PATH.test(url.pathname)) {
      upstreamHost = "openrouter.ai";
    } else {
      return new Response("not found", { status: 404 });
    }

    const target = new URL(url.pathname + url.search, `https://${upstreamHost}`);
    const upstream = await fetch(target.toString(), {
      method: request.method,
      headers: cleanHeaders(request.headers),
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    });

    return new Response(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  },
};
