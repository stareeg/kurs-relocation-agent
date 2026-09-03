-- 0049_debrief_resolution — DBR-5: жизненный цикл сигнала разбора (жёлтый→зелёный/красный).
--
-- resolution: pending (сразу после анализа транскрипта, воронка ещё не подтвердила исход) |
-- advanced (последующая переписка с HR подтвердила движение дальше) | rejected (переписка
-- подтвердила явный отказ по этому этапу — триггерит авто-перевод вакансии в «Отказ»,
-- core.interview.debrief_resolution). Решение по resolution принимает LLM по новым сообщениям
-- «Диалога», НЕ по тексту самого транскрипта — собственная оценка кандидата не финальна.
--
-- Частичный индекс на pending — дешёвый lookup «есть ли у вакансии что резолвить» без сканирования
-- всей истории разборов (resolve_pending_debrief_signal дергается на каждое входящее HR-сообщение).
alter table interview_debriefs add column if not exists resolution text not null default 'pending'
    check (resolution in ('pending', 'advanced', 'rejected'));
alter table interview_debriefs add column if not exists resolved_at timestamptz;
alter table interview_debriefs add column if not exists resolved_note text not null default '';

create index if not exists interview_debriefs_pending_idx
    on interview_debriefs (vacancy_id, created_at desc) where resolution = 'pending';

-- 'failed' — этап явно не пройден (отказ по факту переписки), в отличие от 'cancelled' (этап
-- убрали из цепочки руками, к исходу собеса отношения не имеет).
alter table interview_stages drop constraint if exists interview_stages_status_check;
alter table interview_stages add constraint interview_stages_status_check
    check (status in ('scheduled', 'completed', 'cancelled', 'rescheduled', 'failed'));
