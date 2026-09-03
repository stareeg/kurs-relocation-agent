-- 0066_screening_pitch_blocks — раздел «Скрининги»: рассказ хранится блоками (label + строки),
-- «акценты» заменяются «мостами» (требование вакансии → мой факт → как произнести), разбор
-- вакансии кэшируется рядом с пакетом. Таблица — кэш последней генерации (перегенерация
-- затирает), поэтому перенос данных не нужен: старые пакеты пересобираются кнопкой.

alter table vacancy_screening_questions
    add column if not exists pitch_blocks jsonb not null default '[]'::jsonb,
    add column if not exists bridges      jsonb not null default '[]'::jsonb,
    add column if not exists jd_brief     jsonb not null default '{}'::jsonb;

-- accents (список строк-тезисов из резюме) больше не генерируется: его роль забрали bridges.
alter table vacancy_screening_questions drop column if exists accents;
