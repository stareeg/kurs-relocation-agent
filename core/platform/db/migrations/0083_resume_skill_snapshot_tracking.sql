-- 0083_resume_skill_snapshot_tracking — вход для порога автопересборки снимка навыков (E-02,
-- skills_2026_07_28.md). Без них порог «+N вакансий с прошлого снимка» и «сдвинулся
-- skills-отпечаток резюме» можно было бы только гадать по размеру корпуса.

alter table resume_skill_snapshots add column resume_fp text not null default '';
alter table resume_skill_snapshots add column vacancy_ids jsonb not null default '[]'::jsonb;
