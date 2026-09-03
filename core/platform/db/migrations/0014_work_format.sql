-- 0014_work_format — формат работы (удалённо/гибрид/офис) отдельным структурным полем.
-- До этого формат жил только в тексте вакансии + legacy work_schedule (там формат и график hh
-- смешаны: fullDay/remote/shift…). Новое поле наполняется из новой таксономии hh `workFormats`
-- (REMOTE/HYBRID/ON_SITE/FIELD_WORK) парсером и DOM-расширением. Входит в upsert save_job
-- (повторный скоринг обновляет его, как прочие метаданные вакансии).
alter table jobs add column if not exists work_format text;
