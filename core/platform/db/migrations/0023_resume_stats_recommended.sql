-- 0023_resume_stats_recommended — hh перенёс профиль на /applicant/profile/me (2026-07) и там же
-- показывает кнопку «N вакансий» (рекомендации под резюме). Добавляем как ещё одну колонку снимка
-- resume_stats (та же кадансность записи — расширение снимает с той же страницы, AF-2).
alter table resume_stats
    add column recommended_vacancies int not null default 0;
