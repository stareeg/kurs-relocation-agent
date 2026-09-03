-- 0073_career_relocation_phase — A-25: фаза маршрута из R-09 (RoadmapPhase).
-- Зависимости шагов (BLOCKS → depends_on_id) и запрет self-loop уже в 0070;
-- многоузловые циклы отвергает домен (`career.relocation`), не CHECK.

alter table career_relocation_steps
    add column if not exists phase text not null default '';

comment on column career_relocation_steps.phase is
    'Фаза маршрута релокации (R-09 RoadmapPhase.id/title), пусто = вне фаз';

comment on column career_relocation_steps.depends_on_id is
    'BLOCKS: шаг не стартует, пока не закрыт depends_on (замена рёбер plan-графа)';
