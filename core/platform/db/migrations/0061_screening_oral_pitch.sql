-- 0061_screening_oral_pitch — FR3-51/52: per-vacancy устная легенда в каноническом пакете.

alter table vacancy_screening_questions
    add column if not exists oral_pitch text not null default '';
