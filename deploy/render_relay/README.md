# OpenRouter-релей на Render (фиксированный регион)

Причина, почему это отдельный сервис, а не ветка в `deploy/cloudflare/proxy_worker.js` (который
уже проксирует Telegram) — `docs/problems.md`, 2026-08-05:

Cloudflare Workers исполняются в датацентре, ближайшем к вызывающей стороне по BGP-маршрутизации
провайдера. С этой ВМ (Selectel) это стабильно **Хельсинки** (`cf-ray: ...-HEL`, воспроизведено
5/5 запросов подряд) — и именно этот датацентр блокирует само **OpenRouter'овское** Cloudflare
Bot Management (ответ содержит `set-cookie` с `Domain=openrouter.ai` — блокирует не наш воркер,
а сам OpenRouter). Внутри Cloudflare Workers сменить регион исполнения напрямую нельзя — Smart
Placement существует, но оптимизирует под задержку до апстрима, а не под обход блокировки;
полагаться на него как на фикс ненадёжно. Telegram эту проблему не имеет (РКН не фильтрует IP
Cloudflare) — там прежний воркер остаётся как есть, без изменений.

Обычный HTTP-сервис в **фиксированном** (не Anycast) регионе решает это детерминированно: один
и тот же IP независимо от того, кто и откуда его вызывает. Render — сейчас единственная из
популярных площадок (Fly.io/Koyeb) с реально бесплатным тиром без банковской карты (проверено
2026-08-05).

**Не выключится от простоя** (важная деталь: у Render free план засыпает через 15 минут без
трафика, следующий запрос будит его ~30-60с) — на практике не страшно: у продукта уже есть
фоновый шедулер («Рынок»: grid/pulse/search каждые 300с), который сам держит сервис тёплым.

## Деплой (5 минут, через дашборд)

1. [render.com](https://render.com) → **Get Started** → войти через GitHub (без карты).
2. **New** → **Web Service** → подключить репозиторий (`career-relocation-copilot`, приватный —
   Render попросит доступ через GitHub App, это стандартный OAuth-шаг).
3. Настройки создания сервиса:
   - **Root Directory**: `deploy/render_relay`
   - **Runtime**: `Node`
   - **Region**: любой НЕ скандинавский (например `Frankfurt` или `Oregon`) — сути не меняет,
     главное не тот, что блокирует OpenRouter; конкретный список регионов покажет форма Render.
   - **Build Command**: оставить пустым (зависимостей нет)
   - **Start Command**: `node server.js`
   - **Instance Type**: `Free`
4. **Create Web Service** → дождаться деплоя (лог должен показать `openrouter relay listening
   on :<port>`).
5. Скопировать URL сервиса (`https://<имя>.onrender.com`).
6. Проверить:
   ```
   curl https://<имя>.onrender.com/health
   curl https://<имя>.onrender.com/api/v1/auth/key -H "Authorization: Bearer <ключ OpenRouter>"
   ```
   Первое — `ok`, второе — `{"data":{...}}` с полями ключа (не `{"success":false,...}"`).

## Подключить к бэкенду

На ВМ, в `.env`:
```
OPENROUTER_BASE_URL=https://<имя>.onrender.com/api/v1
```
Перезапустить `api`+`bot` (иначе `.env` не перечитается):
```
docker compose -f deploy/compose.yaml -f deploy/compose.prod.yaml --env-file .env up -d api bot
```
Лог при старте — `OpenRouter прогрет: GET /models → 200` (`core/platform/http/client.py`) вместо
`403`.
