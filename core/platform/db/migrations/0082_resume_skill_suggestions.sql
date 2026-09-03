-- 0082_resume_skill_suggestions — снимок навыков: «мои + разрывы» в одной таблице (S-04,
-- skills_2026_07_28.md). Шапка снимка отдельно от строк — агрегат один на резюме,
-- строк много и они переживают перезагрузку своим user_state (Решение 6 плана).

create table resume_skill_snapshots (
    id              serial primary key,
    input_fp        text not null default '',
    corpus_size     integer not null default 0,
    selection_rule  text not null default '',
    created_at      timestamptz not null default now()
);

create table resume_skill_suggestions (
    id              serial primary key,
    snapshot_id     integer not null references resume_skill_snapshots(id) on delete cascade,
    skill           text not null,
    state           text not null,                       -- have | add | drop | rename
    renames_to      text,
    importance      text,                                 -- required | preferred | null
    demand_count    integer not null default 0,
    demand_total    integer not null default 0,
    companies       jsonb not null default '[]'::jsonb,
    rationale       text not null default '',
    user_state      text not null default 'pending',       -- pending | accepted | hidden
    state_at        timestamptz
);

create index resume_skill_suggestions_snapshot_idx on resume_skill_suggestions (snapshot_id);
