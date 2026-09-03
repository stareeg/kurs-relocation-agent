-- 0070_career_domain — R-32: задел домена career (цели, навыки, портфолио, релокация, лента).
-- Без UI/роутеров/сервисов — только таблицы под models/repo. career_facts — позже (A-28).
-- Конвенция: text + CHECK, timestamptz, identity PK. FK шагов релокации — self-ref, ON DELETE SET NULL.

create table career_goals (
    id              bigint      generated always as identity primary key,
    title           text        not null,
    horizon         text        not null default '',
    success_metric  text        not null default '',
    status          text        not null default 'draft'
        check (status in ('draft', 'active', 'achieved', 'abandoned')),
    notes           text        not null default '',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index career_goals_status_idx on career_goals (status, updated_at desc);

create table career_skill_targets (
    id                  bigint      generated always as identity primary key,
    skill               text        not null,
    current_level       integer     not null default 1
        check (current_level between 1 and 5),
    target_level        integer     not null default 3
        check (target_level between 1 and 5),
    assessment_source   text        not null default 'self'
        check (assessment_source in ('self', 'debrief', 'offer', 'market', 'other')),
    goal_id             bigint      references career_goals (id) on delete set null,
    notes               text        not null default '',
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index career_skill_targets_skill_idx on career_skill_targets (skill);
create index career_skill_targets_goal_idx on career_skill_targets (goal_id);

create table career_portfolio_items (
    id              bigint      generated always as identity primary key,
    project         text        not null,
    role            text        not null default '',
    outcome         text        not null default '',
    artifact_url    text        not null default '',
    privacy         text        not null default 'private'
        check (privacy in ('private', 'shareable', 'public')),
    source_ref      text        not null default '',
    notes           text        not null default '',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index career_portfolio_items_privacy_idx on career_portfolio_items (privacy);

create table career_relocation_steps (
    id              bigint      generated always as identity primary key,
    title           text        not null,
    depends_on_id   bigint      references career_relocation_steps (id) on delete set null,
    deadline        timestamptz,
    status          text        not null default 'todo'
        check (status in ('todo', 'in_progress', 'done', 'blocked', 'obsolete')),
    country         text        not null default '',
    domain          text        not null default 'career'
        check (domain in ('career', 'immigration', 'finance', 'language', 'logistics')),
    notes           text        not null default '',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    check (depends_on_id is distinct from id)
);
create index career_relocation_steps_status_idx on career_relocation_steps (status);
create index career_relocation_steps_depends_idx on career_relocation_steps (depends_on_id);

create table career_timeline (
    id              bigint      generated always as identity primary key,
    kind            text        not null
        check (kind in (
            'application', 'stage', 'offer', 'job_start', 'promotion',
            'project', 'certificate', 'relocation', 'other'
        )),
    title           text        not null,
    occurred_at     timestamptz not null default now(),
    payload         jsonb       not null default '{}'::jsonb,
    source_ref      text        not null default '',
    created_at      timestamptz not null default now()
);
create index career_timeline_occurred_idx on career_timeline (occurred_at desc);
create index career_timeline_kind_idx on career_timeline (kind);
