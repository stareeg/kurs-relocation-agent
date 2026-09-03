-- 0143_copilot_logs_admin_idx — составные индексы журнала оператора
-- (plans/admin_panel_2026_08_25.md Этап 5.2). Сейчас есть только одиночные
-- (ts desc), (level), (event) из 0004 и (account_id) из 0109 — для запроса
-- «уровень + окно» и «человек + окно» этого мало: журнал всегда задаёт оба.
create index if not exists copilot_logs_level_ts_idx
    on copilot_logs (level, ts desc);
create index if not exists copilot_logs_account_ts_idx
    on copilot_logs (account_id, ts desc);
