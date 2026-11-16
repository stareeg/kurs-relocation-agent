-- Сверка расхода запуска агента (E-9): итог в agent_runs.usage против журнала вызовов llm_usage.
--
-- agent_runs.usage считает колбэк RunBudget (LangChain on_llm_end), llm_usage пишет клиент
-- модели из сырого usage HTTP-ответа — два независимых пути. Попадания в кэш результатов
-- (cache_hit) модель не вызывают и в бюджет не входят, поэтому исключены.
--
-- Запуск (стенд, внутри /opt/copilot):
--   docker compose -f deploy/compose.yaml exec -T postgres sh -c \
--     "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -v run_id=<id>" < reconcile.sql

\echo 'Итог запуска и журнал вызовов'
with run as (
    select id, status, stop_reason, usage from agent_runs where id = :run_id
), calls as (
    select count(*)::int as calls,
           coalesce(sum(tokens_in), 0)::int as tokens_in,
           coalesce(sum(tokens_out), 0)::int as tokens_out,
           coalesce(sum(cost_usd), 0)::numeric(12, 6) as cost_usd
    from llm_usage
    where agent_run_id = :run_id and not cache_hit
)
select run.id, run.status, run.stop_reason,
       (run.usage ->> 'model_calls')::int as run_calls, calls.calls as log_calls,
       (run.usage ->> 'tokens_in')::int as run_in, calls.tokens_in as log_in,
       (run.usage ->> 'tokens_out')::int as run_out, calls.tokens_out as log_out,
       (run.usage ->> 'cost_usd')::numeric(12, 6) as run_cost, calls.cost_usd as log_cost,
       (run.usage ->> 'tokens_in')::int - calls.tokens_in as diff_in,
       (run.usage ->> 'tokens_out')::int - calls.tokens_out as diff_out
from run, calls;

\echo 'Журнал вызовов по фичам'
select agent, model, count(*)::int as calls,
       sum(tokens_in)::int as tokens_in, sum(tokens_out)::int as tokens_out,
       sum(cost_usd)::numeric(12, 6) as cost_usd
from llm_usage
where agent_run_id = :run_id and not cache_hit
group by agent, model
order by calls desc, agent;

\echo 'Итог запуска по группам'
select g.key as group_name,
       (g.value ->> 'calls')::int as calls,
       (g.value ->> 'tokens_in')::int as tokens_in,
       (g.value ->> 'tokens_out')::int as tokens_out,
       (g.value ->> 'cost_usd')::numeric(12, 6) as cost_usd
from agent_runs r, jsonb_each(r.usage -> 'by_group') g
where r.id = :run_id
order by calls desc;
