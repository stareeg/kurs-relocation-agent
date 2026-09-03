-- 0127: канон написаний matched_niche (Этап 4 §4.2, plans/scoring_precision_2026_08_17.md) —
-- разовый бэкфилл существующих строк. Новые скоринги канонизируются в коде
-- (core/domains/opportunities/niche_canon.py, тот же список синонимов) — этой миграцией
-- приводим уже накопленные данные в тот же вид, иначе аналитика по нишам продолжает считать
-- «mlops/llmops» и «mlops и llmops» разными нишами. На проде MLOps/LLMOps встречалось в
-- 5 написаниях (189 упоминаний), RAG - в 3, AI Safety - в 2.
with alias_map (raw_fold, canon) as (
    values
        ('mlops/llmops', 'MLOps/LLMOps'),
        ('mlops и llmops', 'MLOps/LLMOps'),
        ('llmops и mlops', 'MLOps/LLMOps'),
        ('mlops', 'MLOps/LLMOps'),
        ('llmops', 'MLOps/LLMOps'),
        ('llm-инфраструктура', 'MLOps/LLMOps'),
        ('llm инфраструктура', 'MLOps/LLMOps'),
        ('llm & rag', 'LLM & RAG'),
        ('llm и rag', 'LLM & RAG'),
        ('rag и graphrag', 'LLM & RAG'),
        ('rag', 'LLM & RAG'),
        ('graphrag', 'LLM & RAG'),
        ('llm', 'LLM & RAG'),
        ('ai safety & guardrails', 'AI Safety & Guardrails'),
        ('ai safety и guardrails', 'AI Safety & Guardrails'),
        ('ai safety', 'AI Safety & Guardrails'),
        ('guardrails', 'AI Safety & Guardrails'),
        ('agentic ai', 'Agentic AI'),
        ('разработка ai-агентов', 'Agentic AI'),
        ('разработка ai агентов', 'Agentic AI'),
        ('multi-agent systems', 'Agentic AI'),
        ('multi agent systems', 'Agentic AI')
),
niches as (
    select
        j.id as job_id,
        elem.ordinality as ord,
        coalesce(m.canon, trim(elem.value)) as canon
    from jobs j
    -- NULL-guard, не WHERE-фильтр: jsonb_array_elements_text падает с ошибкой на скаляре/
    -- объекте (не на NULL - NULL молча даёт 0 строк), а LATERAL вызывает функцию до WHERE,
    -- так что WHERE после join не спас бы от ошибки на кривых legacy-строках.
    cross join lateral jsonb_array_elements_text(
        case
            when jsonb_typeof(j.score #> '{role_content_match,matched_niche}') = 'array'
            then j.score #> '{role_content_match,matched_niche}'
        end
    ) with ordinality as elem(value, ordinality)
    left join alias_map m on m.raw_fold = lower(trim(elem.value))
),
dedup as (
    select distinct on (job_id, lower(canon)) job_id, canon, ord
    from niches
    order by job_id, lower(canon), ord
),
agg as (
    select job_id, jsonb_agg(canon order by ord) as canon_array
    from dedup
    group by job_id
)
update jobs j
set score = jsonb_set(j.score, '{role_content_match,matched_niche}', a.canon_array, false)
from agg a
where j.id = a.job_id
  and j.score #> '{role_content_match,matched_niche}' is distinct from a.canon_array;
