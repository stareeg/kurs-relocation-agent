// ВНИМАНИЕ: файл для Render (Node.js), НЕ для Cloudflare Workers.
// В Workers нет `require`/`http` и исполнение идёт в Хельсинки, где OpenRouter отвечает 403
// на запросы курса. Воркер для Telegram лежит отдельно: deploy/cloudflare/proxy_worker.js.
//
// Прокси-релей OpenRouter на фиксированном (не Anycast) регионе — docs/problems.md, 2026-08-05.
//
// Почему не тот же Cloudflare Worker, что уже проксирует Telegram (deploy/cloudflare/
// proxy_worker.js): Cloudflare Workers исполняются в датацентре, ближайшем к вызывающей
// стороне по BGP — с этой ВМ (Selectel) это стабильно Хельсинки (`cf-ray: ...-HEL`, проверено
// 5/5 запросов подряд), а именно этот датацентр OpenRouter блокирует на уровне своего
// Cloudflare Bot Management (ответ содержит `set-cookie` с `Domain=openrouter.ai` — блокирует
// сам OpenRouter, не наш воркер). Смена региона внутри Cloudflare Workers не контролируется
// напрямую (Smart Placement оптимизирует под задержку до апстрима, не под обход блокировки —
// ненадёжно как фикс). Обычный HTTP-сервис с фиксированным регионом (не Anycast) решает это
// детерминированно: один и тот же IP независимо от того, кто и откуда вызывает.
//
// Без внешних зависимостей — только встроенные http/https, чтобы деплой не требовал build-шага.

const http = require("http");
const https = require("https");

const PORT = process.env.PORT || 3000;
const OPENROUTER_PATH = /^\/api\//;
// Куда проксируем. Переопределяется ради самопроверки (deploy/render_relay/selftest.js):
// в проде всегда OpenRouter.
const ORIGIN = new URL(process.env.OPENROUTER_ORIGIN || "https://openrouter.ai");
// A-0: ключ OpenRouter курса живёт ТОЛЬКО здесь, в окружении Render. LiteLLM стенда ходит
// на релей со служебным токеном (RELAY_TOKEN), релей подменяет его настоящим ключом.
// Запрос с любым другим Authorization (личный ключ человека) проходит как есть — BYOK не
// ломается и не утекает на общий счёт.
const RELAY_TOKEN = (process.env.RELAY_TOKEN || "").trim();
const UPSTREAM_KEY = (process.env.OPENROUTER_API_KEY || "").trim();
const TRANSPORT = ORIGIN.protocol === "http:" ? http : https;
const ORIGIN_PORT = Number(ORIGIN.port || (ORIGIN.protocol === "http:" ? 80 : 443));

// Тот же принцип, что в deploy/cloudflare/proxy_worker.js: не пересылать заголовки,
// раскрывающие реальный адрес/платформу вызывающей стороны.
const STRIP_HEADERS = new Set([
  "host",
  "x-forwarded-for",
  "x-forwarded-proto",
  "x-forwarded-host",
  "x-real-ip",
  "true-client-ip",
  "via",
  "cf-connecting-ip",
  "cf-ipcountry",
  "cf-ray",
  "cf-visitor",
  "cf-worker",
  "connection",
]);

function cleanHeaders(rawHeaders) {
  const out = {};
  for (const [key, value] of Object.entries(rawHeaders)) {
    if (!STRIP_HEADERS.has(key.toLowerCase())) out[key] = value;
  }
  return out;
}

function upstreamHeaders(rawHeaders) {
  const headers = cleanHeaders(rawHeaders);
  if (!RELAY_TOKEN || !UPSTREAM_KEY) return headers;
  if ((headers.authorization || "") === `Bearer ${RELAY_TOKEN}`) {
    headers.authorization = `Bearer ${UPSTREAM_KEY}`;
  }
  return headers;
}

const server = http.createServer((req, res) => {
  if (req.url === "/" || req.url === "/health") {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
    return;
  }

  if (!OPENROUTER_PATH.test(req.url)) {
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("not found");
    return;
  }

  const upstreamReq = TRANSPORT.request(
    {
      hostname: ORIGIN.hostname,
      port: ORIGIN_PORT,
      path: req.url,
      method: req.method,
      headers: upstreamHeaders(req.headers),
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );

  upstreamReq.on("error", (err) => {
    res.writeHead(502, { "content-type": "text/plain" });
    res.end("upstream error: " + err.message);
  });

  req.pipe(upstreamReq);
});

server.listen(PORT, () => {
  console.log(
    `openrouter relay listening on :${PORT} upstream=${ORIGIN.origin} ` +
      `key_injection=${RELAY_TOKEN && UPSTREAM_KEY ? "on" : "off"}`,
  );
});
