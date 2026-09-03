-- 0103_serial_sequence_grants — fix найденный при живой проверке M2 (RLS-тесты на реальном
-- Postgres впервые прогнаны против 0101/0102): `grant ... on <table> to app_rls` даёт право
-- INSERT в таблицу, но НЕ право дёргать nextval() чужой implicit-последовательности `serial`.
--
-- Для `bigint generated always as identity` (jobs, hr_threads, resumes, …) это не нужно —
-- identity-последовательность привязана к колонке и неявно доступна вместе с INSERT на таблицу.
-- Но `resume_skill_snapshots`/`resume_skill_suggestions` (0082, M1) и `offer_comparisons_cache`
-- (0065, M2) заведены старым стилем `id serial primary key` — под app_rls insert падал
-- с `InsufficientPrivilegeError: нет доступа к последовательности …_id_seq` (обнаружено
-- tests/test_rls_resume.py и tests/test_rls_offers.py на живой БД). Тот же класс ошибки, что
-- забытый table-grant (план §1, «Заодно») — просто на объекте другого типа.

grant usage, select on sequence
    resume_skill_snapshots_id_seq,
    resume_skill_suggestions_id_seq,
    offer_comparisons_cache_id_seq
to app_rls, app_admin;
