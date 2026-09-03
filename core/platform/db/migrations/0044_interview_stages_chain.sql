-- 0044_interview_stages_chain — RD-19: interview_stages становится первоклассным веб-объектом
-- (цепочка этапов конкретной вакансии), stage_type — канон формата собеса для веба.
--
-- position — ручной порядок цепочки (перетаскивание в UI), независимый от scheduled_at (этап без
-- даты всё равно занимает место в цепочке). CHECK расширен superset'ом: добавлены business_case и
-- final (форматы Техничек, RD-9), soft_skills/manager из старого набора НЕ убраны — их продолжает
-- писать LLM-классификатор HR-сообщений бота (core/scoring/stage_type_llm.py), ломать этот пайплайн
-- вне скоупа RD-19. Веб-цепочка проецирует soft_skills/manager в «Финал» на уровне фронта
-- (frontend/src/features/prep/stages.ts), не в БД — без потери исходной классификации.
--
-- calendar_event_id/calendar_event_url — мёртвый груз с DR (Calendar снесён), выпиливаем.

alter table interview_stages drop constraint if exists interview_stages_stage_type_check;
alter table interview_stages add constraint interview_stages_stage_type_check
    check (stage_type in (
        'hr_screening', 'live_coding', 'system_design', 'theory',
        'soft_skills', 'manager', 'business_case', 'final'
    ));

alter table interview_stages add column if not exists position integer not null default 0;

alter table interview_stages drop column if exists calendar_event_id;
alter table interview_stages drop column if exists calendar_event_url;

-- Бэкофилл порядка для уже существующих строк: хронология по scheduled_at (без даты — в конец).
with ranked as (
    select id, row_number() over (
        partition by vacancy_id order by scheduled_at nulls last, id
    ) - 1 as rn
    from interview_stages
)
update interview_stages s set position = ranked.rn
from ranked
where ranked.id = s.id;

create index if not exists interview_stages_vacancy_position_idx
    on interview_stages (vacancy_id, position);
