-- 0033_legend_and_screening_questions — динамическая легенда (LLM/БД) и сохраняемые вопросы под
-- вакансию. Заменяет удалённые статичные .md/.json (resume/legend, resume/hr_bank.json): легенда
-- теперь одна запись в БД, перегенерируется кнопкой на базе резюме+приоритетов; вопросы под
-- вакансию сохраняются (не регенерируются каждый раз), перегенерация затирает старые.

-- Легенда: единая самопрезентация владельца. Одна строка (id=1 фикс) — upsert детерминирован,
-- не накапливаем версии (канон один, правка/перегенерация перезаписывают).
create table if not exists legend (
    id          int         not null default 1 primary key,
    content     text        not null default '',
    updated_at  timestamptz not null default now(),
    check (id = 1)
);
-- Гарантируем наличие строки-ядра, чтобы GET никогда не падал на отсутствии записи.
insert into legend (id, content) values (1, '') on conflict (id) do nothing;

-- Вопросы под вакансию: кэш последней генерации по vacancy_id (не история — перегенерация
-- затирает). По образцу vacancy_pitch (0028), но отдельной таблицей: вопросы структурированы
-- (groups → questions), хранятся как jsonb. vacancy_id = HH/getmatch id (с префиксом gm_), БЕЗ
-- FK на jobs — вопросы могут быть для вакансии вне jobs (как prep/debrief).
create table if not exists vacancy_screening_questions (
    vacancy_id      text        not null primary key,
    groups          jsonb       not null default '[]'::jsonb,
    generated_at    timestamptz not null default now()
);
