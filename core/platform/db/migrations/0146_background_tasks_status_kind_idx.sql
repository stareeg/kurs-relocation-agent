-- 0146_background_tasks_status_kind_idx — группировка очереди админки по (status, kind).
-- 0071 уже держит (kind, status) для claim; фильтр «сбои» начинается со статуса.
create index if not exists background_tasks_status_kind_idx
    on background_tasks (status, kind);
