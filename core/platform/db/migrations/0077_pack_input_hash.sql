-- 0077_pack_input_hash — L-19: хэш входа рядом со скрининг-пакетом и prep-pack.
-- Совпадение хэша при повторной генерации ("Подготовиться") → отдаём сохранённое, LLM не зовём.
-- Явные пересборки (регенерация легенды, "ещё вопросов") хэш не проверяют — работают как раньше.

alter table vacancy_screening_questions
    add column if not exists input_hash text not null default '';

alter table prep_packs
    add column if not exists input_hash text not null default '';
