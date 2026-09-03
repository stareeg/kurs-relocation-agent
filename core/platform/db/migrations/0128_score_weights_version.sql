-- 0128_score_weights_version.sql
-- Этап 5 §5.1, plans/scoring_precision_2026_08_17.md (D7): веса скоринга пересчитываются от
-- резюме на каждом скоринге (auto_weights) — вакансии, оценённые в разные дни, могли получить
-- разные веса по одним и тем же осям (work_format видели 25/21/17 баллов на проде), а доска
-- сравнивала их как одну шкалу, хотя это разные линейки.
--
-- Колонка — денормализация jobs.score->>'weights_version' (core/domains/opportunities/
-- weights_version.py) для дешёвого сравнения «посчитано текущей рубрикой или нет» без разбора
-- jsonb. NULL у существующих строк — честно «версии ещё нет» (Этап 5.2 проставит перескором).

alter table jobs add column if not exists score_weights_version text;
