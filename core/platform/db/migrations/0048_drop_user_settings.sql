-- 0048_drop_user_settings — UX3-1: тумблер автоскоринга убран, автоскоринг всегда включён
-- (расширение сам не дублирует скоринг для уже известных вакансий — check_seen + storage-кэш).
-- `user_settings` (0031) больше никем не читается/не пишется — снесён весь стек:
-- api/routers/settings.py, core/settings/, UserSettingsResponse/Update, фронт use-user-settings.ts.
drop table if exists user_settings;
