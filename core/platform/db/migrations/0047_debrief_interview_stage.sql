-- 0047_debrief_interview_stage — UX2-9: связать разбор транскрипта с конкретным экземпляром этапа
-- цепочки (interview_stages), не только с грубым форматом/stage. Если у вакансии две «Техничка» на
-- разные даты, оба транскрипта раньше падали в один бакет формата — теперь разбор знает, к какой
-- именно строке цепочки он относится. Nullable — старые разборы и разборы без выбранного этапа
-- (пустая цепочка) остаются валидными.
-- on delete set null — удаление этапа (реордер/чистка цепочки) не должно ронять уже сохранённый разбор.

alter table interview_debriefs
    add column if not exists interview_stage_id bigint references interview_stages (id) on delete set null;

create index if not exists interview_debriefs_stage_idx
    on interview_debriefs (interview_stage_id) where interview_stage_id is not null;
