-- 0041_prep_packs — RD-16: авто-бриф подготовки под конкретный этап конкретной вакансии.
-- Один бриф на (vacancy_id, stage), НЕ накопительная история (в отличие от interview_debriefs) —
-- перегенерация затирает старый текст, фронт ревьюит diff перед сохранением (паттерн «Перегенерировать
-- легенду», 0033). vacancy_id = HH/getmatch id, БЕЗ FK на jobs (как debrief/prep — бриф может
-- жить для вакансии вне jobs).
create table if not exists prep_packs (
    vacancy_id  text        not null,
    stage       text        not null,
    content     text        not null default '',
    updated_at  timestamptz not null default now(),
    primary key (vacancy_id, stage)
);
