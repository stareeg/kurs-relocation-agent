// Самопроверка релея без сети и без секретов: поднимает заглушку апстрима и релей,
// проверяет три сценария A-0.
//
//   node deploy/render_relay/selftest.js
//
// 1. служебный токен релея → апстрим получает НАСТОЯЩИЙ ключ курса;
// 2. личный ключ человека → проходит как есть (BYOK не перетирается);
// 3. без RELAY_TOKEN релей ничего не подменяет (старое поведение пасстхру).

const http = require("http");
const { spawn } = require("child_process");
const path = require("path");

const RELAY_TOKEN = "sk-relay-test-token";
const COURSE_KEY = "sk-or-v1-course-key";
const USER_KEY = "sk-or-v1-user-key";

function startUpstream() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ auth: req.headers.authorization || "", path: req.url, body }));
      });
    });
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

function startRelay(port, upstreamPort, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(__dirname, "server.js")], {
      env: {
        ...process.env,
        PORT: String(port),
        OPENROUTER_ORIGIN: `http://127.0.0.1:${upstreamPort}`,
        ...env,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => {
      if (String(chunk).includes("listening")) resolve(child);
    });
    child.stderr.on("data", (chunk) => reject(new Error(String(chunk))));
    setTimeout(() => reject(new Error("relay did not start")), 5000);
  });
}

function call(port, authorization) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({ model: "x", messages: [] });
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port,
        path: "/api/v1/chat/completions",
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": Buffer.byteLength(payload),
          authorization,
        },
      },
      (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => resolve(JSON.parse(body)));
      },
    );
    req.on("error", reject);
    req.end(payload);
  });
}

async function main() {
  const upstream = await startUpstream();
  const withInjection = await startRelay(43101, upstream.port, {
    RELAY_TOKEN,
    OPENROUTER_API_KEY: COURSE_KEY,
  });
  const withoutInjection = await startRelay(43102, upstream.port, {
    RELAY_TOKEN: "",
    OPENROUTER_API_KEY: "",
  });

  const failures = [];
  const check = (name, actual, expected) => {
    if (actual !== expected) failures.push(`${name}: got ${actual}, want ${expected}`);
  };

  check(
    "служебный токен → ключ курса",
    (await call(43101, `Bearer ${RELAY_TOKEN}`)).auth,
    `Bearer ${COURSE_KEY}`,
  );
  check("личный ключ проходит как есть", (await call(43101, `Bearer ${USER_KEY}`)).auth, `Bearer ${USER_KEY}`);
  check(
    "без RELAY_TOKEN подмены нет",
    (await call(43102, `Bearer ${RELAY_TOKEN}`)).auth,
    `Bearer ${RELAY_TOKEN}`,
  );

  withInjection.kill();
  withoutInjection.kill();
  upstream.server.close();

  if (failures.length) {
    console.error("FAIL\n" + failures.join("\n"));
    process.exit(1);
  }
  console.log("relay selftest: ok");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});