-- 0020_conversation_kind — единая модель разговора по вакансии (R-4).
-- hr_threads уже = «разговор по вакансии» (ключ vacancy_id, delete-каскад, статус, компания).
-- Делаем его контейнером и для HR-переписки, и для уточняющего LLM-чата владельца — чтобы по одной
-- вакансии не плодились параллельные чаты из разных источников (карточка веба / расширение).
-- Сообщению добавляем `kind` (тип реплики), он авторитетнее бинарного `direction`:
--   hr_in        — HR → владелец (входящее от рекрутера)
--   hr_out       — владелец → HR (исходящее владельцем)
--   llm_user     — владелец → ассистент (уточняющий вопрос)
--   llm_assistant— ассистент → владелец (ответ LLM)
-- `direction` остаётся согласованным: out = реплику написал владелец, in = владелец её получил.

alter table hr_messages add column if not exists kind text not null default 'hr_in';

-- backfill из direction (один раз). Идемпотентно: после первого прогона строки HR уже в hr_in/hr_out,
-- а llm_* не появятся до записи через приложение — повторный прогон не тронет их (guard по kind).
update hr_messages
   set kind = case when direction = 'out' then 'hr_out' else 'hr_in' end
 where kind = 'hr_in';

alter table hr_messages drop constraint if exists hr_messages_kind_check;
alter table hr_messages add constraint hr_messages_kind_check
    check (kind in ('hr_in', 'hr_out', 'llm_user', 'llm_assistant'));

-- выборка ленты по типам (HR-факты кормятся только hr_in/hr_out, не llm-болтовнёй).
create index if not exists hr_messages_kind_idx on hr_messages (thread_id, kind);

-- статус треда += archived (архивирование разговора кнопкой, мягкое сокрытие из списка).
alter table hr_threads drop constraint if exists hr_threads_status_check;
alter table hr_threads add constraint hr_threads_status_check
    check (status in ('active', 'waiting', 'closed', 'archived'));
