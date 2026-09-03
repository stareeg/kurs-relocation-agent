-- 0080_drop_legend — глобальная единая легенда удалена (F-17): ручки GET/PUT/regenerate убраны,
-- писать в эту запись больше некому, оставлять мёртвую строку в БД незачем. Читатели
-- (chat hr_draft, prep_pack) переведены на per-vacancy легенду из пакета скрининга
-- (vacancy_screening_questions).

drop table if exists legend;
