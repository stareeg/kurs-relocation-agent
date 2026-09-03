-- 0069_drop_dead_subsystems — R-15: снос таблиц/схемы мёртвых подсистем.
-- agent_tasks / judge_feedback — оркестратор и judge (R-13/R-14).
-- mirror_retry — очередь зеркала PG→Neo4j (R-07/R-10, plan-граф и memory удалены).
-- схема checkpoints — LangGraph checkpointer (R-14); в конфиге было checkpoints, не checkpoint.
-- daily_cost_* — инертные seed-строки из 0050 (circuit breakers давно сняты).
-- Перед применением: pg_dump в logs/r15_dead_subsystems_YYYY-MM-DD.sql.

drop table if exists agent_tasks;
drop table if exists judge_feedback;
drop table if exists mirror_retry;

drop schema if exists checkpoints cascade;
drop schema if exists checkpoint cascade;

delete from app_settings
 where key in ('daily_cost_limit_usd', 'daily_cost_hard_limit_usd');
