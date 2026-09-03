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

  const upstreamReq = https.request(
    {
      hostname: "openrouter.ai",
      path: req.url,
      method: req.method,
      headers: cleanHeaders(req.headers),
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
  console.log(`openrouter relay listening on :${PORT}`);
});
