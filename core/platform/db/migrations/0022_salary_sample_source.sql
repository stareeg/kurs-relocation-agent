-- 0022_salary_sample_source — JS-8.2: воронка кормит корпус калибровки зарплат.
-- До сих пор salary_calibration_samples наполнялись ТОЛЬКО пересланными в бот постами (forwarded).
-- Теперь приорами становятся и факты воронки: названная HR вилка (JS-8.1) и сумма оффера.
-- source отделяет funnel-сэмплы от forwarded (исторические строки → 'forwarded' по дефолту);
-- content_hash дедуплицирует повторные пересчёты/правки одного источника (vacancy_id+сигнатура),
-- чтобы фоновый HR-пересчёт и инлайн-правка оффера не плодили одинаковые точки.
alter table salary_calibration_samples
    add column source       text not null default 'forwarded',
    add column content_hash text not null default '';

create index salary_calibration_samples_source_hash_idx
    on salary_calibration_samples (source, content_hash);
