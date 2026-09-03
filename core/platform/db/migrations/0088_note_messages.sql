-- 0088_note_messages — контексты как чат (UX7): отдельные сообщения вместо одного текстового
-- поля notes.body. Каждое сообщение — своя строка (добавить/удалить/поправить по одному, как в
-- диалоге вакансии). notes.body остаётся конкатенацией сообщений (join "\n\n", репозиторий держит
-- в синхроне на каждой мутации) — RAG-подмешивание и полнотекстовый поиск (search_vector generated
-- column из notes.body/title, см. 0029_notes) продолжают работать без изменений.
create table if not exists note_messages (
    id bigserial primary key,
    note_id bigint not null references notes (id) on delete cascade,
    body text not null,
    created_at timestamptz not null default now()
);

create index if not exists note_messages_note_id_idx on note_messages (note_id, id);

-- Backfill: непустые существующие заметки становятся одним сообщением — старые контексты сразу
-- открываются в новом виде, без пустой ленты и без потери текста.
insert into note_messages (note_id, body, created_at)
select id, body, coalesce(updated_at, created_at, now())
from notes
where btrim(body) <> '';
