# Auth (`auth`)

домен бэкенда: `profile` (web_auth) + транспорт `api/routers/meta/auth`

Вход по токену из официального Telegram-бота (AUTH-1): пользователи не создают своих ботов —
ссылка t.me/… приходит в `bot_username` из `GET /auth/status` (кэш getMe или
TELEGRAM_BOT_USERNAME). Токен вставляется в «Параметрах» (автовход при вставке), живёт в
httponly-cookie год. `onboarding.ts` — чистая логика гейта разделов и редиректов
(Параметры → Расширение → Резюме); `use-auth-status.ts` — публичный `GET /auth/status`.
Формы логина нет: anon-состояние ведёт в «Параметры».
