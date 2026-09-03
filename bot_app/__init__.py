"""Telegram-бот Career Copilot.

Вторичный канал «на ходу» поверх api/ (основной UI — веб): пересланный пост вакансии →
скоринг и карточка, HR-переписка → разбор и воронка, discovery по пресетам, калибровка
вилок, дайджест и напоминание перед собесом, пуш «себе в Telegram» из веба,
операторские /status и /cost.

Запуск:
    python -m bot_app         # только бот (нужен запущенный api на :8000)
    uvicorn api.main:app …    # API-only: задачи tg_push лежат в очереди до старта бота

Пуш из веба (`POST /api/telegram/push` → kind=`tg_push`) обслуживает процесс бота
(`bot_app.services.push_handler`), не lifespan API.
"""

__version__ = "0.2.0"
