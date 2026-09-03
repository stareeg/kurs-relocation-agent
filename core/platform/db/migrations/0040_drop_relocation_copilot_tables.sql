-- 0040_drop_relocation_copilot_tables — DR-4: снос мёртвых таблиц из 0001_init.sql.
-- Все 11 таблиц ниже пережиток изначального более широкого замысла (Career & Relocation
-- Copilot), от которого проект отошёл в пользу чистого поиска работы (см. plans/deep_refactor.md,
-- памятка project_relocation_copilot: релокация отложена в Фазу 7). Аудит (grep по core/repo,
-- api/, bot_app/ — вне migrations/) подтвердил: ни одного обращения к ним нигде в коде.
-- profile/notifications/finance_snapshots/residency_day_log/english_progress/hr_contacts/
-- auth_sessions — ни разу не читались и не писались за всю историю репо (нет core/repo-модуля).
-- interview_logs — вытеснена interview_debriefs (0016)/interview_stages (0006), тоже 0 обращений.
-- documents/visa_items/portfolio_items — репозитории core/repo/{documents,visa,portfolio}.py
-- существуют, но save_*/list_* в них никто не вызывает (plan-граф заморожен, immigration-агент
-- не реализован); удаляются вместе с этой миграцией.
drop table if exists profile;
drop table if exists notifications;
drop table if exists interview_logs;
drop table if exists documents;
drop table if exists visa_items;
drop table if exists portfolio_items;
drop table if exists finance_snapshots;
drop table if exists residency_day_log;
drop table if exists english_progress;
drop table if exists hr_contacts;
drop table if exists auth_sessions;
