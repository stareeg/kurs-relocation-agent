-- 0056_hr_threads_funnel_suggestion — FR2-86: авто-предложение сдвига воронки из HR-диалога.
-- LLM (stage_type, extract-тир) предлагает статус; владелец применяет одним кликом в шапке чата.
-- suggestion_source_message_id — мягкая ссылка без FK: каскад удаления треда→реплик иначе
-- упирается в self-ref hr_threads→hr_messages (см. аналогичный риск у parent→child FK).

alter table hr_threads
    add column if not exists suggested_funnel_status text,
    add column if not exists suggested_stage_type text,
    add column if not exists suggestion_source_message_id bigint;
