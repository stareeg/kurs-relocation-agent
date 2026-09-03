"""Runtime-состояние бота: in-memory сессии + Postgres-реестр исходящих.

История prep — в Postgres (`core.domains.preparation.prep`); in-memory Q&A/prep-тренировки
бота удалены (DR-3b / TB-0.4). Журнал исходящих сообщений — `message_registry` (TB-3.2;
замена карточек по vacancy_id — TB-4.5).
Pending уборки форвардов батча — `batch_cleanup_pending`.
Pending HR-кнопок — `hr_pending` → Postgres `tg_hr_pending` (TTL сутки).
"""
